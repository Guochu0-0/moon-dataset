"""数据指纹与统计快照。

**统计快照**是从真实数据扫描出来的统计量文件，文档只读它、不读影像，因此移动硬盘
没插时文档照样渲染。快照携带生成时间与一枚**数据指纹**。

指纹刻画的是数据根的**目录形态**——相对路径与文件大小——不是像素内容。955 GB 逐字节
哈希不现实，而「少了一个 ROI」「patch 数量变了」「某个文件被截断」这类真正会让快照
失效的变化都体现在形态上。同一批数据换一块盘、换一个挂载点，指纹不变。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from moondata.errors import DataRootUnavailable, SnapshotUnreadable


@dataclass(frozen=True)
class Fingerprint:
    digest: str
    """`sha256:` 前缀的十六进制摘要。"""
    file_count: int
    total_bytes: int


@dataclass(frozen=True)
class Snapshot:
    generated_at: str
    fingerprint: Fingerprint


def compute_fingerprint(root: Path) -> Fingerprint:
    """遍历 `root` 下全部文件，按 `相对路径 + 大小` 计算指纹。只列目录，不读内容。"""
    root = Path(root)
    if not root.is_dir():
        raise DataRootUnavailable(f"数据根不可达：{root}")

    entries: list[tuple[str, int]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except OSError:  # 盘在遍历途中被拔掉，或权限不足
            raise DataRootUnavailable(f"数据根读到一半读不动了：{path}") from None
        entries.append((path.relative_to(root).as_posix(), size))

    entries.sort()
    digest = hashlib.sha256()
    for relpath, size in entries:
        digest.update(f"{relpath}\0{size}\n".encode("utf-8"))
    return Fingerprint(
        digest=f"sha256:{digest.hexdigest()}",
        file_count=len(entries),
        total_bytes=sum(size for _, size in entries),
    )


def load_snapshot(path: Path) -> Snapshot | None:
    """读取统计快照。**快照不存在返回 None**——那是「还没生成」，不是错误。"""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        fingerprint = document["fingerprint"]
        return Snapshot(
            generated_at=document["generated_at"],
            fingerprint=Fingerprint(
                digest=fingerprint["digest"],
                file_count=fingerprint["file_count"],
                total_bytes=fingerprint["total_bytes"],
            ),
        )
    except (json.JSONDecodeError, KeyError, TypeError, OSError) as error:
        raise SnapshotUnreadable(f"统计快照读不动：{path}（{error}）") from error
