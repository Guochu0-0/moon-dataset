"""本包对外抛出的错误。

两个编号脚本把它们渲染成一行中文并以退出码 1 结束，**不打印 traceback**：
移动硬盘没插、某个 ROI 的输入缺文件，都是日常状态，不是程序缺陷。
"""

from __future__ import annotations


class MoonDataError(Exception):
    """本包所有预期内错误的基类。脚本捕获它，其余异常照常向上抛。"""


class ConfigUnreadable(MoonDataError):
    """`config.toml` 找不到、语法错、或某一项的类型不对。"""


class DataRootUnavailable(MoonDataError):
    """`config.toml` 里的数据根不存在或不是一个目录。"""


class RawInputsUnavailable(MoonDataError):
    """数据根下某个 ROI 的原始输入（CE-2 分幅、Mini-RF 条带）缺失或认不出。"""


class OverlapImagesMissing(MoonDataError):
    """要切 patch，但这个 ROI 的重叠区影像不在——第一步还没跑。"""


class MetadataUnreadable(MoonDataError):
    """元数据表读不动，或 ROI 名、分幅名、产品 ID 认不出。"""


class TiePointsUnreadable(MoonDataError):
    """控制点文件找不到或认不出。消息里带 ROI 与文件路径。"""


class NoOverlap(MoonDataError):
    """光学与 SAR 在月面上没有公共范围——无从切 patch。"""


class DegeneratePoints(MoonDataError):
    """控制点退化（全部重合、全部共线），仿射解不唯一。宁可报错，也不悄悄降一档模型。"""


class InsufficientPoints(MoonDataError):
    """控制点少于仿射变换所需的 3 对。"""


class RasterUnreadable(MoonDataError):
    """影像打不开、没有坐标系、或不是北向上的正方形像元。消息里带文件路径。"""


class GridMismatch(MoonDataError):
    """写出的重叠区影像没有落在规划的像素网格上。"""
