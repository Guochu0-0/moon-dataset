# 数据来源

## 官方文档

| 文档 | 版本 | 内容 |
|---|---|---|
| [Mini-RF 数据产品 SIS](https://pds-geosciences.wustl.edu/lro/lro-l-mrflro-4-cdr-v1/lromrf_0001/document/dp_sis/mrflro_dp_sis.pdf) | MRF-4009，2010-02-25 | 仪器参数（表 1）、Stokes 参数（§4.3.2.2）、文件命名（§4.7.1.1、表 16） |
| Mini-RF 产品标签（`.LBL`） | `DATA_SET_ID = LRO-L-MRFLRO-5-CDR-MAP-V1.0` | 波段、入射角、视向、投影、特殊值 |
| [Mini-RF CDR 数据集说明](https://pds-geosciences.wustl.edu/lro/lro-l-mrflro-4-cdr-v1/lromrf_0001/catalog/mrflro_4_cdr_v1_0_ds.cat) | `LRO-L-MRFLRO-4-CDR-V1.0`，2011-06-15 | 数据集层面的说明 |
| [嫦娥数据发布与信息服务系统](https://moon.bao.ac.cn/) | — | CE-2 7 m DOM 下载入口（证书已过期） |

本数据集的产品标签属于 `-5-CDR-MAP`（地图投影后的 CDR），数据集说明属于 `-4-CDR`，两者的数据集 ID 不同。

## Mini-RF SAR

### 产品 ID

产品 ID 同时是文件名。按 SIS §4.7.1.1 与表 16 解码，以 `LSZ_02319_2CD_EKU_23S131_V1` 为例：

| 段 | 含义 | 本例 |
|---|---|---|
| `L` | 平台 | LRO |
| `S` | 频段 | S 波段 |
| `Z` | 雷达模式 | Zoom |
| `02319` | 轨道号 | 2319 |
| `2` | 处理级别 | Level 2 |
| `CD` | 文件类型 | Calibrated Data Record |
| `E` | 投影 | Equirectangular |
| `K` | 分辨率档位 | 1024 ppd |
| `U` | 数值类型 | Unnormalized float |
| `23` `S` | 中心纬度 | 23°S |
| `131` | 中心经度（东经 0–359°） | 131°E |
| `V1` | 产品版本 | 1 |

- 全部 67 个条带的档位字母为 `K`（1024 ppd），产品标签的 `MAP_RESOLUTION` 为 4096 ppd。以标签为准。
- 产品 ID 不含成像时间。成像时间见 GeoTIFF 元数据的 `START_TIME` 或元数据表的「成像时刻UTC」列。

### 波段

混合极化：发射圆极化，相干接收 H、V 两路线极化。4 个 float32 波段，按波段顺序存放（SIS §4.3.2.2.1）。

| 波段 | `BAND_NAME` | 物理量 |
|---|---|---|
| 1 | H RECEIVE INTENSITY | ⟨\|E<sub>H</sub>\|²⟩，功率 |
| 2 | V RECEIVE INTENSITY | ⟨\|E<sub>V</sub>\|²⟩，功率 |
| 3 | CROSS POWER INTENSITY (REAL) | Re⟨E<sub>H</sub> E<sub>V</sub>\*⟩ |
| 4 | CROSS POWER INTENSITY (IMAGINARY) | Im⟨E<sub>H</sub> E<sub>V</sub>\*⟩ |

波段 3、4 可为负值。

### Stokes 参数

SIS §4.3.2.2.1–2：

```python
S1 = b1 + b2
S2 = b1 - b2
S3 = 2 * b3
S4 = -2 * b4

SC  = 0.5 * (S1 - S4)                        # 同向圆极化
OC  = 0.5 * (S1 + S4)                        # 反向圆极化
CPR = SC / OC                                # 圆极化比
m   = np.sqrt(S2**2 + S3**2 + S4**2) / S1    # 极化度
```

全月平均 CPR 约 0.3，m 约 0.6（SIS §4.3.2.2.2.3）。

### 仪器参数

SIS 表 1，S 波段：

| 参数 | Zoom | Baseline |
|---|---|---|
| 频率 | 2.38 GHz（12.6 cm） | 同左 |
| 斜距分辨率 | 23 m | 115 m |
| 地距 / 方位分辨率 | 15 × 30（原表无单位） | 150 m |
| 视数 | 8 | 16 |
| 线性调频带宽 | 8 MHz | 1.6 MHz |
| NESZ | −25 dB | −30 dB |
| 条带长度 | < 400 km | 同左 |

### 格式与投影

| 项 | 值 | 出处 |
|---|---|---|
| 官方格式 | PDS3 `IMG` + `LBL`，`PC_REAL` | 产品标签 |
| 空值 | `CORE_NULL` ≈ −3.4028 × 10³⁸ | 产品标签 |
| 投影 | 等距圆柱，`CENTER_LONGITUDE = 180.0` | 产品标签 |
| 月球半径 | 1737.4 km（球体） | 产品标签 |
| 采样间隔 | 4096 ppd，`MAP_SCALE` = 7.4032 m | 产品标签 |
| 数据盘格式 | GeoTIFF，标签字段写入 GeoTIFF 元数据 | 数据盘 `raw/ROI_<n>/minirf/` |

[ROI_054](rois/ROI_054.md) 的 `minirf/` 目录下有两个 SAR 文件。

## CE-2 光学

### 投影参数有误的分幅

以下 5 幅的 `lat_ts` 写成了相邻纬度带的值。读取时按幅名纠正，源文件未改。

| 分幅 | 写成 | 应为 | 受影响的 ROI |
|---|---|---|---|
| E215、E218、E219 | 21° | 35° | [ROI_073](rois/ROI_073.md)、[ROI_057](rois/ROI_057.md)、[ROI_058](rois/ROI_058.md) |
| I219、I236 | −35° | −21° | [ROI_070](rois/ROI_070.md)、[ROI_065](rois/ROI_065.md) |
