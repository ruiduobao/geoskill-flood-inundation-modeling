#!/usr/bin/env python3
"""flood-inundation-modeling — 洪水淹没模拟

基于 DEM 的 Bathtub（浴缸）静态洪水淹没模拟。给定一个水位（water_level），
所有高程低于该水位的像元被视为潜在淹没区。实现两种模式：

- **static**：纯静态淹没，凡 DEM < water_level 的像元均计为淹没（含孤立洼地）。
- **connected**：水文连通性约束，从栅格边界种子做 flood-fill（scipy.ndimage.label
  连通域分析），只保留与边界连通的淹没区，排除内部孤立洼地（这些洼地在真实物理
  过程中不会被外部洪水填充）。

水深 = water_level − DEM（仅在淹没区内，非负）。输出淹没范围栅格、水深栅格，
以及淹没面积 / 蓄水体积统计 JSON。

数据源：本地 DEM GeoTIFF（EPSG:4326），或 ``--synthetic`` 生成含河谷洼地的
模拟 DEM 用于离线测试。

隐私声明 / Privacy：
- 默认完全离线运行，不发起任何网络请求。
- ``--synthetic`` 模式完全无网络。
- 所有处理在本地完成，不上传任何用户数据。

Usage:
    python flood-inundation-modeling.py --input dem.tif --water-level 5.0 --method connected
    python flood-inundation-modeling.py --bbox 116 39 117 40 --water-level 5.0 --synthetic --output-dir ./out

License: MIT
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

VERSION = "1.0.0"
SKILL_NAME = "flood-inundation-modeling"

# ---- 复用共享核心库（本地 vendored，随脚本目录一起分发）----
try:
    from _geoskill_core.errors import (
        GeoSkillError, UsageError, ValidationError, ProcessError, to_exit_code,
    )
    from _geoskill_core.manifest import OutputManifest, OutputFile
except ImportError:  # pragma: no cover - fallback minimal definitions
    class GeoSkillError(Exception):
        def __init__(self, message: str, code: int = 7, kind: str = "EGeo", **kw):
            super().__init__(message)
            self.message, self.code, self.kind = message, code, kind

    class UsageError(GeoSkillError):
        def __init__(self, m, **k): super().__init__(m, code=2, kind="EUsage", **k)

    class ValidationError(GeoSkillError):
        def __init__(self, m, **k): super().__init__(m, code=6, kind="EValidate", **k)

    class ProcessError(GeoSkillError):
        def __init__(self, m, **k): super().__init__(m, code=7, kind="EProcess", **k)

    def to_exit_code(exc):
        return getattr(exc, "code", 7)

    OutputManifest = None
    OutputFile = None


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------
def validate_bbox(bbox) -> None:
    """Validate a [W, S, E, N] geographic bbox.

    Raises ValidationError (exit 6) on:
      - non-finite values
      - longitude/latitude out of range
      - W >= E (no antimeridian wrap-around)
      - S >= N
      - zero-area bbox
    """
    w, s, e, n = bbox
    if not all(np.isfinite([w, s, e, n])):
        raise ValidationError(
            f"bbox contains non-finite values: W={w} S={s} E={e} N={n}",
            bbox=list(bbox),
        )
    if abs(w) > 180.0 or abs(e) > 180.0:
        raise ValidationError(
            f"bbox longitude out of range: W={w} E={e} (must be in [-180, 180])",
            bbox=list(bbox),
        )
    if abs(s) > 90.0 or abs(n) > 90.0:
        raise ValidationError(
            f"bbox latitude out of range: S={s} N={n} (must be in [-90, 90])",
            bbox=list(bbox),
        )
    if w >= e:
        raise ValidationError(
            f"bbox reversed: W ({w}) must be < E ({e}). "
            f"For antimeridian-crossing bboxes, split into W..180 and -180..E.",
            bbox=list(bbox),
        )
    if s >= n:
        raise ValidationError(
            f"bbox reversed: S ({s}) must be < N ({n})", bbox=list(bbox)
        )
    if (e - w) < 1e-9 or (n - s) < 1e-9:
        raise ValidationError(
            f"bbox has zero area: W={w} S={s} E={e} N={n}", bbox=list(bbox)
        )


def read_geotiff_with_nodata(path: str):
    """Read a single-band GeoTIFF, replacing NoData with NaN.

    Returns (dem_float32, bbox_WSEN, n_valid_pixels).
    """
    data, bbox = read_geotiff(path)
    import rasterio
    with rasterio.open(path) as src:
        nodata = src.nodata
    if nodata is not None:
        data = np.where(data == nodata, np.nan, data).astype(np.float32)
    n_valid = int(np.sum(np.isfinite(data)))
    return data, bbox, n_valid


# ---------------------------------------------------------------------------
# 核心算法
# ---------------------------------------------------------------------------
def static_inundation(dem: np.ndarray, water_level: float) -> np.ndarray:
    """静态 Bathtub 淹没：凡高程低于水位的像元均被淹没。

    返回布尔掩膜 (H, W)，True = 淹没。
    """
    return dem < float(water_level)


def connected_inundation(dem: np.ndarray, water_level: float) -> np.ndarray:
    """水文连通性约束的淹没：只保留与栅格边界连通的淹没区。

    用 scipy.ndimage.label 对静态淹没掩膜做 8 连通域分析，
    保留至少有一个像元落在栅格边界上的连通域，排除内部孤立洼地。
    """
    from scipy import ndimage

    inund = dem < float(water_level)
    if not inund.any():
        return inund

    # 8 连通结构元
    struct = np.ones((3, 3), dtype=bool)
    labels, n = ndimage.label(inund, structure=struct)

    h, w = inund.shape
    boundary_labels = set()
    boundary_labels.update(labels[0, :].tolist())
    boundary_labels.update(labels[-1, :].tolist())
    boundary_labels.update(labels[:, 0].tolist())
    boundary_labels.update(labels[:, -1].tolist())
    boundary_labels.discard(0)

    if not boundary_labels:
        return np.zeros_like(inund, dtype=bool)

    keep = np.isin(labels, np.array(sorted(boundary_labels), dtype=labels.dtype))
    return keep


def inundation_depth(
    dem: np.ndarray, water_level: float, mask: np.ndarray
) -> np.ndarray:
    """计算水深：淹没区内 depth = water_level − DEM（非负），区外为 0。"""
    depth = np.where(mask, float(water_level) - dem, 0.0)
    return np.clip(depth, 0.0, None).astype(np.float32)


def pixel_area_m2(bbox: List[float], height: int, width: int) -> float:
    """估算单个像元的地表面积（平方米）。

    用纬度相关的度→米换算：1° 经度 ≈ 111320·cos(lat)，1° 纬度 ≈ 110540 m。
    """
    w, s, e, n = bbox
    mid_lat = (s + n) / 2.0
    dx_m = (e - w) / max(width, 1) * 111320.0 * np.cos(np.deg2rad(mid_lat))
    dy_m = (n - s) / max(height, 1) * 110540.0
    return float(abs(dx_m * dy_m))


def flood_stats(
    mask: np.ndarray, depth: np.ndarray, pixel_area: float
) -> Dict[str, Any]:
    """统计淹没面积（m² / km²）与蓄水体积（m³）。"""
    n_pix = int(np.count_nonzero(mask))
    area_m2 = n_pix * pixel_area
    volume_m3 = float(np.sum(depth)) * pixel_area
    return {
        "inundated_pixels": n_pix,
        "pixel_area_m2": float(pixel_area),
        "area_m2": float(area_m2),
        "area_km2": float(area_m2 / 1e6),
        "volume_m3": float(volume_m3),
        "mean_depth_m": float(np.mean(depth[mask]) if n_pix > 0 else 0.0),
        "max_depth_m": float(np.max(depth) if depth.size > 0 else 0.0),
    }


def run_flood(
    dem: np.ndarray,
    water_level: float,
    method: str = "connected",
    bbox: Optional[List[float]] = None,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    """执行洪水淹没模拟主流程。

    返回 (inundation_mask_uint8, water_depth, stats_dict)。
    """
    if dem.ndim != 2:
        raise ValidationError(
            f"DEM must be 2D, got ndim={dem.ndim}", ndim=int(dem.ndim)
        )
    if not np.isfinite(dem).any():
        raise ValidationError("DEM contains no valid (finite) values")

    if method == "static":
        mask = static_inundation(dem, water_level)
    elif method == "connected":
        mask = connected_inundation(dem, water_level)
    else:
        raise UsageError(
            f"unknown method '{method}'. Choose from: static, connected",
            method=method,
        )

    depth = inundation_depth(dem, water_level, mask)

    if bbox is not None:
        pixel_area = pixel_area_m2(bbox, dem.shape[0], dem.shape[1])
    else:
        pixel_area = 1.0
    stats = flood_stats(mask, depth, pixel_area)
    stats["method"] = method
    stats["water_level"] = float(water_level)

    mask_u8 = mask.astype(np.uint8)
    return mask_u8, depth, stats


# ---------------------------------------------------------------------------
# 合成数据：含河谷洼地的 DEM（离线测试）
# ---------------------------------------------------------------------------
def generate_synthetic_dem(
    bbox: List[float],
    width: int = 128,
    height: int = 128,
    seed: int = 42,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """生成一个含河谷与孤立洼地的 DEM。

    地形：从西北向东南倾斜的基底 + 一条贯穿的低洼河谷（连通到边界）+
    一个内部孤立洼地（不连通到边界），以便对比 static / connected 两种模式。
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:height, 0:width]
    yy = yy.astype(np.float32) / max(height - 1, 1)
    xx = xx.astype(np.float32) / max(width - 1, 1)

    # 基底：10 m（东南低）到 30 m（西北高）
    base = 30.0 - 20.0 * (0.5 * xx + 0.5 * yy)

    # 河谷：沿对角线的一条低洼带，连通到边界
    river_dist = np.abs((xx - yy))  # 距对角线距离
    valley = np.where(river_dist < 0.06, -8.0 * (1.0 - river_dist / 0.06), 0.0)

    dem = base + valley

    # 内部孤立洼地：中心偏右上一个圆形凹陷，不与边界河谷连通
    cx, cy, r = 0.72, 0.30, 0.10
    dist_c = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    pit = np.where(dist_c < r, -6.0 * (1.0 - dist_c / r), 0.0)
    dem = dem + pit

    # 轻微纹理噪声
    dem = dem + rng.normal(0, 0.1, size=dem.shape).astype(np.float32)
    dem = dem.astype(np.float32)

    info = {
        "bbox": bbox,
        "width": width,
        "height": height,
        "dem_min": float(np.min(dem)),
        "dem_max": float(np.max(dem)),
        "dem_mean": float(np.mean(dem)),
    }
    return dem, info


# ---------------------------------------------------------------------------
# GeoTIFF I/O（直接用 rasterio，保证离线可用）
# ---------------------------------------------------------------------------
def write_geotiff(
    path: str,
    cube: np.ndarray,
    bbox: List[float],
    nodata: float = -9999.0,
    dtype: str = "float32",
) -> None:
    import rasterio
    from rasterio.transform import from_bounds

    if cube.ndim == 2:
        cube = cube[np.newaxis, ...]
    nb, h, w = cube.shape
    transform = from_bounds(bbox[0], bbox[1], bbox[2], bbox[3], w, h)
    profile = {
        "driver": "GTiff", "height": h, "width": w, "count": nb,
        "dtype": dtype, "crs": "EPSG:4326", "transform": transform,
        "nodata": nodata, "compress": "deflate",
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with rasterio.open(path, "w", **profile) as dst:
        for b in range(nb):
            dst.write(cube[b].astype(dtype), b + 1)


def read_geotiff(path: str) -> Tuple[np.ndarray, List[float]]:
    import rasterio
    if not os.path.exists(path):
        raise UsageError(f"input raster not found: {path}", path=path)
    with rasterio.open(path) as src:
        data = src.read(1).astype(np.float32)
        b = src.bounds
        bbox = [b.left, b.bottom, b.right, b.top]
    return data, bbox


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
def write_manifest(
    output_dir: str,
    args: argparse.Namespace,
    outputs: List[Dict[str, Any]],
    qa: Dict[str, Any],
    started_at: str,
    exit_code: int,
    bbox: List[float],
) -> Optional[str]:
    if OutputManifest is None:
        return None
    cmd = " ".join([SKILL_NAME] + sys.argv[1:])
    man = OutputManifest(
        skill=SKILL_NAME,
        skill_version=VERSION,
        command=cmd,
        started_at=started_at,
        finished_at=_utc_now(),
        exit_code=exit_code,
        inputs={
            "input": getattr(args, "input", None),
            "water_level": getattr(args, "water_level", None),
            "method": getattr(args, "method", None),
            "synthetic": bool(getattr(args, "synthetic", False)),
        },
        outputs=[OutputFile(**o) for o in outputs],
        qa=qa,
        software={"python": sys.version.split()[0], "skill": SKILL_NAME},
    )
    path = os.path.join(output_dir, "output-manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(man.to_dict(), f, ensure_ascii=False, indent=2, default=str)
    return path


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def process(args: argparse.Namespace) -> int:
    started_at = _utc_now()
    output_dir = args.output_dir
    bbox = list(args.bbox) if args.bbox else None
    if bbox is not None:
        validate_bbox(bbox)
    if args.water_level is None or not np.isfinite(args.water_level):
        raise ValidationError(
            f"--water-level must be a finite number, got {args.water_level}",
            water_level=args.water_level,
        )

    # 1) 获取 DEM
    synth_info: Optional[Dict[str, Any]] = None
    n_valid = 0
    if args.input and not args.synthetic:
        if not os.path.exists(args.input):
            raise UsageError(f"input raster not found: {args.input}", path=args.input)
        dem, file_bbox, n_valid = read_geotiff_with_nodata(args.input)
        bbox = bbox if bbox is not None else file_bbox
        validate_bbox(bbox)
        source_note = args.input
    else:
        if bbox is None:
            raise UsageError("provide --bbox (synthetic mode) or --input <raster>")
        dem, synth_info = generate_synthetic_dem(bbox)
        source_note = "synthetic"
        n_valid = int(np.sum(np.isfinite(dem)))

    if dem.size == 0:
        raise ValidationError("input DEM is empty")
    if n_valid == 0:
        raise ValidationError(
            "input DEM has no valid (non-NoData) pixels",
            shape=list(dem.shape),
        )

    # 2) 淹没模拟
    mask, depth, stats = run_flood(
        dem, water_level=args.water_level, method=args.method, bbox=bbox
    )

    # Only create output dir after all validations have passed
    os.makedirs(output_dir, exist_ok=True)

    # 3) 写出产物
    mask_tif = os.path.join(output_dir, "inundation_mask.tif")
    depth_tif = os.path.join(output_dir, "water_depth.tif")
    write_geotiff(mask_tif, mask, bbox, nodata=255, dtype="uint8")
    write_geotiff(depth_tif, depth, bbox)

    stats_path = os.path.join(output_dir, "flood_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    n_total_pixels = int(dem.shape[0] * dem.shape[1])
    qa: Dict[str, Any] = {
        "source": source_note,
        "method": args.method,
        "water_level": args.water_level,
        "dem_min": float(np.nanmin(dem)) if np.any(np.isfinite(dem)) else 0.0,
        "dem_max": float(np.nanmax(dem)) if np.any(np.isfinite(dem)) else 0.0,
        "inundated_pixels": stats["inundated_pixels"],
        "area_km2": stats["area_km2"],
        "volume_m3": stats["volume_m3"],
        "mean_depth_m": stats["mean_depth_m"],
        "n_valid_pixels": n_valid,
        "n_total_pixels": n_total_pixels,
    }
    if synth_info is not None:
        qa["synthetic_dem_mean"] = synth_info["dem_mean"]

    outputs = [
        {"path": mask_tif, "kind": "raster", "crs_epsg": 4326,
         "bbox_wgs84": bbox, "band_count": 1},
        {"path": depth_tif, "kind": "raster", "crs_epsg": 4326,
         "bbox_wgs84": bbox, "band_count": 1},
        {"path": stats_path, "kind": "json"},
    ]

    man_path = write_manifest(output_dir, args, outputs, qa, started_at, 0, bbox)

    if not args.quiet:
        print(f"[{SKILL_NAME}] source: {source_note}")
        print(f"[{SKILL_NAME}] method: {args.method}  water_level: {args.water_level}")
        print(f"[{SKILL_NAME}] inundated pixels: {stats['inundated_pixels']}")
        print(f"[{SKILL_NAME}] area: {stats['area_km2']:.4f} km²  volume: {stats['volume_m3']:.1f} m³")
        print(f"[{SKILL_NAME}] mask:  {mask_tif}")
        print(f"[{SKILL_NAME}] depth: {depth_tif}")
        if man_path:
            print(f"[{SKILL_NAME}] manifest: {man_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=SKILL_NAME,
        description="Bathtub static flood inundation modeling from DEM with connectivity constraint.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"),
                   help="geographic extent [minLon minLat maxLon maxLat]")
    p.add_argument("--input", help="input DEM GeoTIFF (EPSG:4326)")
    p.add_argument("--water-level", type=float, default=5.0,
                   help="flood water level in DEM height units (default: 5.0)")
    p.add_argument("--method", default="connected", choices=["static", "connected"],
                   help="inundation method (default: connected)")
    p.add_argument("--synthetic", action="store_true",
                   help="generate a physics-consistent synthetic DEM (offline)")
    p.add_argument("--output-dir", default="./output", help="output directory")
    p.add_argument("--quiet", action="store_true", help="suppress console output")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return process(args)
    except GeoSkillError as exc:
        print(f"[{SKILL_NAME}] ERROR [{exc.kind}] {exc.message}", file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"[{SKILL_NAME}] ERROR {exc}", file=sys.stderr)
        return to_exit_code(exc)


if __name__ == "__main__":
    sys.exit(main())
