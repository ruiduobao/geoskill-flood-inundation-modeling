---
name: geoskill-flood-inundation-modeling
description: '基于 DEM 的 Bathtub 静态洪水淹没模拟，支持水文连通性约束（flood-fill）。Static bathtub flood inundation modeling from DEM with optional hydrological connectivity constraint. 输出淹没范围/水深 GeoTIFF + 面积体积统计 JSON。'
---

# 洪水淹没模拟 | Flood Inundation Modeling

Bathtub (static) flood inundation modeling from a digital elevation model (DEM). Given a water level (`--water-level`), every pixel whose elevation is below the water level is considered potentially inundated, with water depth equal to the difference between the water level and the ground elevation. Suitable for rapid floodplain screening, flood storage/detention area assessment, and estimation of storm-surge and dam-break inundation extents.

Two modes are implemented:

- **static**: purely static inundation — every pixel with `DEM < water_level` is counted as flooded (including interior isolated depressions).
- **connected**: hydrological connectivity constraint. Uses `scipy.ndimage.label` for 8-connectivity component analysis and keeps only the inundated regions connected to the raster boundary, excluding interior isolated depressions — in real physical processes these depressions would not be filled by external floodwater. This mode is closer to the actual inundation extent.

Outputs an inundation extent raster (0/1), a water depth raster (m), and a statistics JSON (inundated area in m²/km², stored water volume in m³, mean/max water depth, etc.). The `--synthetic` mode generates a simulated DEM containing valley depressions and isolated depressions, so the workflow and the difference between the two modes can be validated offline without network access or real data.

## Dependencies / 依赖

```bash
pip install numpy rasterio scipy
```

## Usage / 使用方法

### Basic usage (synthetic data, offline)

```bash
python geoskill-flood-inundation-modeling.py --bbox 116.0 39.0 117.0 40.0 --water-level 15.0 --output-dir ./output
```

### Example 1: connectivity-constrained inundation (synthetic data)

```bash
python geoskill-flood-inundation-modeling.py \
    --bbox 116.0 39.0 117.0 40.0 \
    --water-level 18.0 \
    --method connected \
    --synthetic \
    --output-dir ./flood_connected
```

### Example 2: static inundation (including isolated depressions)

```bash
python geoskill-flood-inundation-modeling.py \
    --bbox 116.0 39.0 117.0 40.0 \
    --water-level 18.0 \
    --method static \
    --synthetic \
    --output-dir ./flood_static
```

### Example 3: real DEM inundation

```bash
python geoskill-flood-inundation-modeling.py \
    --input dem.tif \
    --water-level 5.0 \
    --method connected \
    --output-dir ./real_flood
```

### Example 4: comparison of different water-level scenarios

```bash
python geoskill-flood-inundation-modeling.py --bbox 116 39 117 40 --water-level 10.0 --method connected --output-dir ./wl10 --quiet
python geoskill-flood-inundation-modeling.py --bbox 116 39 117 40 --water-level 20.0 --method connected --output-dir ./wl20 --quiet
```

## Output / 输出

| File | Format | Description |
|---|---|---|
| `inundation_mask.tif` | GeoTIFF (uint8) | Inundation extent, 1=flooded 0=not flooded, EPSG:4326 |
| `water_depth.tif` | GeoTIFF (float32) | Water depth (m); flooded area = water level − DEM, non-negative |
| `flood_stats.json` | JSON | Number of inundated pixels, area (m²/km²), volume (m³), mean/max water depth |
| `output-manifest.json` | JSON | Run manifest (inputs/outputs/QA/software versions) |

## Data Source / 数据源 / Source

- **DEM**: local input GeoTIFF (EPSG:4326), which may come from SRTM / ASTER GDEM / Copernicus DEM
- **Synthetic mode**: locally generated simulated DEM with valley depressions and isolated depressions; no external data source

## Privacy / 隐私声明 / Privacy

- Fully offline by default; no network requests are made
- `--synthetic` mode reads no external data
- All computation is performed locally; user data is never uploaded

## License / License

MIT

---

> 中文完整版：需要时再读 [references/SKILL.zh-CN.md](references/SKILL.zh-CN.md)，不要默认全量加载。
