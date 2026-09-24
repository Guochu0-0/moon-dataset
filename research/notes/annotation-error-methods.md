# 调研：没有重复标注时，估计人工同名点标注误差的方法

对应 issue #39（地图 #34）。调研日期 2026-09-25。只写方法与文献事实，不替作者做决定；
凡是「本文推断」的地方都单独标出，其余每条附一手出处。

## 1. 问题的形式化

术语见 `CONTEXT.md`。对一个 patch 对上的第 i 对评测真值点，记光学坐标 `p_i`、SAR 坐标 `q_i`，
测到的偏差是

```
d_i = q_i - p_i = g(p_i) + e_i
```

- `g(·)`：该 patch 内光学与 SAR 之间真实的**残余错位**（由整幅重叠区上的全局仿射切出 patch 后
  剩下的局部几何差异；样例中 0–45 px，各点不一致）。
- `e_i`：**标注误差**，等于 SAR 侧点击误差减去光学侧点击误差。两侧独立时
  `Var(e) = σ_opt² + σ_sar²`；只看 `d_i` 无法把两侧分开。

**可辨识性（本文推断，但下面各方法都隐含它）**：每个点只标一次时，`g` 与 `e` 在单个点上不可分。
所有「无重复标注」的方法都要靠对 `g` 的结构性假设（在 patch 内是低阶变换、空间上平滑或空间相关）
与对 `e` 的假设（点间独立、零均值、同分布）来分离两者。**假设错多少，估计就偏多少，而且几乎总是
把一部分真实局部几何差异算进标注误差，得到的是上界。** 只有重复标注（第 7 节）不依赖对 `g` 的假设。

## 2. 方法一：patch 内局部参数变换拟合的残差

**做法**：在每个 patch 内用最小二乘拟合平移（p=2）、相似（p=4）或仿射（p=6）把 `p_i` 映到 `q_i`，
取残差平方和 RSS。若模型对 `g` 完全正确、`e` 为各向同性、独立、每坐标方差 σ² 的高斯噪声，
则 `E[RSS] = σ²·(2N − p)`，无偏估计 `σ̂² = RSS / (2N − p)`；跨 patch 汇总时分子分母分别求和。

- 点配准文献中的同一关系：Fitzpatrick、West、Maurer 推导了刚体点配准的 fiducial registration error
  (FRE) 与 fiducial localization error (FLE) 的关系，3D 刚体下 `⟨FRE²⟩ ≈ (1 − 2/N)⟨FLE²⟩`，即上式在
  3N 个坐标、6 个参数时的特例。出处：Fitzpatrick et al., *Predicting error in rigid-body point-based
  registration*, IEEE TMI 17(5), 1998, <https://doi.org/10.1109/42.736021>。
- N=8 时每 patch 的自由度：平移 14、相似 12、仿射 10。模型越灵活，自由度越少，但吸收的真实错位越多。

**假设**：`g` 在 patch 内恰好是所选的低阶变换；`e` 独立同分布、无粗差。

**局限**：
- `g` 的非线性部分（撞击坑边缘、地形起伏造成的 SAR 局部位移）全部进入残差，σ̂ 是**上界**。
  Ye 等人对 Sentinel-1/2 的实测表明，SAR 与光学之间的错位随地形起伏显著变化，并且在同一幅影像内
  分布不均（标准差大），平坦区 1 阶多项式在检查点上的 RMSE 超过 10 px，而 2–5 阶多项式为亚像素级：
  Ye et al., *Improving Co-registration for Sentinel-1 SAR and Sentinel-2 Optical images*,
  <https://arxiv.org/abs/2005.11092>（第 4.3–4.4 节、表 4–5）。这说明低阶模型的残差可以远大于点位误差。
- 单个 patch 的拟合残差不能说明该 patch 的真实精度：Fitzpatrick 用仿真证明 FRE 与 target registration
  error (TRE) 不相关，<https://doi.org/10.1117/12.813601>（SPIE 7261, 2009）。因此残差只宜汇总成
  **总体**的 σ 估计，不宜逐 patch 解读。
- 对粗差敏感；ASPRS 标准把偏差超过目标 RMSE 三倍的检查点视为 blunder、须先查明：
  ASPRS Positional Accuracy Standards, Edition 2 (2023), §7（第 496–498 行），
  <https://aagsmo.org/wp-content/uploads/2023/03/ASPRS_PosAcc_Edition2_MainBody.pdf>。

## 3. 方法二：留一交叉验证（LOO）与独立检查点

**做法**：每次留出一个点，用其余 N−1 个点拟合变换，预测被留点，得到预测误差；或者像摄影测量
那样把点分成控制点（CP）与检查点，只用检查点报告精度。Ye 等人即用 95 个 CP、48 个检查点报告各几何
模型的检查点 RMSE（同上 arXiv:2005.11092，表 5）。线性最小二乘的 LOO 残差有闭式
`r_(−i) = r_i / (1 − h_ii)`（`h_ii` 为 hat 矩阵对角元），见 Hastie, Tibshirani, Friedman,
*The Elements of Statistical Learning*, 2nd ed., §7.10，<https://hastie.su.domains/ElemStatLearn/>。

**假设**：同方法一，另需被留点与拟合点的误差独立。

**局限**：
- LOO 衡量的是**预测误差** = 标注误差 + 模型对 `g` 的插值误差，不是纯标注误差；它比拟合残差更诚实
  （不会被过拟合压低），但仍是上界。
- N=8、仿射每坐标 3 个参数时，平均 leverage = 3/8，边缘点更高；留一后只剩 7 点，估计噪声大。
  它的主要价值在于**比较模型**（平移 / 仿射 / TPS 哪个对 `g` 描述得更好），而不是直接给出 σ。

## 4. 方法三：平滑薄板样条（approximating TPS）与广义交叉验证

**做法**：插值型 TPS 会让所有点残差为零，无法估计噪声；应改用带正则的平滑 TPS，用广义交叉验证
（GCV）选平滑参数，并用 `σ̂² = RSS / tr(I − A)` 估计噪声方差（A 为 influence matrix）。
- Craven & Wahba, *Smoothing noisy data with spline functions*, Numer. Math. 31, 1979,
  <https://doi.org/10.1007/BF01404567>。
- 在点配准中把点位误差（各向同性或各向异性协方差）纳入 approximating TPS：Rohr et al.,
  *Landmark-based elastic registration using approximating thin-plate splines*, IEEE TMI 20(6), 2001,
  <https://doi.org/10.1109/42.929618>。

**假设**：`g` 足够平滑（弯曲能量小），`e` 为白噪声。

**局限**：每 patch 只有 7–11 点，GCV 在如此小的 N 上很不稳定；平滑程度与噪声大小此消彼长，
小样本下两者近乎不可辨识（本文推断）。更可行的做法是把点放回重叠区影像坐标、在 ROI 尺度上汇总
（见方法四）。

## 5. 方法四：跨 patch 汇总的空间统计（变异函数 nugget / 高斯过程 + 白噪声）

**做法**：把 `d_i`（或它对全局仿射、对 patch 平移的残差）当成空间随机场的观测，估计经验变异函数
`γ(h) = ½·E[(d_i − d_j)²]`（按分量、按点间距 h 分组）。若 `g` 空间连续，则 `γ(h) = σ² + γ_g(h)`，
`γ_g(0) = 0`，外推到 h→0 的 **nugget** 即标注误差方差 σ²（每分量）。

- 变异函数把误差分解为不相关的 nugget 与空间相关部分（sill、range），并用于遥感几何/高程误差：
  Hugonnet et al., *Uncertainty analysis of digital elevation models by spatial inference from stable
  terrain*, IEEE JSTARS 15, 2022, <https://ieeexplore.ieee.org/document/9815885/>；实现与说明见 xDEM 文档
  <https://xdem.readthedocs.io/en/stable/spatial_stats.html>。
- 同一思路的贝叶斯版本：把配准误差建成带指数协方差的高斯过程、把读片者（reader）点位误差建成独立
  正态，分层模型联合估计：Liu et al., *Evaluation of image registration spatial accuracy using a
  Bayesian hierarchical model*, Biometrics 70(2), 2014, <https://pmc.ncbi.nlm.nih.gov/articles/PMC4061263/>。
  注意该文用到了同一读片者相隔数周的两次标注来帮助辨识读片者误差。

**为什么适合本数据集（本文推断）**：每 patch 约 8 点、约 28 个点对；`data/ground-truth/` 下有 1605 个
带点的 patch 文件，点对总数上万，足以估计短距离段的变异函数；而且 patch 窗口在重叠区影像上的位置
已知，可以把相邻 patch 的点放到同一坐标系里，得到跨 patch 的点对，覆盖更大的距离范围。

**假设**：`g` 在小尺度上连续、（分块）平稳；`e` 点间独立、与位置无关（或可用协变量建模异方差）。

**局限**：
- nugget = 标注误差 + 小于最小点距的**微尺度**真实变化（例如 SAR 侧视几何在坑缘处造成的突变）。
  月面地形起伏正是 Ye 等人指出的错位随地形增大的情形（arXiv:2005.11092），因此 nugget 仍是上界。
- 外推到 h=0 依赖变异函数模型形式与最短点距；需要报告对模型选择的敏感性。
- 宜按分量（x/y，或 SAR 的距离向/方位向）分别估计，检查各向异性。

## 6. 方法五：与自动匹配结果比较、三角法（triple collocation）

**做法**：在每个人工点附近用多模态模板匹配（如 Ye 等人的 CFOG 描述子 + 3D phase correlation，
arXiv:2005.11092 第 3 节）得到自动同名点，比较人工与自动的差。只比较两者时，差的方差 =
人工误差 + 匹配误差，无法拆开；若有**三套**误差互相独立的测量（人工、匹配器 A、匹配器 B），
可用 triple collocation 分别估计每套的误差方差，例如 `Var(e_H) = E[(d_H − d_A)(d_H − d_B)]`。
出处：Stoffelen, *Toward the true near-surface wind speed: Error modeling and calibration using triple
collocation*, JGR 103(C4), 1998, <https://doi.org/10.1029/97JC03180>。

**假设**：三套测量指向同一个「真值」；误差零均值、两两独立。

**局限**：
- 匹配器与人工都依赖同一处图像结构（边缘、坑缘），误差很可能正相关，triple collocation 会低估人工
  误差（本文推断）。
- 若模板取自人工的光学点、只在 SAR 上搜索，则光学侧点击误差被双方共享，比较只反映 SAR 侧
  （本文推断）。
- 光学–SAR 的「同一地物」本身有定义歧义（SAR 亮边与光学阴影边未必是同一处），匹配器的「真值」
  与人的「真值」可能系统性不同；匹配失败呈重尾，需要稳健统计。

## 7. 方法六：小样本补标（重复标注）

**做法**：随机抽取一部分已标点，隔一段时间在**不看原标注**的条件下重新标注（同一人：intra-observer；
另一人：inter-observer）。两次标注差 `δ` 的每分量方差为 `2σ²`，即 `σ̂² = mean(δ²)/2`。
- 重复测量估计测量误差的标准做法：Bland & Altman, *Measurement error*, BMJ 313:744, 1996,
  <https://doi.org/10.1136/bmj.313.7059.744>。
- 配准评测中的先例：Castillo et al. 用每例 >1100 对肺部 landmark 评测形变配准，并通过重复标注估计
  观察者内/观察者间变异；还给出空间误差估计的不确定度与 `σ/√n` 成正比、可据此算样本量：
  *A framework for evaluation of deformable image registration spatial accuracy using large landmark
  point sets*, Phys. Med. Biol. 54(7), 2009, <https://doi.org/10.1088/0031-9155/54/7/001>。

**假设**：两次标注误差独立（间隔足够、盲标）；重标流程（工具、缩放、显示拉伸）与原标注一致。

**局限**：
- 只测到**随机**部分；同一人稳定的系统偏好（例如总点 SAR 亮边的外沿）两次都会出现，测不到，
  需要 inter-observer 补上（本文推断）。
- 需要人工工时，但样本量可控：σ̂ 的相对标准误约为 `1/√(2·dof)`，n 个点两分量 dof=2n，
  n=25 约 10%，n=50 约 7%，n=100 约 5%（卡方分布的标准近似）。这只是统计精度，要覆盖不同纹理与
  ROI 还需分层抽样。
- 它是唯一不依赖 `g` 结构假设的方法，因此最适合当作**锚点**去校准方法一至四的上界偏多少。

## 8. 附：独立专家分级审核

3MOS 数据集在人工配准后请**未参与配准的专家**逐位置把误差分为 ≤1 px、1–3 px、>3 px、不可辨四类，
剔除不可辨区域后给出各卫星的平均误差（见第 10 节表）：*3MOS: Multi-sources, Multi-resolutions, and
Multi-scenes dataset for Optical-SAR image matching*, <https://arxiv.org/abs/2404.00838>（表 2）。这是一种低成本的抽检方式，但给出的是分级判断，
不是连续误差分布。

## 9. 标注误差对评测指标的含义

- 若算法误差与标注误差独立，则以评测真值点量出的均方误差 ≈ 真实均方误差 + σ_e²（二维时 + 2σ²）。
  ASPRS 2023 标准正是把检查点自身误差按平方和并入产品精度：`RMSE_H = √(RMSE_H1² + RMSE_H2²)`，
  并要求检查点至少比被评产品精度高两倍（§7.11–7.12，出处同上）。
- 因此评测指标存在下限：σ_e 附近及以下的算法差异无法用这套真值点分辨；以阈值计的成功率
  （如 < t px）在 t 接近 2–3σ_e 时会被噪声明显拉低（本文推断）。

## 10. 已有光学–SAR 数据集如何报告对齐/标注精度

| 数据集 | 对齐方式 | 报告的精度 | 出处 |
|---|---|---|---|
| SEN1-2 | Sentinel-1 GRD 用精轨 + SRTM/ASTER DEM 正射；Sentinel-2 为已地理编码产品；无人工点 | 未给出配准精度数值，只引用 Sentinel-1 的地理定位精度 | Schmitt et al., 2018, <https://arxiv.org/abs/1807.01569> |
| （参照）Sentinel-1/2 | — | 按 ESA 定位指标推算，两者间仍可能有约 2 个 10 m 像元的错位；未做地形校正的 L1 产品实测错位平坦区 20–30 px、丘陵 20–40 px、山区 50–60 px | Ye et al., <https://arxiv.org/abs/2005.11092> |
| OS-Dataset | 对 1000×1000 块用作者的相位一致性（PC）配准方法自动配准后取中心部分 | 仓库 README 无数值；论文（IEEE JSTARS 2020）未能获取全文，未核实 | <https://github.com/xym2009/OSdataset>，<https://ieeexplore.ieee.org/document/9204802/> |
| QXS-SAROPT | 按子区域人工选建筑、船、道路等角点作匹配点，再用软件配准 | 未给出精度数值 | Huang et al., <https://arxiv.org/abs/2103.08259> |
| SOPatch | 由 WHU-SEN-City、OS-Dataset、SEN1-2 再精配准（3MOS 表 1 记为 RIFT + CFOG）；另**故意**加入位置与旋转噪声 | 摘要无数值；全文付费墙，未核实 | Xu et al., JAG 122:103433, 2023, <https://doi.org/10.1016/j.jag.2023.103433>；<https://arxiv.org/abs/2404.00838> |
| WHU-OPT-SAR | GF-1 与 GF-3 重采样到 5 m、WGS84 | 仓库与摘要均未给配准精度；论文全文未获取 | <https://github.com/AmberHen/WHU-OPT-SAR-dataset>，<https://doi.org/10.1016/j.jag.2021.102638> |
| 3MOS | 正射后，专家均匀选数十个控制点，一阶多项式配准 | 独立专家分级审核后的平均误差：SEN1 0.31±0.34、TerraSAR 0.52±0.63、GF3 0.81±0.71、Radarsat 0.74±0.66、ALOS 0.79±0.81、RCM 1.20±1.1 px | <https://arxiv.org/abs/2404.00838>（表 2） |
| MultiResSAR | 自动配准 + 测绘专业人员均匀选控制点人工核验 | 声明「误差控制在一个像素以内」，未给测量方法与分布 | Zhang et al., <https://arxiv.org/abs/2502.01002>（§4.3） |
| OSEval | 以光学与 SAR 上结构清晰的金属杆等点作真值 | README 未给数值 | <https://github.com/xym2009/OS-Eval> |
| SARptical | TomoSAR 点云与光学点云的三维重建与匹配 | 本次未核实数值 | Wang & Zhu, <https://arxiv.org/abs/1801.07532> |

共同点：
- 公开数据集几乎都只报告**配准（对齐）精度**，没有一个报告了逐点**标注误差**的估计；MultiResSAR 的
  综述直言「公开数据集不提供精确的配准真值」（arXiv:2502.01002 §4.1）。
- 给出数值的（3MOS、MultiResSAR）都在 0.3–1.2 px 量级，且依赖人工判断，不是重复标注统计。
- 本数据集与它们的区别：patch 对**有意保留**真实残余错位，评测真值点用来量它，所以必须把标注误差
  与残余错位分开，而上述数据集都假定 patch 已对齐。

## 11. 适合本数据集（每 patch ~8 点）的方法建议清单

供作者取舍，不是决定：

1. **先做便宜的上界**：每 patch 拟合平移 / 相似 / 仿射，按 `ΣRSS / Σ(2N − p)` 汇总得到 σ 的上界；
   同时做 LOO，比较三种模型的预测误差，判断 patch 内 `g` 是否接近平移或仿射。先剔除粗差
   （参照 ASPRS 的 3 倍规则）。
2. **主估计用空间统计**：把全部点按窗口位置放回重叠区影像坐标，对「偏差减全局仿射」的残差按分量
   估计变异函数，以 nugget 作 σ² 的估计（仍是上界，但比方法一紧）；分 ROI、分分量检查稳定性与各向异性。
   若要给出置信区间，可考虑 Liu et al. 2014 的「高斯过程 + 独立读片误差」分层模型。
3. **补一个小的重复标注子集作锚点**：随机抽 50–100 个点（跨 ROI、跨纹理），隔数周盲标一次；条件允许
   再请第二人标同一批。用它直接估计 σ（及光学、SAR 两侧各自的点击误差，若两侧分开重标），
   并检验第 2 条的 nugget 偏高多少。这是唯一不依赖残余错位结构假设的方法。
4. **自动匹配只作交叉检查**：用多模态模板匹配在人工点附近搜索，看人工–自动差的分布与粗差；
   若要用 triple collocation，需两个原理不同的匹配器，并警惕与人工误差的相关性。
5. **报告方式**：给出 σ 的估计区间（下界来自重复标注、上界来自拟合残差/nugget），说明假设；
   把 σ_e 写进评测指标的解读（均方误差按平方和扣除、阈值型指标注明下限）。

## 附：本次未能核实的内容

- OS-Dataset、SOPatch、WHU-OPT-SAR、SARptical 论文全文中是否有配准精度数值（付费墙或未读全文）。
- 月面（Mini-RF 与 CE-2）场景下人工点击误差的已发表数值：未找到。
