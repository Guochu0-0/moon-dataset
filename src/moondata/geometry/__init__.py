"""几何层：纯 numpy，不依赖任何地理库——变换估计、网格规划、坐标换算。

这是测试性价比最高的接缝：输入输出都是数组与数值，无 IO，可在没有 GDAL 的机器上
完整跑通。
"""

from moondata.geometry.grid import LonLatBox, PixelGrid, overlap_region, reference_tile
from moondata.geometry.transforms import TransformModel, apply_transform, estimate_transform
from moondata.geometry.windows import (
    MIN_OVERLAP,
    WindowPair,
    WindowPlan,
    grid_windows,
    plan_windows,
    sar_window,
)

__all__ = [
    "MIN_OVERLAP",
    "LonLatBox",
    "PixelGrid",
    "TransformModel",
    "WindowPair",
    "WindowPlan",
    "apply_transform",
    "estimate_transform",
    "grid_windows",
    "overlap_region",
    "plan_windows",
    "reference_tile",
    "sar_window",
]
