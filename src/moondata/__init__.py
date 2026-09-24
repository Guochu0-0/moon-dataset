"""moondata —— 从 CE-2 7 m DOM 与 Mini-RF SAR 的原始输入做出配准数据集。

流程是两个编号脚本，中间夹一个人工步骤：

    scripts/01_overlap.py   重叠区提取
    （人工：在重叠区影像上标控制点，结果在 data/tie-points/）
    scripts/02_patches.py   协同切片

脚本只做编排，逻辑在本包的四个模块里：

    config     读 config.toml
    sources    定位原始输入
    geometry   纯 numpy：网格、铺窗、仿射、SAR 窗口映射、剔除与编号
    raster     唯一依赖 GDAL/pyproj 的地方

`geometry` 与 `raster` 的分界是有意画的：几何是全部窗口位置与编号的来源，把它做成
无 IO 的纯函数才能被单测完整覆盖。
"""

from __future__ import annotations

__all__ = ["__version__"]
__version__ = "0.2.0"
