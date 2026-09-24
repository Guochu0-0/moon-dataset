# 制作流程

<div class="flow">
<svg viewBox="0 0 1100 280" role="img" aria-label="流程图：原始影像经重叠区提取得到重叠区影像，经标控制点得到控制点，经协同切片得到 patch 对">
<defs><marker id="flow-head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z"/></marker></defs>
<a href="data/sources.md"><g class="dn">
<rect x="20" y="70" width="60" height="60" class="opt"/><rect x="20" y="130" width="60" height="60" class="opt"/>
<polygon points="100,62 124,58 150,196 126,200" class="sar"/>
<text x="20" y="232" class="t">原始影像</text></g></a>
<text x="20" y="252" class="s"><a href="data/sources.md">出处</a> · <a href="data/organization.md">组织</a></text>
<a href="#重叠区提取"><g class="op">
<path d="M170 130 H 316" marker-end="url(#flow-head)"/>
<text x="243" y="116" text-anchor="middle">重叠区提取</text><text x="243" y="152" text-anchor="middle" class="m">01_overlap.py</text></g></a>
<g class="dn">
<rect x="330" y="60" width="44" height="140" class="opt"/><rect x="384" y="60" width="44" height="140" class="blank"/>
<polygon points="392,60 414,60 424,200 402,200" class="sar"/>
<text x="330" y="232" class="t">重叠区影像</text><text x="330" y="252" class="s">同一网格，7.5 m</text></g>
<a href="#标控制点"><g class="op manual">
<path d="M446 130 H 616" marker-end="url(#flow-head)"/>
<text x="531" y="116" text-anchor="middle">标控制点</text><text x="531" y="152" text-anchor="middle" class="m">人工，ENVI</text></g></a>
<g class="dn">
<rect x="630" y="60" width="44" height="140" class="opt"/><rect x="684" y="60" width="44" height="140" class="blank"/>
<polygon points="692,60 714,60 724,200 702,200" class="sar"/>
<path d="M640 80h10M645 75v10M655 130h10M660 125v10M643 180h10M648 175v10M699 82h10M704 77v10M707 132h10M712 127v10M711 182h10M716 177v10" class="cross"/>
<text x="630" y="232" class="t">控制点</text><text x="630" y="252" class="s">光学–SAR 同名点</text></g>
<a href="#协同切片"><g class="op">
<path d="M746 130 H 916" marker-end="url(#flow-head)"/>
<text x="831" y="116" text-anchor="middle">协同切片</text><text x="831" y="152" text-anchor="middle" class="m">02_patches.py</text></g></a>
<a href="data/statistics.md"><g class="dn">
<rect x="930" y="80" width="56" height="56" class="opt"/><rect x="939" y="89" width="56" height="56" class="sarp"/>
<rect x="948" y="98" width="56" height="56" class="opt"/><rect x="957" y="107" width="56" height="56" class="sarp"/>
<rect x="966" y="116" width="56" height="56" class="opt"/><rect x="975" y="125" width="56" height="56" class="sarp"/>
<text x="930" y="232" class="t">patch 对</text><text x="930" y="252" class="s">512 × 512</text></g></a>
</svg>
</div>

## 重叠区提取

`scripts/01_overlap.py`
{: .script }

**输入**　CE-2 DOM 分幅、Mini-RF SAR 条带（[出处](data/sources.md)、[组织](data/organization.md#目录)）
{: .io }

**输出**　重叠区影像 `opt.tif`、`sar.tif`，`work/01_overlap/ROI_xxx/`
{: .io }

1. 求光学与 SAR 的公共覆盖区。
2. 统一坐标系，cubic 重采样到 7.5 m 的同一网格。

<!-- 流程配图 images：ROI_054 重叠区影像的一段（光学行 9216–14848），左光学、右 SAR。 -->

## 标控制点

人工，ENVI
{: .script .manual }

**输入**　重叠区影像
{: .io }

**输出**　控制点 `data/tie-points/ROI_xxx.pts`
{: .io }

### 标注规程

| 项目 | 做法 |
|---|---|
| 软件 | ENVI |
| 标注影像 | 重叠区影像 |
| 数量 | 每个 ROI 约 30 对；最多 150 对，最少 19 对 |
| 分布 | 沿条带从上到下均匀覆盖 |
| 选点 | 在两幅影像中找到对应的小陨石坑，取坑中心 |

ROI_073 的控制点最初误标在 ROI_074 的影像上，已重标（30 对），并按新控制点重新切片、编号。

<!-- 流程配图 points：同一段上的控制点，同号为一对。 -->

## 协同切片

`scripts/02_patches.py`
{: .script }

**输入**　重叠区影像、控制点
{: .io }

**输出**　patch 对 `work/02_patches/{Train,Val,Test}/ROI_xxx/{Optical,SAR}/`；仿射矩阵与窗口列表（JSON）
{: .io }

1. 由控制点最小二乘解算全局仿射（光学 → SAR）。
2. 在光学上以 512 × 512 滑窗，步长 512。
3. 窗口四角经仿射映射到 SAR。
4. 剔除出界、重叠比低于 70%、含 nodata 的窗口。
5. 先行后列编号，从 `patch_0` 起。
6. 切片。

<!-- 流程配图 windows：同一段，逐步点开。斜线格为剔除的窗口；指向一个窗口，另一侧的对应窗口同时高亮。 -->
