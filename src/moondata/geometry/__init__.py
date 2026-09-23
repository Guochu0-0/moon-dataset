"""几何层：纯 numpy，不依赖任何地理库——变换估计、网格规划、坐标换算。

这是测试性价比最高的接缝：输入输出都是数组与数值，无 IO，可在没有 GDAL 的机器上
完整跑通。窗口生成见 issue #9。
"""

from moondata.geometry.grid import LonLatBox, PixelGrid, overlap_region, reference_tile
from moondata.geometry.transforms import TransformModel, apply_transform, estimate_transform

__all__ = [
    "LonLatBox",
    "PixelGrid",
    "TransformModel",
    "apply_transform",
    "estimate_transform",
    "overlap_region",
    "reference_tile",
]
