"""文档页从统计快照取值、把数字排成文字的工具。

文档中的每个统计数字都从快照行内取值（`{python} ...`），这里的函数负责「取」与「排」。
它们放在包里而不是 .qmd 的代码块里，是为了能被单测——排版错一位小数，
和手写错一个数字是同一种错。

**快照缺失或尚未扫过统计量时直接报错**，让 `quarto render` 失败：一页数字全空的
文档悄悄被提交出去，比构建失败糟糕得多。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np

from moondata.config import SNAPSHOT_RELPATH, find_repo_root
from moondata.errors import SnapshotUnreadable
from moondata.snapshot import Snapshot, load_snapshot

_HINT = "接上数据盘后运行 `moondata scan` 生成它。"


def load_stats_snapshot(start: Path | None = None) -> Snapshot:
    """从 `start`（默认当前目录，即 Quarto 执行页面代码的目录）向上找仓库根，读快照。

    不走 `load_config`：文档渲染与数据根无关，不该因为本机 `moondata.toml` 写坏了而失败。
    """
    start = Path(start) if start is not None else Path.cwd()
    path = (find_repo_root(start) or start) / SNAPSHOT_RELPATH
    snapshot = load_snapshot(path)
    if snapshot is None:
        raise SnapshotUnreadable(f"统计快照不存在：{path}。{_HINT}")
    if not snapshot.stats:
        raise SnapshotUnreadable(f"统计快照里只有指纹、没有统计量：{path}。{_HINT}")
    return snapshot


def num(value: int | float) -> str:
    """整数加千分位；浮点保留四位有效数字——SAR 的后向散射值再多写几位也没有意义。"""
    if isinstance(value, (int, np.integer)):
        return f"{int(value):,}"
    return f"{float(value):.4g}"


def pct(part: int, whole: int, digits: int = 1) -> str:
    return f"{part / whole:.{digits}%}" if whole else "—"


def size(nbytes: int) -> str:
    if nbytes < 1024:
        return f"{nbytes} B"
    value = nbytes / 1024
    for unit in ("KiB", "MiB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


def dtype_label(dtype: str) -> str:
    kind = np.dtype(dtype)
    names = {"u": "无符号整型", "i": "有符号整型", "f": "浮点"}
    return f"{kind.itemsize * 8} 位{names[kind.kind]}（`{dtype}`）"


def table(
    headers: Sequence[str], rows: Sequence[Sequence[object]], align: str | None = None
) -> str:
    """Markdown 管道表格。`align` 逐列给 `l`/`r`，不给则用默认对齐。"""
    rule = {"l": ":---", "r": "---:"}
    separator = [rule[a] for a in align] if align else ["---"] * len(headers)
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(separator) + "|",
    ]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)
