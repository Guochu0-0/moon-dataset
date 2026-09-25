# 使用建议

## 输入表示

光学与 SAR 各变成一个单通道 float32 的 z 值图，常数只取自训练集，三个划分共用：

| | SAR | 光学 |
|---|---|---|
| 量 | 总功率 S1 = b1 + b2（见[成像特征](imaging.md#stokes-参数)） | 灰度 |
| 变换 | 10·log₁₀(S1)，先夹到 −25 dB 以上 | — |
| 标准化 | z = (S1_dB + 10.976) / 2.711 | z = (灰度 − 73.786) / 26.533 |
| z 的范围（三个划分） | −5.17 – 8.15 | −2.74 – 6.83 |

- −25 dB 是 Mini-RF Zoom 模式的噪声等效后向散射系数（[仪器参数](imaging.md#仪器参数)）。低于它的只有近零与非正值，来自重采样过冲，占训练集像素的 2.2e-7。
- 上限不截断。z > 4 的像素占训练集的 1.6e-3，出现在 91% 的训练 patch 里，是坑壁、石块等正对雷达的亮结构。
- 交叉功率（波段 3、4）不进单通道表示。
- 光学的阴影（灰度 1）不做特殊处理。

## 代码

`moondata.preprocess` 里的两个函数，纯 numpy：

```python
from osgeo import gdal
from moondata.preprocess import optical_input, sar_input

sar = sar_input(gdal.Open("SAR/patch_0.tif").ReadAsArray())              # (4, 512, 512) → (512, 512)
optical = optical_input(gdal.Open("Optical/patch_0.tif").ReadAsArray())  # uint8 → (512, 512)
```

| 函数 | 输入 | 输出 |
|---|---|---|
| `sar_input(bands)` | `(4, H, W)`，4 个原始波段 | `(H, W)` float32 |
| `optical_input(optical)` | `(H, W)` uint8 | `(H, W)` float32 |

常数是模块常量：`SAR_FLOOR_DB`、`SAR_MEAN_DB`、`SAR_STD_DB`、`OPTICAL_MEAN`、`OPTICAL_STD`。

用三通道的预训练权重时，把单通道复制成 3 份：`np.repeat(z[None], 3, axis=0)`。

## 已知的亮度差异

全局标准化保留下面这些差异。

| 差异 | 数值 |
|---|---|
| SAR 条带间的整体亮度 | ROI 的 S1 dB 均值从 −13.2 到 −9.1 dB，ROI 间标准差 1.0 dB，与 ROI 内的 1.1 dB 相当 |
| SAR 划分间 | 验证集整体比训练集亮约 0.5 dB |
| 光学 ROI 间 | 灰度的 ROI 间标准差 20 个灰度级，ROI 内 9 个；9 个 ROI 暗且对比度极低，四分位距只有 3–6 个灰度级 |
| 光学阴影 | 只在训练集：灰度 1 占训练集像素的 0.36%；约 69 个 patch 超过 10%，约 17 个超过 50%（最多 97%），集中在 ROI_016 与 ROI_027 |
