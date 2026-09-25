# 标注质量

评测真值点的标注误差约 1 像素（7.5 m），指一对点在光学、SAR 上各点一次、两次点击合在一起后，每个坐标轴上的标准差。

| | 仿射拟合残差 | 变异函数 | 无意重标 |
|---|---|---|---|
| 看的是 | 一个 patch 内拟合仿射后剩下的散布 | 相距很近的两点读数之差 | 同一地物两次独立标注之差 |
| 假设 | 错位在 patch 内是仿射 | 错位随距离平滑变化 | 两次标注同样准、相互独立 |
| 多算进去的 | 比仿射复杂的真实错位 | 小于约 20 像素尺度上的真实错位 | 无 |
| 结果（像素） | 1.2，上界 | 0.95，上界 | 1.0，直接测量 |

<div class="tabs" markdown="1">
<div class="tabbar"><button data-tab="t1">仿射拟合残差</button><button data-tab="t2" class="on">变异函数</button><button data-tab="t3">无意重标</button></div>

<section id="t1" markdown="1">

{{affine-outline}}

</section>

<section id="t2" class="on" markdown="1">

#### 例子

{{variogram-example}}

#### 公式与代码

{{variogram-formula}}

```python
i, j = np.triu_indices(len(r), k=1)                      # 同一 ROI 内的全部点对
h, half_sq = np.hypot(*(xy[i] - xy[j]).T), 0.5 * (r[i] - r[j]) ** 2
# 按 h 分档求 half_sq 的平均得 γ(h)；在最短几档上拟合直线，截距即 nugget
```

完整代码：`research/annotation-error/estimate.py` 的 `variogram()` 与 `nugget()`。

#### 月球数据

{{variogram-moon}}

</section>

<section id="t3" markdown="1">

{{repeat-outline}}

</section>
</div>
