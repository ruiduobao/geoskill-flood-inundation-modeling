# 洪水淹没模拟 | Flood Inundation Modeling

基于数字高程模型（DEM）的 Bathtub（浴缸）静态洪水淹没模拟。给定一个水位
（`--water-level`），所有高程低于该水位的像元被视为潜在淹没区，水深为水位
与地面高程之差。适用于洪泛区快速筛查、蓄滞洪区评估、风暴潮/溃坝淹没范围
估算等场景。

实现两种模式：

- **static**：纯静态淹没，凡 `DEM < water_level` 的像元均计为淹没（含内部孤立洼地）。
- **connected**：水文连通性约束。用 `scipy.ndimage.label` 做 8 连通域分析，
  只保留至少与栅格边界连通的淹没区，排除内部孤立洼地——真实物理过程中这些
  洼地不会被外部洪水填充。该模式更贴近实际淹没范围。

输出淹没范围栅格（0/1）、水深栅格（m），以及淹没面积（m²/km²）、蓄水体积
（m³）、平均/最大水深等统计 JSON。支持 `--synthetic` 模式生成含河谷洼地与
孤立洼地的模拟 DEM，无需网络和真实数据即可验证流程并对比两种模式差异。

## 依赖

```bash
pip install numpy rasterio scipy
```

## 使用方法

### 基本用法（合成数据，离线）

```bash
python geoskill-flood-inundation-modeling.py --bbox 116.0 39.0 117.0 40.0 --water-level 15.0 --output-dir ./output
```

### 示例 1：连通性约束淹没（合成数据）

```bash
python geoskill-flood-inundation-modeling.py \
    --bbox 116.0 39.0 117.0 40.0 \
    --water-level 18.0 \
    --method connected \
    --synthetic \
    --output-dir ./flood_connected
```

### 示例 2：静态淹没（含孤立洼地）

```bash
python geoskill-flood-inundation-modeling.py \
    --bbox 116.0 39.0 117.0 40.0 \
    --water-level 18.0 \
    --method static \
    --synthetic \
    --output-dir ./flood_static
```

### 示例 3：真实 DEM 淹没

```bash
python geoskill-flood-inundation-modeling.py \
    --input dem.tif \
    --water-level 5.0 \
    --method connected \
    --output-dir ./real_flood
```

### 示例 4：不同水位情景对比

```bash
python geoskill-flood-inundation-modeling.py --bbox 116 39 117 40 --water-level 10.0 --method connected --output-dir ./wl10 --quiet
python geoskill-flood-inundation-modeling.py --bbox 116 39 117 40 --water-level 20.0 --method connected --output-dir ./wl20 --quiet
```

## 输出

| 文件 | 格式 | 说明 |
|---|---|---|
| `inundation_mask.tif` | GeoTIFF (uint8) | 淹没范围，1=淹没 0=未淹没，EPSG:4326 |
| `water_depth.tif` | GeoTIFF (float32) | 水深（m），淹没区 = 水位−DEM，非负 |
| `flood_stats.json` | JSON | 淹没像元数、面积（m²/km²）、体积（m³）、平均/最大水深 |
| `output-manifest.json` | JSON | 运行清单（输入/输出/QA/软件版本） |

## 数据源 / Source

- **DEM**：本地输入 GeoTIFF（EPSG:4326），可来自 SRTM / ASTER GDEM / Copernicus DEM
- **合成模式**：本地生成含河谷洼地与孤立洼地的模拟 DEM，无外部数据源

## 隐私声明 / Privacy

- 默认完全离线运行，不发起任何网络请求
- `--synthetic` 模式不读取任何外部数据
- 所有计算在本地完成，不上传用户数据

## License

MIT
