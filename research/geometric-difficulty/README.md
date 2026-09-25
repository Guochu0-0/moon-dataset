# 调研：配准基准怎样逐样本刻画几何难度（重合度、变换大小与形状）

对应 issue #46（地图 #34，服务于决策 #42）。调研日期 2026-09-25。只写文献惯例与事实，不替作者做决定。
每条附一手出处；标「本文推断」的是由出处推出、出处本身没说的话；标「未核对」的是没能读到原文、
凭二手材料或记忆写下的内容。术语见 `CONTEXT.md`。

本数据集的对照事实取自 #40（分支 `research/ground-truth-residuals`）：验证集、测试集 patch 为
512×512、7.5 m；每个 patch 约 8 对评测真值点；逐 patch 仿射之后 x 仍剩约 3.5 像素的非仿射部分；
x 错位在 patch 内沿对角线变化中位 29 像素；y 几乎是纯平移（|dy| 中位 1.0 像素）。

## 0. 结论先行

| 量 | 有没有文献惯例 | 典型出处 | 对本数据集 |
|---|---|---|---|
| 重合度（overlap / co-visibility） | 有，且是**分档**的主轴 | 3DMatch / 3DLoMatch；SuperGlue、IMC 的 MegaDepth / PhotoTourism | 能算，但几乎不分档：每 patch 都在 0.7 以上，且接近平移量的单调函数，信息与平移重复 |
| 四角位移（corner displacement） | 有：合成单应数据的**生成范围**（±ρ）和**评测误差**（corner error） | DeTone 2016；SuperGlue、LoFTR 的 HPatches 评测 | 适用。等于「不做配准时的四角误差」，把平移与 patch 内变化合成一个像素量；但四角在 8 个点的凸包外，是外推 |
| 平移量 | 有，但多作为合成扰动的**生成参数**，不是逐样本报告的统计量 | SOMA（±32 px）、SOMA-1M（±30%）、HPatches（tmax） | 适用，对 y 足够；对 x 不够（#40 已排除） |
| 变换形状（旋转、尺度、各向异性、剪切） | 分解本身是教科书内容；数据集把它用作**生成参数**，几乎不对真实数据逐样本分解后报告分布 | Hartley & Zisserman；HPatches 的 EASY/HARD/TOUGH；SuperGlue、SOMA-1M 的合成单应 | 不推荐原样套用：本数据集的线性部分几乎全在 x 一行，分解会把 x 向剪切拆成「旋转 + 各向异性」，读出来的旋转是分解的产物 |
| 光学–SAR 数据集 | 公开数据集普遍**不报告**逐样本几何量；评测用的几何差异多是人为合成的 | OSdataset、SEN1-2、QXS-SAROPT、MultiResSAR、SOMA-1M | 本数据集的错位是真实的、有物理成因的，这一点本身是差异化卖点 |
| 医学配准：配准前的真值点位移 | 有，且与本数据集最像：用人工标记点在**配准前**的距离描述难度 | ANHIR（初始 rTRE、robustness）；DIR-Lab（逐病例位移均值，未核对） | 直接适用：逐点 `|d_i|` 或其每 patch 汇总，不依赖任何变换模型 |

术语上，文献把逐样本真值几何叫 **ground-truth transformation / homography / pose / warp**（第 1 节）；
本数据集没有这样一个真值变换，真值是**稀疏同名点**，逐 patch 仿射是由它们**拟合**出来的。

## 1. 术语：文献怎么称呼「逐样本的真值几何变换」

- **ground-truth transformation**：点云配准。PREDATOR 记作 `T̄_P^Q`，用它定义重合度与配准召回率
  （Huang et al., *PREDATOR: Registration of 3D Point Clouds with Low Overlap*, CVPR 2021,
  <https://arxiv.org/abs/2011.13005>，§3.1、附录 A.1）。
- **ground-truth homography**：平面单应。DeTone 等人把 4 点参数化「used as the associated ground-truth
  training label」，测试集为每对图生成「corresponding ground truth homography」（DeTone et al., *Deep Image
  Homography Estimation*, arXiv:1606.03798, 2016，§III、§V）；SOMA-1M 写作「ground truth homography matrix」，
  并定义为合成扰动矩阵的逆（Wu et al., *SOMA-1M*, arXiv:2602.05480，§4.1.1 式 (1)）。
- **ground-truth pose**：相对位姿（旋转 + 平移方向），MegaDepth / ScanNet / IMC 的评测对象（Jin et al.,
  *Image Matching across Wide Baselines*, IJCV 2021, arXiv:2003.01587，§3.3 标题即 On the quality of the
  "ground-truth"）。
- **ground-truth warp / flow**：稠密配准。SOMA 的损失对 `W^gt` 求 RMSE（Wang et al., *SOMA: Feature Gradient
  Enhanced Affine-Flow Matching for SAR-Optical Registration*, arXiv:2511.13168，Warp Loss 一节）。
- 遥感光学–SAR 数据集里，真值常以**点**的形式给出：OSDataset2.0 称「ground-truth correspondences」
  （Xiang et al., 雷达学报 2026, 15(3):983–995, <https://radars.ac.cn/en/article/doi/10.12000/JR25176>，
  仅读到摘要），MultiResSAR 称「ground truth points」（Zhang et al., arXiv:2502.01002，§4.3 与式 (2)）。
  OS-Eval 用两图上都清晰的「meta poles」作真值（<https://github.com/xym2009/OS-Eval>）。
- 合成数据集中「难度」参数通常叫 **perturbation**（扰动）、**geometric noise**（HPatches）或
  **transformation parameters**。

**本文推断**：本数据集的情形对应「真值同名点」（ground-truth correspondences / landmarks），而不是
「真值变换」。逐 patch 仿射是这些点的最小二乘拟合，外加约 3.5 像素的非仿射残余，把它叫
「真值变换」会暗示它是精确的。医学配准的叫法（landmarks、TRE）与此最贴近（第 6 节）。

## 2. 重合度（overlap ratio / co-visibility）

### 2.1 3DMatch 与 3DLoMatch

- **定义**：PREDATOR 式 (1)：在真值变换 `T̄` 下，源点云 P 中有多大比例的点，其变换后到 Q 的最近邻距离
  不超过容差 v：

  ```
  overlap(P, Q) = (1/|P|) · |{ p_i ∈ P : ‖T̄(p_i) − NN(T̄(p_i), Q)‖₂ ≤ v }|
  ```

  v 由点密度决定，实际按体素下采样的尺寸取（3DMatch 为 2.5 cm，表 6）。
- **分档**：3DMatch 只取重合度 >30% 的扫描对；PREDATOR 新建的 3DLoMatch 取 10%–30%（§4.1）。
  「3DMatch 原始基准取 >30%」这一句我是从 PREDATOR 的描述读到的，没有在 3DMatch 原文
  （Zeng et al., CVPR 2017, <https://arxiv.org/abs/1603.08182>）里逐页核对。
- 同文的 ModelNet / ModelLoNet 用的是另一种难度轴：旋转角 <45°、平移 [−0.5, 0.5]（§4.1）。
- **作用**：重合度既是**选样本的门槛**，也是**分档报告**的依据：同一方法在 3DMatch 与 3DLoMatch 上
  分别报告配准召回率。

### 2.2 MegaDepth、ScanNet、PhotoTourism（图像匹配）

- **D2-Net**：选取「sparse SfM point cloud 中至少 50% 重合」的图像对作为训练数据（Dusmanu et al., CVPR 2019,
  <https://arxiv.org/abs/1905.03561>，§4.2）。
- **SuperGlue**（Sarlin et al., CVPR 2020, <https://arxiv.org/abs/1911.11763>，附录）：
  - ScanNet：overlap score 是「A 中在 B 里可见的像素比例（反之亦然）的平均」，用真值位姿与深度算，
    检查深度一致性以排除遮挡；训练、测试都取 [0.4, 0.8]。正文说明这样选是为了得到更难（更宽基线）的对，
    而不是像以往那样按时间差或 SIFT 共视选。
  - MegaDepth：overlap score 是「两图中都可见的三角化关键点的比例」，训练时取 [0.1, 0.7]。
  - PhotoTourism：沿用 Ono 等人按包围盒算的重合度，取 [0.1, 0.4]。
- **Image Matching Challenge**（Jin et al., IJCV 2021, arXiv:2003.01587，§3.2）给出了最明确的逐样本定义：
  两图都观测到的 3D 点在图 i 上的包围盒面积 / 图 i 面积，记为 i 在 j 中的 visibility；两个方向取**较小者**
  为 co-visibility `v_ij ∈ [0, 1]`，「characterizes how challenging matching of the particular image pair is」。
  评测剔除 v < 0.1 的对，并按 0.1+、0.2+、…、0.6+ 的阈值分档报告 mAA（§6.9、图 21–22）。
- LoFTR 沿用 SuperGlue 的 ScanNet [0.4, 0.8]（Sun et al., CVPR 2021, <https://arxiv.org/abs/2104.00680>）。

### 2.3 对本数据集

- **可以算**。patch 是方的、两侧同尺寸，逐 patch 仿射 `q = A p + t` 已知，可以直接照 IMC 的面积定义算：
  `overlap = area(W ∩ f(W)) / area(W)`，W 为 512×512 窗口，f 为逐 patch 仿射（本文推断，公式是 IMC 定义
  在已知变换下的直接改写）。仓库里已有同样的几何：`src/moondata/geometry.py` 的 `candidate_windows` 按
  「变换后四边形与 SAR 窗口的重叠比」≥70% 剔除窗口，只是那里用的是全局仿射。
- **几乎不分档**（本文推断）：线性部分很小时，`overlap ≈ (1 − |dx|/512)(1 − |dy|/512)`。按 #40 的
  patch 中心偏移，|dx| 中位 25 像素、95 分位 140 像素，对应重合度约 0.95 与 0.73；全部落在 3DMatch 的
  「>30%」一档，远离 3DLoMatch 与 IMC 关心的 0.1–0.4 区间。并且它近乎是平移量的单调函数，不提供平移之外的
  信息。
- 重合度在点云、宽基线匹配里是主轴，是因为那里的难点是「有多少东西在两边都看得见」。本数据集的难点是
  重合区里模态差异和 x 向的非刚性错位，重合度抓不住这一点。

## 3. 变换有多大：四角位移与平移

### 3.1 深度单应估计的 4 点参数化与 ±ρ

- **参数化**：DeTone 等人指出把 3×3 单应展开成向量会「mixing both rotational and translational terms」，
  难以在优化中平衡，于是改用四个角的位移 `(Δu_k, Δv_k), k = 1..4`（8 个数，与 8 自由度单应一一对应）
  （arXiv:1606.03798，§II）。
- **生成难度**：在 patch 上把四角各自在 `[−ρ, ρ]` 内均匀扰动，四对对应点确定 `H_AB`。训练用 128×128、
  ρ = 32（「each corner … can be perturbed by a maximum of one quarter of the total image edge size」）；
  测试用 256×256、ρ = 64（§III、§V）。
- **评测**：Mean Average Corner Error：估计角点与真值角点的 L2 距离，四角平均，再对测试集平均（§V、图 5）。
  图 5 同时给出「对每对都估计单位阵」的基线。**本文推断**：单位阵基线的 corner error 恰好就是每个样本的
  真值四角位移的均值，这是深度单应文献里「逐样本变换大小」最直接的量。
- **延续**：SuperGlue 在 HPatches 上计算「mean reprojection error of the four corners」并报告到 10 像素的
  累积曲线 AUC（§5.1）；LoFTR 报告 corner error 在 3、5、10 像素阈值下的 AUC。这里 corner error
  是**误差**指标，但同一个量套在单位阵上就是**难度**指标。

### 3.2 平移量

- 平移几乎只作为合成扰动的**范围**出现，而不是真实数据上逐样本报告的分布：
  - HPatches：`t_x, t_y ∈ [−t_max, t_max]`，以 patch 尺度为单位，EASY/HARD/TOUGH 分别为 0.15/0.3/0.45
    （Balntas et al., CVPR 2017, <https://arxiv.org/abs/1704.05939>，§4、表 4）。
  - SOMA：对 SAR 图施加最多 32 像素平移、0.2 的尺度变化、±5° 旋转，称「following the previous protocols」；
    消融加大到 50 像素、±20°（arXiv:2511.13168，实验设置与附录 B）。「previous protocols」指哪篇，原文
    没有在该句给出，**未核对**其出处。
  - SOMA-1M：平移为图宽、高的 ±30%（§4.1.1）。
- 点云配准里另有以真值变换的**旋转角、平移长度**描述样本的做法（如 PREDATOR 的 ModelNet 设定），在
  3DMatch 一类真实数据上则不作为主轴。

### 3.3 对本数据集

- **四角位移适用，而且是 #42 候选里「中心值加半跨度」的规范写法**（本文推断）：对逐 patch 仿射 f，
  四角位移 `d_k = f(c_k) − c_k`。`max_k |d_k|` 给出 patch 内最大错位，`mean_k |d_k|` 正是 DeTone 意义下的
  「单位阵基线的平均角点误差」。它把「中心平移」和「x 向跨度」合成一个像素量，并且与深度单应文献的误差
  单位一致，方便读者拿方法的 corner error 与之对比。
- **限制**：四个角在 8 个真值点的凸包之外，角点值是仿射的**外推**，外推误差随点的分布变化；非仿射残余
  （约 3.5 像素）不在其中。若担心外推，可改在真值点处取 `|d_i|`（第 6 节），或在凸包内取最大值。
- **平移**：对 y 足够（#40）。对 x，单一平移会漏掉 patch 内中位 29 像素的变化，不宜作唯一的难度标量。
- 合成扰动的范围可作量级参照（本文推断）：DeTone 的 ρ = 32 是 128 边长的 1/4；SOMA 的 32 像素平移用在
  SEN1-2 的 256×256 上，约为边长 1/8。本数据集 |dx| 的 95 分位 140 像素，是 512 边长的约 27%，与这些合成
  设定处在同一量级，但它是真实的、空间上连续变化的，而不是一次性施加的全局变换。

## 4. 变换的形状：把仿射或单应分解成旋转、尺度、各向异性、剪切

### 4.1 分解的标准形式

- **仿射分解**：Hartley & Zisserman 把仿射的线性部分写成 `A = R(θ) R(−φ) D R(φ)`，`D = diag(λ1, λ2)`：
  先转到 φ 方向，沿两轴各自缩放 λ1、λ2，再转回并旋转 θ；这实质上是 SVD（Hartley & Zisserman,
  *Multiple View Geometry in Computer Vision*, 2nd ed., 2004, §2.4.3）。**未核对**：公式与节号凭记忆，
  没有读到原书页面。
- **可核对的等价写法**：Lindeberg 给出 2-D 仿射矩阵的闭式分解，形式上是「pre- 与 post- 矩阵都限定为旋转」的
  SVD，参数为两个奇异值与两个角，并在附录 A.2 逐一分析纯缩放、纯旋转、非均匀缩放、剪切（skewing）这四种
  基本变换在分解中的参数（Lindeberg, arXiv:2411.05673，§3、附录 A.1–A.2、图 3）。
- **单应分解**：`H = H_S H_A H_P`（相似 × 仿射 × 射影），同见 H&Z §2.4.6（**未核对**，凭记忆）。
- **分解不唯一**（本文推断）：同一个 A 可按 SVD、极分解 `A = R S`、或「尺度 × 剪切 × 旋转」（QR 型）写，
  得到的「旋转角」「剪切量」数值不同。任何报告分解参数的表都必须写明用了哪一种。

### 4.2 数据集怎么用分解

- **作为生成参数，而非统计报告**：
  - HPatches 对检测区域施加随机变换，参数为旋转 θ、平移 t、尺度 s、各向异性 a，在
    `θ ∈ [−θmax, θmax]`、`log2(s) ∈ [−smax, smax]`、`log2(a) ∈ [−amax, amax]` 内均匀采样；
    EASY/HARD/TOUGH 的 θmax 为 10°/20°/30°，smax 为 0.15/0.3/0.5，amax 为 0.2/0.4/0.45（§4、表 4）。
    这是「逐样本几何难度按分解参数分三档」最明确的先例，但档位是**设计出来的**，并用 Oxford 序列中
    检测器的重叠精度来标定（图 3）。
  - SuperGlue 的合成单应测试集：「random perspective, scaling, rotation, and translation」（附录中对 §5.1 的补充说明）。
  - SOMA-1M：旋转 ±108°、平移 ±30%、尺度 0.7–1.3（§4.1.1）。SOMA：±5°、0.2 尺度、32 像素（同上）。
- **真实数据上的逐样本分解分布**：本次检索没有找到哪个主流配准基准对**真实**样本的真值变换做分解并报告
  各参数分布。Oxford Affine 数据集按序列标注视角变化角度与缩放倍数（Mikolajczyk et al., IJCV 2005），
  那是按采集条件标的，不是由真值单应分解出来的（**未核对**，凭记忆）。

### 4.3 对本数据集

- **不推荐原样套用旋转—尺度—各向异性分解**（本文推断）。#40 的结论是：y 几乎纯平移，线性变化几乎全在
  x 的错位里，即逐 patch 仿射近似为

  ```
  dx = t_x + a·x + b·y      (a = ∂dx/∂x，距离向的尺度差；b = ∂dx/∂y，剪切)
  dy ≈ t_y
  ```

  这种「单行」线性部分在 SVD 型分解下会被拆成旋转加各向异性。数值例子（本文计算）：`A = [[1, k], [0, 1]]`
  取 k = 29/512 ≈ 0.057（x 错位沿 y 方向跨 patch 变化 29 像素），SVD 给出「旋转」−1.6°、奇异值比 1.058；
  k = 0.1 时为 −2.9°、1.105。行列式恒为 1，没有面积变化。读者看到「旋转 1.6°」会以为两图相对转了，
  实际上 y 方向没有任何对应的变化。
- **更贴合物理的参数化**（本文推断）：直接报告 x 向错位的梯度 `(∂dx/∂x, ∂dx/∂y)` 或它在 patch 上造成的
  像素跨度（#40 已用「沿对角线的变化」），并单列非仿射残余。这对应 SAR 地形位移只发生在距离向这一成因
  （#40 中 σ̂x 与入射角的相关）。
- 如果仍想与 HPatches 式档位对照，只有「平移」和「x 向尺度差」两项有明确意义；「旋转」「各向异性」
  「剪切」三者在这里是同一现象的不同写法。

## 5. 光学–SAR 与遥感多模态配准数据集报告了什么

| 数据集 | 真值怎么来 | 是否报告逐样本几何量 | 出处 |
|---|---|---|---|
| SEN1-2 | 依靠 Sentinel-1/2 的正射校正与地理编码，作者称为 co-registered patch pairs | 全文检索未见逐样本错位或变换的统计 | Schmitt, Hughes, Zhu, ISPRS Annals 2018, <https://arxiv.org/abs/1807.01569> |
| OSdataset | 地理信息粗配准 + 改进相位一致性精配准，取 1000×1000 块的中心 512×512；人工目检剔除有变换畸变或地物变化的块 | 否；配准后视为对齐 | <https://github.com/xym2009/OSdataset>；Xiang et al., IEEE JSTARS 13:5847–5861, 2020 |
| QXS-SAROPT | 人工选同名点，用现有软件把光学配到 SAR（双线性），再切 256×256 | 否 | Huang et al., arXiv:2103.08259，§II-E |
| OS-Eval | 以两图都清晰的「meta poles」为真值点，提供相对 / 绝对两套 | 未在 README 中看到逐样本几何统计 | <https://github.com/xym2009/OS-Eval>；Xiang et al., IEEE TGRS 2023 |
| MultiResSAR | 自动配准结果上，由测绘遥感专业人员均匀选取若干控制点，误差控制在 1 像素内；用这些点算 RMSE、NCM、SR | 否（按传感器、分辨率、场景分组，不按几何分档） | Zhang et al., arXiv:2502.01002，§4.2–4.4 |
| OSDataset2.0 | 「high-precision, uniformly distributed ground-truth correspondences」 | 仅读到摘要，**未核对**正文 | 雷达学报 2026, 15(3):983–995 |
| SOMA-1M | 粗到精的自动配准，局部单应精配准（RANSAC 阈值 1.5 px） | 评测时**人为**对左图施加随机单应（旋转、平移、尺度，范围见 4.2），真值为扰动矩阵之逆 | arXiv:2602.05480，§3、§4.1.1 |
| SOMA（方法论文） | 在 SEN1-2 等「finely aligned」数据上人为施加平移、尺度、旋转 | 只有生成范围 | arXiv:2511.13168 |

要点：

- 公开的光学–SAR 数据集多是「先把两图配准好，再当作对齐」。MultiResSAR 明确指出「publicly available
  datasets do not provide accurate registration ground truth」（§4.1 末）。
- 于是评测时的几何差异几乎都是**合成**的：在对齐图对上施加随机平移、旋转、尺度，难度只由生成范围描述。
- 真实残余错位在遥感里有记录，但不作为数据集字段：Ye 等人报告 Sentinel-1/2 间的错位随地形起伏显著变化
  （arXiv:2005.11092，已在调研 #39 的笔记中引用）。
- 综述（Zhu et al., *Advances and Challenges in Multimodal Remote Sensing Image Registration*,
  arXiv:2302.00912）列出的多模态数据集表中，也只有名称、模态、规模与链接，没有几何难度一栏。

**本文推断**：本数据集的每个 patch 带真实（非合成）的逐 patch 仿射与非仿射残余，这在光学–SAR 公开数据集中
没有先例可循，也就没有可以直接照抄的报告格式；最近的参照是下一节的医学配准。

## 6. 医学配准：用真值点在配准前的位移描述难度

与本数据集最相像的场景：真值是人工标记点，没有精确的真值变换，变形也不限于低阶模型。

- **ANHIR**（Borovec et al., IEEE TMI 2020；指标定义见 <https://anhir.grand-challenge.org/Performance_Metrics/>）：
  - `TRE = d_e(x_l^T, x_l^W)`，目标图与形变后图中同一标记点的欧氏距离；
  - `rTRE = TRE / √(w² + h²)`，按图像对角线归一化；
  - robustness `R_i = (1/|L_i|) Σ_j [rTRE_j^regist < rTRE_j^init]`：配准后比**配准前**更近的标记点比例。
  其中 `rTRE^init` 就是逐标记点的初始错位，即难度的基准。
- **DIR-Lab 4DCT**（Castillo et al., Phys. Med. Biol. 54(7), 2009, <https://doi.org/10.1088/0031-9155/54/7/001>）：
  每个病例 300 个人工标记点，按病例报告配准前标记点位移的均值与标准差，作为该病例的运动（难度）大小。
  **未核对**：官网页面本次访问超时，具体数值与表格形式没有读到原文。

**对本数据集**（本文推断）：直接取评测真值点上的 `|d_i| = |q_i − p_i|`（配准前错位），按 patch 汇总成
均值、最大值或 RMS，就是 ANHIR / DIR-Lab 式的难度量。它不依赖仿射假设，自动包含非仿射残余，只在真值点
处取值（不外推），并可按 patch 对角线（512√2 ≈ 724 像素）归一化得到 rTRE 式的相对量。代价是它受约 1 像素
的标注误差影响（#40），对 |d| 在几像素以下的 patch 相对误差较大。

## 7. 小结：哪些量适合本数据集

| 候选量 | 定义 | 与惯例的关系 | 适用性（本文推断） |
|---|---|---|---|
| 中心平移 `(t_x, t_y)` | 逐 patch 仿射在 patch 中心的错位 | 合成扰动的平移参数 | y 足够；x 不够 |
| 四角位移 `max_k |d_k|`、`mean_k |d_k|` | 逐 patch 仿射在四角的错位 | DeTone 4 点参数化；单位阵基线的 corner error | 适合作单一标量；注意外推 |
| 真值点初始错位 `|d_i|` 的每 patch 汇总 | 逐点 `|q_i − p_i|` | ANHIR `rTRE^init`；DIR-Lab 初始位移 | 最稳健、无模型假设；受标注误差影响 |
| x 错位梯度 `(∂dx/∂x, ∂dx/∂y)` 或跨度 | 仿射 x 行的线性系数 | 无直接惯例；对应分解中的尺度差与剪切 | 贴合距离向位移的成因，适合描述「形状」 |
| 旋转、各向异性（SVD 分解） | `A = R(θ)R(−φ)DR(φ)` | HPatches 的生成参数 | 不推荐：旋转是分解的产物 |
| 重合度 | `area(W ∩ f(W)) / area(W)` | 3DMatch、IMC 的主分档轴 | 能算但全在 0.7 以上，与平移重复 |
| 非仿射残余 | 仿射拟合后真值点的残差 RMS | 无直接惯例 | 单独报告，x 约 3.5 像素、y 约 1.2 像素（#40） |

## 8. 未核对与局限

- 3DMatch 原文的 30% 门槛：只核对了 PREDATOR 对它的描述。
- Hartley & Zisserman 的仿射分解公式与节号、单应分解 `H_S H_A H_P`：凭记忆，未读原书；可核对的替代出处为
  Lindeberg arXiv:2411.05673。
- Oxford Affine 数据集按视角角度、缩放倍数标序列：凭记忆。
- DIR-Lab 按病例报告初始位移：凭记忆与检索摘要，未读到原表。
- OSDataset2.0：只读到摘要与图注。
- SOMA 所说「previous protocols」（32 像素、0.2、±5°）的来源文献未追到。
- SEN1-2、QXS-SAROPT、MultiResSAR「未报告逐样本几何量」是对全文文本检索的结论，图表中的内容可能漏看。
