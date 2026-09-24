# 调研：SAR 强度数据进入深度网络前的表示与归一化

issue #35（地图 #34）。调研日期 2026-09-25。本文只列做法、出处与适用前提，并给出候选方案，不替作者做决定。

## 摘要

- 主流 SAR 深度学习数据集与代码库对**强度/功率**的共同做法是：取 **dB（10·log10）**，再用**固定的全局常数**截断并线性缩放（SEN12MS：[−25, 0] dB；SSL4EO-S12：均值 ± 2σ 映射到 uint8；torchgeo：逐通道均值/标准差）。都**不做去相干斑**，把去斑留给使用者。
- 光学–SAR 配准数据集多把 SAR 直接做成**单通道 8 位灰度图**，并逐图拉伸对比度（OSdataset：线性振幅 + MATLAB `imadjust`，即饱和上下各 1%；SEN1-2：dB 后截断到 ±2.5σ）。传统方法（RIFT、HOPC、CFOG）的公开代码都以 8 位灰度 PNG/TIF 为输入。
- 这些数据集的 SAR 都是单极化或双线极化（VV/VH）功率，**没有**像 Mini-RF 这样含负值的交叉功率波段。含负值的波段没有现成惯例，要靠物理量变换自己处理（见 §3.3）。
- 本数据集抽样统计：b1、b2、S1、SC、OC 在 600 个 patch 里几乎全为正（非正值 ≤ 1e-6，疑为三次卷积重采样的过冲）；负值只出现在 b3、b4。S1 的 dB 值大致落在 −18 到 0 dB；单个 patch 内 S1 的 p99/p1 中位约 10 倍（约 10 dB）。
- 预训练权重：timm 把 RGB 首层卷积按通道求和得到单通道卷积；RIPE 在灰度输入时把单通道复制成 3 通道，而把 `nchannels` 改成非 3 时首层卷积会被**随机初始化**。

## 1. 本数据集的数值事实

脚本 [`research/sar_value_stats.py`](../sar_value_stats.py)，各划分随机抽 200 个 SAR patch（种子 0），读 `G:/Lunar_Optical_SAR_Registration_Dataset/Processed_Data`。运行：

```
conda run -n moon-dataset python research/sar_value_stats.py G:/Lunar_Optical_SAR_Registration_Dataset/Processed_Data 200
```

| 量 | 非正值比例（Train / Val / Test） | 线性值 p1 – p50 – p99（Train） |
|---|---|---|
| b1（H 功率） | 0 / 0.0001% / 0 | 0.0079 – 0.034 – 0.26 |
| b2（V 功率） | 0 / 0 / 0 | 0.0097 – 0.039 – 0.24 |
| b3（Re 交叉功率） | 38% / 36% / 37% | −0.029 – 0.0022 – 0.058 |
| b4（Im 交叉功率） | 91% / 91% / 90% | −0.093 – −0.012 – 0.014 |
| S1 = b1 + b2 | 0 / 0 / 0 | 0.021 – 0.074 – 0.47 |
| SC | 0 / 0 / 0 | 0.0060 – 0.024 – 0.19 |
| OC | 0 / 0 / 0 | 0.011 – 0.049 – 0.31 |

- S1（dB）分位（Train）：p0.1 −18.5，p1 −16.8，p2 −16.2，p50 −11.3，p98 −4.3，p99 −3.2，p99.9 +0.1。Val、Test 与之相差不到 1 dB。
- 右尾很重：S1 的 p99.9 约为 p99 的 2 倍（线性）。线性域 min–max 会被少量亮点压扁对比度。
- 单个 patch 内 S1 的 p99/p1（线性）：中位约 10，5%–95% 分位约 5–29。
- b4 约九成为负，说明 S4 = −2·b4 多为正，即 OC > SC，与全月 CPR ≈ 0.3 一致（`docs/pages/data/imaging.md`）。
- Mini-RF Zoom 为 8 视（`docs/pages/data/imaging.md`）。若按充分发育相干斑、8 视强度服从 Gamma 分布估算，强度的变差系数为 1/√8 ≈ 0.35，取 dB 后标准差约 (10/ln10)·√ψ₁(8) ≈ 1.6 dB。与 patch 内约 10 dB 的动态范围相比，相干斑不可忽略。（估算，未对数据做检验。）
- 仓库现有做法：文档站素材把 SAR 画成 S1 的 dB，再按 2%–98% 分位拉伸（[`src/moondata/assets.py`](../../src/moondata/assets.py) `STRETCH_PERCENTILES = (2, 98)`）。

## 2. 做法清单

每条：做法 — 出处 — 适用前提。

### 2.1 选哪个通道或派生量

| 做法 | 出处 | 适用前提 |
|---|---|---|
| 只用一路共极化功率（VV） | SEN1-2：“restricted ourselves to vertically polarized (VV) data”（[arXiv:1807.01569](https://arxiv.org/abs/1807.01569)） | 线极化单通道任务；Mini-RF 没有 VV/VH，只有 H、V 两路接收功率，对应不上 |
| 双极化功率各作一个通道（VV、VH） | SEN12MS（[arXiv:1906.07789](https://arxiv.org/abs/1906.07789)）；SSL4EO-S12（`ALL_BANDS_S1_GRD = ['VV','VH']`，[代码](https://github.com/zhu-xlab/SSL4EO-S12/blob/main/src/benchmark/pretrain_ssl/datasets/SSL4EO/ssl4eo_dataset.py)）；torchgeo 的 Sentinel-1 权重均为 `in_chans: 2`（[resnet.py](https://github.com/microsoft/torchgeo/blob/main/torchgeo/models/resnet.py)） | 各通道都是非负功率 |
| 单极化振幅单通道 | OSdataset（GF-3，“The SAR amplitude is presented in linear scale”，[README](https://github.com/xym2009/OSdataset)）；QXS-SAROPT（“spotlight mode images with single polarization”，[arXiv:2103.08259](https://arxiv.org/abs/2103.08259)） | 单极化 |
| 混合极化用 Stokes 派生量：总功率 S1、CPR、极化度 m、m-chi 分解 | Mini-RF SIS §4.3.2.2（本仓库 `docs/pages/data/imaging.md`）；m-chi：Raney et al. 2012, JGR Planets 117(E12)（[doi:10.1029/2011JE003986](https://doi.org/10.1029/2011JE003986)） | 混合极化（发圆收线）数据；m-chi 给出三个非负分量，天然可作 3 通道（RGB）显示 |
| 月球 SAR 配准的单通道做法 | 公开文献多用 S1 或其等价量；Mini-RF 基于 DEM 的配准（[Remote Sens. 17(4):613](https://doi.org/10.3390/rs17040613)）用 NCC 与“background removal”，但我读到的文本未说明所用派生量 | —（未核实，见 §4） |

说明：在本仓库 **S1 = b1 + b2** 是唯一与极化基无关、且严格为正的总功率，对应 Sentinel-1 惯例里“一路功率”的角色最自然。SC、OC 也为正且物理意义明确（SC + OC = S1）。

### 2.2 取 dB 或其他压缩

| 做法 | 出处 | 适用前提 |
|---|---|---|
| 功率取 dB（σ⁰ dB）作为网络输入 | SEN1-2、SEN12MS 都以 dB 发布（“σ0 backscatter coefficient in dB scale”）；SEN12MS 代码 `np.clip(s1, -25, 0)` 直接作用在 dB 上（[dataset.py](https://github.com/schmitt-muc/SEN12MS/blob/master/classification/dataset.py)）；SSL4EO-S12 与 torchgeo 的 S1 均值约 −12.5 / −20.2，即 dB 域统计 | 输入为非负功率 |
| 自然对数 + 固定全局 min/max 归一到 [0,1] | deepdespeckling（MERLIN/SAR2SAR）：`(np.log(np.clip(image, 0, image.max())+1e-6)-m)/(M-m)`，`M`、`m` 为“Global maximum and minimum values obtained empirically”（[utils.py](https://github.com/hi-paris/deepdespeckling/blob/main/deepdespeckling/utils/utils.py)，[constants.py](https://github.com/hi-paris/deepdespeckling/blob/main/deepdespeckling/utils/constants.py)） | 振幅/强度非负；对数把乘性相干斑变成加性（Argenti et al. 2013, [doi:10.1109/MGRS.2013.2277512](https://doi.org/10.1109/MGRS.2013.2277512)） |
| 线性振幅，不取对数 | OSdataset（见上）；SAR-SIFT 的 ROEWA 比值梯度是为线性强度上的乘性相干斑设计的（Dellinger et al. 2015, TGRS 53(1):453–466, [doi:10.1109/TGRS.2014.2323552](https://doi.org/10.1109/TGRS.2014.2323552)） | 下游方法本身按乘性噪声建模，或数据集只为可视化 |
| 不统一换算：线性、dB、振幅不混用 | torchgeo `Sentinel1` 文档：“power, decibel, and amplitude scale data should not be mixed, and TorchGeo does not attempt to convert all data to a common scale”（[sentinel.py](https://github.com/microsoft/torchgeo/blob/main/torchgeo/datasets/sentinel.py)） | 任何多来源训练 |

### 2.3 零值、负值、NaN

| 做法 | 出处 | 适用前提 |
|---|---|---|
| NaN 置 0，再在 dB 域截断 | SEN12MS `np.nan_to_num(s1)` 后 `np.clip(s1, -25, 0)` | 数据已在 dB 域，0 dB 恰好在截断区间内 |
| 对数前把负值截到 0 并加小常数 ε | deepdespeckling：`np.clip(image, 0, ...)+1e-6` | 非负量里的少量数值噪声 |
| 非正值与填充值记为无效 | 本仓库 `assets.py`：非正值与 Mini-RF 填充值（−3.4e38）记为 NaN | 可视化 |
| 带符号量不取对数：用除以总功率的归一化 Stokes 参数 s_i = S_i / S1 ∈ [−1, 1] | 由 Stokes 定义推出（|S2|、|S3|、|S4| ≤ S1，极化度 m ≤ 1，见 SIS §4.3.2.2 与 Raney et al. 2012） | 需要把 b3、b4（交叉功率实部/虚部）也送进网络时；{S1, S2/S1, S3/S1, S4/S1} 与 {b1..b4} 一一对应，不丢信息 |

未找到任何主流数据集或代码库直接处理“含负值的交叉功率”波段的惯例；上表最后一行是按物理定义的推论，不是引用来的惯例。

### 2.4 截断与缩放

| 做法 | 出处 | 适用前提 |
|---|---|---|
| 固定 dB 区间 [−25, 0] 截断，线性映射 | SEN12MS 代码（`s1 /= 25; s1 += 1`，映到 [0,1]） | Sentinel-1 C 波段陆地的常见范围；Mini-RF 的数值是另一套定标，区间需按本数据集重定（本数据集 S1 约 −18 到 0 dB） |
| 按 ±2.5σ 截断并缩放到 [0,1] | SEN1-2：“cut gray values to the ±2.5σ range, scaling them to the interval [0;1]”（论文未写明 σ 取自单景还是全局） | 近似对称分布（dB 域） |
| 按全局均值 ± 2σ 映射到 0–255 并截断，存 uint8 | SSL4EO-S12 `normalize()`：`min_value = mean - 2*std` … `np.clip(img, 0, 255).astype(np.uint8)` | 要与 uint8 光学统一存储/增强管线 |
| 逐通道 z-score（全局均值/标准差） | torchgeo `_ssl4eo_s12_transforms_s1`：`T.Normalize(mean=[-12.59, -20.26], std=[5.26, 5.91])`；SEN12MS `Normalize` 类 | 数值稳定即可的网络输入 |
| 逐图饱和上下各 1% 后线性拉伸 | OSdataset 用 MATLAB `imadjust` 默认参数；`imadjust` 文档：“saturates the bottom 1% and the top 1% of all pixel values”（[MathWorks](https://www.mathworks.com/help/images/ref/imadjust.html)） | 为了人眼/传统方法可见的对比度，放弃绝对辐射量 |
| 逐图 2%–98% 分位拉伸 | 本仓库 `assets.py`（S1 dB） | 可视化 |

### 2.5 全局还是逐图；统计量取自哪个划分

- **全局固定常数**是 SAR 深度学习数据集的主流（SEN12MS、SSL4EO-S12、torchgeo、deepdespeckling）。前提：各景定标一致，绝对后向散射有意义。
- **逐图/逐 patch 归一化**：OSdataset（`imadjust`）、SEN1-2（±2.5σ，范围未说明）。RIPE 的骨干网提供 `use_instance_norm` 选项，在网络入口做 `nn.InstanceNorm2d`（[backbone_base.py](https://github.com/fraunhoferhhi/RIPE/blob/main/ripe/models/backbones/backbone_base.py)），等效于网络内的逐图标准化；RIPE 的默认配置里为 `False`（[vgg.yaml](https://github.com/fraunhoferhhi/RIPE/blob/main/conf/backbones/vgg.yaml)）。前提：任务只依赖相对结构（配准正是如此），不依赖绝对亮度。
- **统计量只取自训练集**：scikit-learn 文档：“these transformations are only learnt from the training data … the average should be the average of the train subset, not the average of all the data”（[Common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html)）。本仓库按 ROI 划分，全局常数应只由 Train 的 ROI 算出。逐图归一化不涉及跨划分统计，无此问题。

### 2.6 是否去相干斑

- SEN1-2：“we have not carried out any speckle filtering”；SEN12MS：“we intend to leave any further pre-processing, e.g. speckle filtering, to the end user”。
- 深度去斑（MERLIN、SAR2SAR）是独立模型，输入需按其训练时的对数归一化常数准备（见 §2.2），不能直接套用到 Mini-RF 的数值范围。
- 前提：去斑是有损的（平滑纹理与边缘），与“预处理不丢信息”的立场冲突；更适合作为消融或专门给传统方法的版本。Argenti et al. 2013 是去斑方法的综述入口。

### 2.7 单通道 backbone 与 ImageNet 预训练权重

| 惯例 | 出处 | 适用前提 |
|---|---|---|
| 单通道输入时把 RGB 首层卷积权重按输入通道求和（`conv_weight.sum(dim=1, keepdim=True)`）；非 3 通道时循环复制并乘 3/C | timm `adapt_input_conv`（[_manipulate.py](https://github.com/huggingface/pytorch-image-models/blob/main/timm/models/_manipulate.py)） | 输入分布与 ImageNet 灰度相近（[0,1] 后减均值除方差）时迁移最好 |
| 灰度图复制成 3 通道喂 3 通道预训练网络；`nchannels != 3` 时首层 `nn.Conv2d` 重新随机初始化 | RIPE `BackboneBase.forward` 的 `x.repeat(1, 3, 1, 1)`；`VGG19.__init__` 的 `self.layers[0] = nn.Conv2d(num_input_channels, 64, 3, 1, 1)`（[vgg_utils.py](https://github.com/fraunhoferhhi/RIPE/blob/main/ripe/models/backbones/vgg_utils.py)）；RIPE 示例输入为 `decode_image(...)/255.0` | 用 RIPE 做基线时：单通道 SAR 应缩放到 [0,1]，保持 `nchannels=3` 才能用上 VGG19 预训练权重 |
| 灰度读图、除以 255 | LoFTR `cv2.IMREAD_GRAYSCALE` … `/ 255`（[dataset.py](https://github.com/zju3dv/LoFTR/blob/master/src/utils/dataset.py)） | 以 uint8 灰度训练的匹配网络 |
| RGB 输入再按 ImageNet 均值/方差标准化 | RoMa `TupleNormalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])`（[utils.py](https://github.com/Parskatt/RoMa/blob/main/romatch/utils/utils.py)） | 用 DINOv2/ResNet 等 ImageNet 骨干 |
| SAR 专用预训练权重（2 通道 VV/VH，dB 域 z-score） | torchgeo `SENTINEL1_GRD_*` 权重 | 输入必须按它的统计量归一化；与 Mini-RF 的极化量不对应，只能借首层以外的层 |

### 2.8 与传统方法（RIFT、HOPC、CFOG）同评时的输入

| 事实 | 出处 | 含义 |
|---|---|---|
| RIFT 示例读 `pair1.jpg`，`im2uint8(imread(...))`，单通道复制成 3 通道 | [RIFT_demo.m](https://github.com/LJY-RS/RIFT-multimodal-image-matching/blob/main/RIFT_demo.m) | 输入按 8 位图准备；`im2uint8` 对浮点输入按 [0,1] 解释并饱和，直接喂浮点 SAR 会出错 |
| RIFT 用相位一致性（PC）而非强度检测与描述，声称对非线性辐射畸变稳健 | RIFT 摘要（[arXiv:1804.09493](https://arxiv.org/abs/1804.09493)） | 对对比度差异相对不敏感，但仍受噪声阈值影响 |
| Kovesi `phasecong3` 的噪声补偿参数 k：“You may want to vary this up to a value of 10 or 20 for noisy images”；彩色图先 `rgb2gray`，再 `double` | [phasecong3.m](https://www.peterkovesi.com/matlabfns/PhaseCongruency/phasecong3.m) | 相干斑强时 PC 类方法（RIFT、HOPC）的参数与输入的噪声形态有关；dB 与线性输入的噪声形态不同 |
| CFOG 示例读 `optical_ref.png`、`SAR_sen.png`；3 通道才 `rgb2gray`，然后 `double`；CFOG 内部 `single(im)` 后做 L2（C 版）或 L1 归一化 | [demo.m](https://github.com/yeyuanxin110/CFOG/blob/main/demo.m)，[matchFramework.m](https://github.com/yeyuanxin110/CFOG/blob/main/matchFramework.m)，[CFOG.m](https://github.com/yeyuanxin110/CFOG/blob/main/pixel-wise%20feature%20represatation/CFOG/CFOG.m) | 描述子逐像素归一化，对整体增益不敏感 |
| CFOG 匹配框架丢弃被匹配影像上像素值 ≤ 0 的匹配：`if (im_Sen(Y_match,X_match)<=0) continue;` | [matchFramework.m](https://github.com/yeyuanxin110/CFOG/blob/main/matchFramework.m) | **SAR 若作为被匹配影像，输入必须严格为正**：dB 值、零均值标准化后的值都会被当成无效；8 位拉伸后被截到 0 的像素也会被丢 |
| CFOG 在参考影像上用 Harris（Noble 度量）选点 | [harrisValue.m](https://github.com/yeyuanxin110/CFOG/blob/main/harrisValue.m) | 选点依赖参考图的梯度与对比度 |
| HOPC 仓库同样以 PNG/TIF 8 位示例数据为输入 | [HOPC](https://github.com/yeyuanxin110/HOPC) | 同上 |
| SAR-SIFT 的 ROEWA 比值梯度针对线性强度的乘性相干斑 | Dellinger et al. 2015 | 若纳入 SAR-SIFT，按其设计应输入线性功率而非 dB |

小结：公开实现的传统方法都默认“8 位、对比度正常的灰度图”；数据集侧（OSdataset、SEN1-2）也都把 SAR 做成拉伸过的 8 位图后，深度与传统方法共用同一份输入。

## 3. 针对本数据集的候选方案

以下是候选，不是结论。编号便于后续票引用。

### 3.1 神经网络单通道（默认）

- **A1 全局 dB + 固定常数**：`x = 10·log10(max(S1, ε))`，ε 取远低于数据下限的常数（如 1e-4，即 −40 dB；Train 的 p0.1 为 −18.5 dB）；再用 **Train** 上算出的常数线性映射，例如 `(x − μ)/σ`，或按 Train 的 [p0.1, p99.9] dB 映到 [0,1] 且不截断/宽截断。float32。
  - 依据：SEN12MS、SSL4EO-S12、torchgeo 的做法；单调变换，除 ε 外不丢信息。
  - 风险：67 条条带若存在定标差，全局常数下各 ROI 的亮度基线不同，网络得自己吸收。
- **A2 逐 patch 标准化**：先取 dB，再在每个 patch 内做 z-score 或分位拉伸（float32，不量化）。
  - 依据：OSdataset、SEN1-2 的逐图做法；RIPE 的 `use_instance_norm`。
  - 取舍：丢掉绝对亮度（对配准通常无用），换来对条带间定标差的不敏感；不涉及划分间统计泄漏。
- **A3 线性 S1 做对照**：线性功率除以 Train 常数，不取对数。作用是检验“dB 是否必要”；预计右尾重、对比度被亮点压缩（p99.9 ≈ 2×p99）。

### 3.2 与 ImageNet 预训练权重配合

- **B1**：A1 或 A2 的结果缩放到 [0,1]，按灰度图处理：RIPE 保持 `nchannels=3` 由框架复制通道；timm 骨干用 `in_chans=1`（权重求和）。光学同样 `/255`。
- 前提：SAR 的 [0,1] 分布最好与光学的灰度分布相近，逐 patch 分位拉伸（A2）比全局常数更容易做到。

### 3.3 多通道

- **C1 {S1_dB, s2, s3, s4}**，其中 s_i = S_i/S1 ∈ [−1, 1]：与原四个波段一一对应，不丢信息；负值由构造自然处理，无需对带符号量取对数。
- **C2 {SC_dB, OC_dB}**：两者在本数据集全为正，物理意义明确（CPR = SC/OC 即两通道之差的 dB）。与 Sentinel-1 “双通道 dB” 惯例同形，可借 torchgeo 的 2 通道权重结构（统计量需重算）。
- **C3 {H_dB, V_dB}**：b1、b2 全为正；但 H/V 是接收天线基，对发圆收线的 Mini-RF 物理解释不如 SC/OC 直接。
- **C4 m-chi 三通道**（Raney et al. 2012）：三个非负分量，天然对应 RGB，可直接接 ImageNet 3 通道首层；但丢失 S2/S3 的部分方向信息，属有损派生。

### 3.4 给传统方法的版本（与网络输入分开）

- **D1 8 位 SAR**：S1 → dB → 逐 patch 分位拉伸（1%/99% 对齐 `imadjust` 默认，或 2%/98% 对齐本仓库文档站）→ uint8，并把输出下限设为 1 而不是 0（避开 CFOG 对 ≤0 像素的丢弃）。
- **D2 8 位 + 去斑**：在 D1 之前加一种经典去斑滤波（如 Lee，或 Argenti 综述里的方法），作为传统方法的“增强版”；需在报告里注明，避免被当作数据集本身的属性。
- **D3 光学同样拉伸**：对光学也做同一分位拉伸，使两侧对比度处理对称；是否需要取决于光学 patch 的对比度分布（未统计）。
- 公平性原则（依据 §2.8）：传统方法拿到的是“它的公开代码默认假设的输入”（8 位、拉伸过、正值），网络拿到的是不丢信息的 float 表示；报告里两者输入不同这一点要写明。

### 3.5 去斑（跨网络与传统方法）

- **E1 不去斑**作为默认（与 SEN1-2、SEN12MS 一致，也符合“不丢信息”）。
- **E2 去斑仅作消融**：8 视 dB 域相干斑标准差约 1.6 dB（§1 估算），可以对比有无去斑对网络和传统方法各自的影响。

## 4. 未查到或待核实

- 月球 Mini-RF 与光学配准的深度学习文献里具体用哪个派生量、是否取 dB：没有找到给出细节的一手来源（DEM 配准一文的可读文本未说明）。
- SEN1-2 的 ±2.5σ 是逐景统计还是全局统计，论文原文未写明。
- OSDataset2.0（[雷达学报 JR25176](https://radars.ac.cn/en/article/doi/10.12000/JR25176)）对 11 种方法的输入准备：网页未给细节，全文 PDF 未读。
- §1 的相干斑估算假设充分发育相干斑与 Gamma 分布；实际数据经过三次卷积重采样，局部统计会被平滑，应在均匀区域上实测。
- 67 条条带之间是否存在系统的定标差（决定 A1 与 A2 的取舍）：本次只做了按划分的汇总统计，未按 ROI 分组。

## 出处

- SEN1-2：Schmitt, Hughes, Zhu 2018，[arXiv:1807.01569](https://arxiv.org/abs/1807.01569)
- SEN12MS：Schmitt et al. 2019，[arXiv:1906.07789](https://arxiv.org/abs/1906.07789)；代码 [schmitt-muc/SEN12MS](https://github.com/schmitt-muc/SEN12MS/blob/master/classification/dataset.py)
- SSL4EO-S12：[zhu-xlab/SSL4EO-S12](https://github.com/zhu-xlab/SSL4EO-S12/blob/main/src/benchmark/pretrain_ssl/datasets/SSL4EO/ssl4eo_dataset.py)
- torchgeo：[models/resnet.py](https://github.com/microsoft/torchgeo/blob/main/torchgeo/models/resnet.py)，[datasets/sentinel.py](https://github.com/microsoft/torchgeo/blob/main/torchgeo/datasets/sentinel.py)
- OSdataset：[xym2009/OSdataset](https://github.com/xym2009/OSdataset)；MATLAB [`imadjust`](https://www.mathworks.com/help/images/ref/imadjust.html)
- QXS-SAROPT：[arXiv:2103.08259](https://arxiv.org/abs/2103.08259)
- deepdespeckling（MERLIN/SAR2SAR）：[hi-paris/deepdespeckling](https://github.com/hi-paris/deepdespeckling)
- RIFT：Li, Hu, Ai, IEEE TIP 29 (2020)，[arXiv:1804.09493](https://arxiv.org/abs/1804.09493)，[代码](https://github.com/LJY-RS/RIFT-multimodal-image-matching)
- CFOG：Ye et al., TGRS 2019，[yeyuanxin110/CFOG](https://github.com/yeyuanxin110/CFOG)；HOPC：[yeyuanxin110/HOPC](https://github.com/yeyuanxin110/HOPC)
- Kovesi 相位一致性：[phasecong3.m](https://www.peterkovesi.com/matlabfns/PhaseCongruency/phasecong3.m)
- SAR-SIFT：Dellinger et al., TGRS 53(1) 2015，[doi:10.1109/TGRS.2014.2323552](https://doi.org/10.1109/TGRS.2014.2323552)
- 去斑综述：Argenti et al., IEEE GRSM 1 (2013) 6–35，[doi:10.1109/MGRS.2013.2277512](https://doi.org/10.1109/MGRS.2013.2277512)
- m-chi 分解：Raney et al., JGR Planets 117(E12) 2012，[doi:10.1029/2011JE003986](https://doi.org/10.1029/2011JE003986)
- timm：[`adapt_input_conv`](https://github.com/huggingface/pytorch-image-models/blob/main/timm/models/_manipulate.py)
- RIPE：[fraunhoferhhi/RIPE](https://github.com/fraunhoferhhi/RIPE)
- LoFTR：[zju3dv/LoFTR](https://github.com/zju3dv/LoFTR/blob/master/src/utils/dataset.py)；RoMa：[Parskatt/RoMa](https://github.com/Parskatt/RoMa/blob/main/romatch/utils/utils.py)
- scikit-learn：[Common pitfalls — data leakage](https://scikit-learn.org/stable/common_pitfalls.html)
