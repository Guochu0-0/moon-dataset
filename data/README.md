# `data/`

本目录是不可再生的小文件，按字节原样存储。

| 路径 | 内容 | 来源 | 规模 |
|---|---|---|---|
| `tie-points/ROI_<nnn>.pts` | 控制点：人工在重叠区影像上标的光学–SAR 同名点，`02_patches.py` 读它解全局仿射 | ENVI Image-to-Image Tie Points，逐 ROI 人工标注（ROI_073 为重标的一代） | 67 个文件 |
| `ground-truth/{Val,Test}/ROI_<nnn>/patch_<n>.txt` | 评测真值点：patch 内的光学–SAR 同名点，配准评测的真值 | ArcGIS 地理配准链接表导出，逐 patch 人工标注 | 1605 个文件 |
| `metadata/minirf_metadata.csv` | Mini-RF 逐 ROI 元数据：产品 ID、成像时刻、入射角、视向、条带尺寸等 | 各条带的 PDS 标签 | 67 行 |

两种点文件的格式与坐标符号约定见文档站的「数据说明」（双击 [`_site/index.html`](../_site/index.html)）。
