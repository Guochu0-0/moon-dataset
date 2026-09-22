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


class NotImplementedYet(MoonDataError):
    """子命令的骨架已就位、实现留待后续 issue。带上 issue 号，别让人猜。"""


class DocSiteUnpatchable(MoonDataError):
    """文档站渲染完了，但改不成离线可读的样子（多半是 Quarto 升级改了产物结构）。

    宁可让构建失败：这一步的每一处失灵在成品里都是静默的——搜索框不出结果、
    页内目录不跟随——提交出去没人会发现。
    """
