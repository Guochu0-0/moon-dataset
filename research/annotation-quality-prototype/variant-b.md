# 标注质量

<figure markdown="1" class="lead">
<img src="../assets/aq/compare.svg" alt="三种方法估出的标注误差">
<figcaption>一对点（光学、SAR 各点一次）每个坐标轴上的标注误差。灰条是上界，蓝点是直接测量；须线是各方法内部的取值范围。</figcaption>
</figure>

评测真值点的标注误差约 **1 像素**（7.5 m）。两种方法只能给上界，一种方法直接测得；三个数各自成立，不合成总数。

## 仿射拟合残差：1.2 像素，上界

每个 patch 内拟合一个仿射，拟合不掉的散布包含标注误差，也包含比仿射复杂的真实错位。

{{affine-outline}}

## 变异函数：0.95 像素，上界

相距越近的两个点，真实错位越接近，读数之差越只剩标注误差。把「半个均方差」对点间距作图，外推到间距为 0，截距就是标注误差的方差。

<figure markdown="1">
<img src="../assets/aq/toy.svg" alt="一维例子：错位场、带误差的读数与变异函数">
<figcaption>一维例子。左：错位场 f(s)（灰线）与标注读数（黑点），σ = 1。右：γ(h) 外推到 h = 0 得到 σ²。</figcaption>
</figure>

<details markdown="1">
<summary>例子的完整说明</summary>

{{variogram-example}}

</details>

<details markdown="1">
<summary>公式与代码</summary>

{{variogram-formula}}

{{variogram-code}}

</details>

<details markdown="1" open>
<summary>月球数据</summary>

{{variogram-moon}}

</details>

## 无意重标：1.0 像素，直接测量

同一个地物被独立点了两次，两次读数之差只来自标注误差，不需要对错位的形状作任何假设。

{{repeat-outline}}
