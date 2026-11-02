# Flood Inundation Modeling (geoskill-flood-inundation-modeling)

> DEM-based static bathtub flood inundation modeling with optional hydrological connectivity constraint (flood-fill). Outputs inundation extent/water depth GeoTIFFs plus area-volume statistics JSON.

---

## 1. Overview

Static bathtub flood inundation modeling based on a digital elevation model (DEM). Given a water level (`--water-level`), all pixels whose elevation is below this level are treated as potentially inundated, and water depth equals the difference between the water level and the ground elevation. Suitable for rapid screening of floodplains, evaluation of flood detention/retention areas, and estimation of storm surge or dam-break inundation extents. Two modes are implemented: - **static**: purely static inundation; every pixel with `DEM < water_level` counts as inundated (including internally isolated depressions). - **connected**: hydrological connectivity constraint. Uses `scipy.ndimage.label` for 8-connectivity component analysis and keeps only inundated areas connected to at least one raster boundary, excluding internally isolated depressions — in real physical processes these depressions would not be filled by external floodwater. This mode is closer to the actual inundation extent. Outputs an inundation extent raster (0/1), a water depth raster (m), and statistics JSON such as inundated area (m²/km²), storage volume (m³), and mean/max water depth. The `--synthetic` mode generates a simulated DEM containing valley depressions and isolated depressions, allowing the workflow to be validated and the two modes to be compared offline without network access or real data.

## 3. Quick Start

```bash
pip install -r requirements.txt
python geoskill-flood-inundation-modeling.py --bbox 116 39 117 40 --synthetic --output-dir ./out
```

## 4. CLI Parameters

Run `python <skill>.py --help` for the full list. Common parameters:

| Parameter | Type | Description |
|---|---|---|
| `--bbox` | `float[4]` | WGS84 bounding box `min_lon min_lat max_lon max_lat` |
| `--input` | `path` | Local input file (GeoJSON/GeoTIFF/etc.) |
| `--output-dir` | `path` | Output directory (default `./output`) |
| `--synthetic` | `flag` | Use synthetic data instead of real input |
| `--quiet` | `flag` | Suppress non-essential stdout |

## 5. Input / Output

| File | Format | Description |
|---|---|---|
| `inundation_mask.tif` | GeoTIFF (uint8) | Inundation extent, 1=inundated 0=not inundated, EPSG:4326 |
| `water_depth.tif` | GeoTIFF (float32) | Water depth (m), inundated area = water level − DEM, non-negative |
| `flood_stats.json` | JSON | Inundated pixel count, area (m²/km²), volume (m³), mean/max water depth |
| `output-manifest.json` | JSON | Run manifest (inputs/outputs/QA/software versions) |

## 6. Technical Principle

(see SKILL.md for details)

## 8. License

MIT License. See [`LICENSE`](./LICENSE) for full text.

---

> 中文完整版：[references/SKILL.zh-CN.md](references/SKILL.zh-CN.md)
