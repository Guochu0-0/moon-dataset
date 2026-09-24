# 组织

## 目录

数据盘上原始数据与成品的目录：

```
<数据根>/
├── raw/                                    原始数据
│   └── ROI_<n>/
│       ├── ce2/        CE2_GRAS_DOM_07m_<分幅>_A.tif（.tfw、.prj）    CE-2 DOM 分幅
│       ├── minirf/     lsz_<…>_v1.tif                                  Mini-RF 条带
│       └── cropped/ce2/
│                       opt.tif、sar.tif                                 重叠区影像
└── Processed_Data/                         成品
    ├── Train/
    │   └── ROI_<nnn>/
    │       ├── Optical/   patch_<n>.tif
    │       └── SAR/       patch_<n>.tif
    ├── Val/
    │   └── ROI_<nnn>/
    │       ├── Optical/   patch_<n>.tif
    │       ├── SAR/       patch_<n>.tif
    │       └── Label/     patch_<n>.txt、patch_<n>.prj
    └── Test/              同 Val
```

- `raw/` 下有 73 个 ROI 目录，数据集用到其中 67 个。ROI 目录里另有 LRO NAC 等其他数据，不属于本数据集。
- 划分按 ROI：同一个 ROI 的 patch 全在同一个划分里。

## 文件

| 文件 | 内容 | 数据类型 | 尺寸与波段 | nodata | 值域 |
|---|---|---|---|---|---|
| `Optical/patch_<n>.tif` | CE-2 光学 patch | uint8 | 512 × 512，1 个波段 | 0 | 1–255 |
| `SAR/patch_<n>.tif` | Mini-RF SAR patch，波段见[成像特征](imaging.md#波段) | float32 | 512 × 512，4 个波段 | 0 | 波段 1：−0.014–9.56<br>波段 2：−0.022–10.01<br>波段 3：−3.13–3.02<br>波段 4：−3.23–2.74 |
| `Label/patch_<n>.txt` | 评测真值点 | 文本 | 每行一对点，4 列 | — | — |
| `Label/patch_<n>.prj` | ArcGIS 随链接表写出的文件 | 文本 | — | — | — |

- patch 是 GeoTIFF，按条带存储，Deflate 压缩，像元 7.5 m，带地理参考。光学 patch 共 1.27 GB，SAR patch 共 38.5 GB。
- 值域是全部 patch 上有效像素的最小、最大值。

命名规则：

- `Processed_Data/` 下的 ROI 目录名补零到三位（`ROI_006`）；`raw/` 下不补零（`ROI_6`）。
- `patch_<n>` 在每个 ROI 内从 0 起编号，不补零。
- 同一个 ROI 里，同编号的光学、SAR、标签文件是一对。

## 标签文件

评测真值点在 ArcGIS 中逐 patch 标注，文件为地理配准链接表的导出格式：制表符分隔的 4 列（光学 x、y，SAR x、y），单位为 patch 内像素。ArcGIS 对无地理参考的影像以左上角为原点、y 轴向上，因此 y 为负值，取绝对值即为行号。同名 `.prj` 为 ArcGIS 随链接表写出的文件，不含有效坐标系。
