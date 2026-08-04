"""Core algorithm tests for flood-inundation-modeling."""
import sys
import os

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))
from conftest import mod as fl


class TestStaticInundation:
    def test_below_water_level_inundated(self):
        dem = np.array([[1.0, 6.0], [3.0, 8.0]], dtype=np.float32)
        mask = fl.static_inundation(dem, water_level=5.0)
        # 1.0 和 3.0 < 5 → True; 6.0 和 8.0 → False
        assert mask[0, 0] == True
        assert mask[1, 0] == True
        assert mask[0, 1] == False
        assert mask[1, 1] == False

    def test_no_inundation_when_water_low(self):
        dem = np.full((8, 8), 10.0, dtype=np.float32)
        mask = fl.static_inundation(dem, water_level=5.0)
        assert mask.sum() == 0


class TestConnectedInundation:
    def test_excludes_isolated_pit(self):
        """内部孤立洼地不应被 connected 模式淹没，但 static 会。"""
        dem = np.full((16, 16), 10.0, dtype=np.float32)
        # 连通到左边界的低洼沟（淹没到边界）
        dem[8, 0:5] = 1.0
        # 内部孤立洼地（四周被高地包围，不连通边界）
        dem[3, 10:13] = 1.0
        dem[4, 10:13] = 1.0

        static_mask = fl.static_inundation(dem, 5.0)
        conn_mask = fl.connected_inundation(dem, 5.0)

        # static 包含孤立洼地
        assert static_mask[3, 11] == True
        # connected 排除孤立洼地
        assert conn_mask[3, 11] == False
        # connected 保留连通到边界的沟
        assert conn_mask[8, 0] == True
        assert conn_mask[8, 4] == True
        # connected 是 static 的子集
        assert conn_mask.sum() <= static_mask.sum()

    def test_empty_when_no_water(self):
        dem = np.full((10, 10), 10.0, dtype=np.float32)
        assert fl.connected_inundation(dem, 5.0).sum() == 0


class TestInundationDepth:
    def test_depth_nonnegative(self):
        dem = np.array([[1.0, 6.0], [3.0, 8.0]], dtype=np.float32)
        mask = fl.static_inundation(dem, 5.0)
        depth = fl.inundation_depth(dem, 5.0, mask)
        assert (depth >= 0).all()

    def test_depth_values(self):
        dem = np.array([[1.0, 6.0], [3.0, 8.0]], dtype=np.float32)
        mask = fl.static_inundation(dem, 5.0)
        depth = fl.inundation_depth(dem, 5.0, mask)
        # 淹没区：5-1=4, 5-3=2；非淹没区=0
        assert np.isclose(depth[0, 0], 4.0)
        assert np.isclose(depth[1, 0], 2.0)
        assert depth[0, 1] == 0.0
        assert depth[1, 1] == 0.0


class TestPixelArea:
    def test_positive_area(self):
        a = fl.pixel_area_m2([116.0, 39.0, 117.0, 40.0], 128, 128)
        assert a > 0

    def test_area_scales_with_extent(self):
        small = fl.pixel_area_m2([116.0, 39.0, 116.5, 39.5], 100, 100)
        large = fl.pixel_area_m2([116.0, 39.0, 117.0, 40.0], 100, 100)
        assert large > small


class TestFloodStats:
    def test_area_and_volume_consistency(self):
        dem = np.zeros((10, 10), dtype=np.float32)
        dem[:5, :] = 1.0   # 上半部高
        dem[5:, :] = -1.0  # 下半部低（淹没）
        mask = fl.static_inundation(dem, 0.0)
        depth = fl.inundation_depth(dem, 0.0, mask)
        pixel_area = 100.0
        stats = fl.flood_stats(mask, depth, pixel_area)
        assert stats["inundated_pixels"] == 50
        assert np.isclose(stats["area_m2"], 50 * 100.0)
        # 每像元水深=1, 体积 = 50*1*100
        assert np.isclose(stats["volume_m3"], 50 * 1.0 * 100.0)
        assert np.isclose(stats["mean_depth_m"], 1.0)


class TestRunFlood:
    def test_bad_method_raises(self):
        dem = np.zeros((8, 8), dtype=np.float32)
        with pytest.raises(fl.UsageError):
            fl.run_flood(dem, 5.0, method="bogus")

    def test_non_2d_raises(self):
        dem = np.zeros((2, 8, 8), dtype=np.float32)
        with pytest.raises(fl.ValidationError):
            fl.run_flood(dem, 5.0)

    def test_run_returns_shapes(self):
        dem = np.random.uniform(0, 20, (32, 32)).astype(np.float32)
        mask, depth, stats = fl.run_flood(dem, 8.0, method="static",
                                          bbox=[116, 39, 117, 40])
        assert mask.shape == (32, 32)
        assert depth.shape == (32, 32)
        assert (depth >= 0).all()
        assert stats["water_level"] == 8.0


class TestSynthetic:
    def test_synthetic_dem_shape(self):
        dem, info = fl.generate_synthetic_dem([116, 39, 117, 40])
        assert dem.shape == (128, 128)
        assert info["width"] == 128
        assert np.isfinite(dem).all()

    def test_connected_excludes_pit_in_synthetic(self):
        """合成 DEM 含内部孤立洼地：connected 模式应比 static 少淹没。"""
        dem, _ = fl.generate_synthetic_dem([116, 39, 117, 40], seed=7)
        wl = 18.0  # 较高水位以同时淹没河谷与洼地
        static_mask = fl.static_inundation(dem, wl)
        conn_mask = fl.connected_inundation(dem, wl)
        assert conn_mask.sum() <= static_mask.sum()


class TestGeoTiffIO:
    def test_roundtrip(self, tmp_path):
        arr = np.random.uniform(0, 50, (24, 24)).astype(np.float32)
        bbox = [116.0, 39.0, 117.0, 40.0]
        path = str(tmp_path / "dem.tif")
        fl.write_geotiff(path, arr, bbox)
        assert os.path.exists(path)
        back, rbbox = fl.read_geotiff(path)
        assert back.shape == arr.shape
        np.testing.assert_allclose(rbbox, bbox, atol=1e-6)
        np.testing.assert_allclose(back, arr, atol=1e-4)

    def test_read_missing_raises(self):
        with pytest.raises(fl.UsageError):
            fl.read_geotiff("/nonexistent/nope.tif")
