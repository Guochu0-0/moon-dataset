"""本包对外抛出的错误。

命令行把它们渲染成一行中文说明并以退出码 1 结束，**不打印 traceback**：
移动硬盘没插是日常状态，不是程序缺陷。
"""


class MoonDataError(Exception):
    """本包所有预期内错误的基类。命令行捕获它，其余异常照常向上抛。"""


class DataRootUnavailable(MoonDataError):
    """数据根没配置、不存在、或不是一个目录——凡需读取影像的操作都走这条路。"""


class ConfigUnreadable(MoonDataError):
    """`moondata.toml` 存在但读不动（语法错、类型错）。"""


class SnapshotUnreadable(MoonDataError):
    """统计快照存在但读不动。区别于「快照尚未生成」，后者返回 None。"""


class TiffUnreadable(MoonDataError):
    """TIFF 文件坏了，或用了 `moondata.tiff` 不支持的编码方式。消息里带文件路径。"""


class StatsUnavailable(MoonDataError):
    """扫描产出统计量时遇到读不动或认不出的输入（产物目录、窗口清单、删除清单、标签文件）。"""


class MetadataUnreadable(MoonDataError):
    """Mini-RF 逐 ROI 元数据表或 ROI 已知问题清单读不动、认不出。"""


class ThumbnailUnavailable(MoonDataError):
    """对齐影像读得动、但画不出缩略图（例如整幅没有一个有效像素）。"""


class RepoRootNotFound(MoonDataError):
    """命令的输入或输出在仓库里（元数据表、档案页），却不是在仓库内运行的。"""


class DocSiteUnpatchable(MoonDataError):
    """文档站渲染完了，但改不成离线可读的样子（多半是 Quarto 升级改了产物结构）。

    宁可让构建失败：这一步的每一处失灵在成品里都是静默的——搜索框不出结果、
    页内目录不跟随——提交出去没人会发现。
    """


class InsufficientPoints(MoonDataError):
    """同名点数少于所选变换模型的最低要求。宁可报错，也不悄悄换一个自由度更低的模型。"""


class DegeneratePoints(MoonDataError):
    """同名点够数但退化（全部重合、全部共线），解不唯一。"""


class NoOverlap(MoonDataError):
    """光学与 SAR 在月面上没有公共范围——对不齐，也就无从切 patch。"""


class TiePointsUnreadable(MoonDataError):
    """对齐控制点文件找不到或认不出。消息里带 ROI 与文件路径。"""


class WindowManifestUnreadable(MoonDataError):
    """窗口清单（`data/windows/*.json`）读不动或结构认不出。"""


class GeoLibraryUnavailable(MoonDataError):
    """要读写影像，但当前环境没装 GDAL/pyproj（多半是用了文档档环境）。"""


class RasterUnreadable(MoonDataError):
    """影像打不开、没有坐标系、或不是北向上的正方形像元。消息里带文件路径。"""


class GridMismatch(MoonDataError):
    """写出的对齐影像没有落在规划的像素网格上。"""


class RawInputsUnavailable(MoonDataError):
    """数据根下某个 ROI 的原始输入（CE-2 分幅、Mini-RF 条带）缺失或认不出。"""
