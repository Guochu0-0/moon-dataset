"""自检：数据根解析到哪个路径、该路径是否可达、与统计快照的指纹是否一致。

回答的是「数据在不在、在哪、对不对」这一个问题，所以三件事一次报全，而不是让人
从别的命令的报错信息里反推。数据根不可达时不抛栈，照常出报告——只是把指纹一项
标为未比对。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from moondata.config import CONFIG_FILENAME, ENV_VAR, Config, DataRootSource
from moondata.errors import DataRootUnavailable, SnapshotUnreadable
from moondata.snapshot import Fingerprint, Snapshot, compute_fingerprint, load_snapshot


class Reachability(Enum):
    REACHABLE = "可达"
    MISSING = "不可达（路径不存在，移动硬盘没插？）"
    NOT_A_DIRECTORY = "不可达（该路径不是目录）"
    UNSET = "未设置"


class SnapshotCheck(Enum):
    MATCH = "一致"
    MISMATCH = "不一致"
    NO_SNAPSHOT = "统计快照尚未生成"
    SKIPPED = "未比对（数据根不可达）"
    UNREADABLE = "统计快照读不动"


@dataclass(frozen=True)
class DoctorReport:
    data_root: Path | None
    data_root_source: DataRootSource
    data_root_origin: str | None
    reachability: Reachability
    snapshot_path: Path
    snapshot: Snapshot | None
    snapshot_check: SnapshotCheck
    actual_fingerprint: Fingerprint | None
    note: str | None = None

    @property
    def ok(self) -> bool:
        """数据根可达、且没有查出指纹不一致或快照损坏。快照尚未生成不算失败。"""
        return self.reachability is Reachability.REACHABLE and self.snapshot_check in (
            SnapshotCheck.MATCH,
            SnapshotCheck.NO_SNAPSHOT,
        )


def run_doctor(config: Config) -> DoctorReport:
    reachability = _probe(config.data_root)

    try:
        snapshot = load_snapshot(config.snapshot_path)
    except SnapshotUnreadable as error:
        return DoctorReport(
            data_root=config.data_root,
            data_root_source=config.data_root_source,
            data_root_origin=config.data_root_origin,
            reachability=reachability,
            snapshot_path=config.snapshot_path,
            snapshot=None,
            snapshot_check=SnapshotCheck.UNREADABLE,
            actual_fingerprint=None,
            note=str(error),
        )

    check, actual, note = _compare(config.data_root, reachability, snapshot)
    return DoctorReport(
        data_root=config.data_root,
        data_root_source=config.data_root_source,
        data_root_origin=config.data_root_origin,
        reachability=reachability,
        snapshot_path=config.snapshot_path,
        snapshot=snapshot,
        snapshot_check=check,
        actual_fingerprint=actual,
        note=note,
    )


def _probe(data_root: Path | None) -> Reachability:
    if data_root is None:
        return Reachability.UNSET
    if data_root.is_dir():
        return Reachability.REACHABLE
    if data_root.exists():
        return Reachability.NOT_A_DIRECTORY
    return Reachability.MISSING


def _compare(
    data_root: Path | None, reachability: Reachability, snapshot: Snapshot | None
) -> tuple[SnapshotCheck, Fingerprint | None, str | None]:
    if snapshot is None:
        return SnapshotCheck.NO_SNAPSHOT, None, None
    if reachability is not Reachability.REACHABLE or data_root is None:
        return SnapshotCheck.SKIPPED, None, None
    try:
        actual = compute_fingerprint(data_root)
    except DataRootUnavailable as error:
        return SnapshotCheck.SKIPPED, None, str(error)
    check = (
        SnapshotCheck.MATCH
        if actual == snapshot.fingerprint
        else SnapshotCheck.MISMATCH
    )
    return check, actual, None


def format_report(report: DoctorReport) -> str:
    lines = [
        f"数据根    {report.data_root if report.data_root else '（未设置）'}",
        f"来源      {report.data_root_source.value}"
        + (
            f" → {report.data_root_origin}"
            if report.data_root_origin
            and report.data_root_origin != report.data_root_source.value
            else ""
        ),
        f"可达性    {report.reachability.value}",
        f"统计快照  {report.snapshot_path}",
        f"指纹      {report.snapshot_check.value}",
    ]

    if report.reachability is Reachability.UNSET:
        lines.append(
            f"          设置办法：导出环境变量 {ENV_VAR}，"
            f"或在仓库根的 {CONFIG_FILENAME} 中写 [data] root"
            f"（可从 {CONFIG_FILENAME}.example 复制）"
        )

    if report.snapshot is not None:
        lines.append(f"          快照生成于 {report.snapshot.generated_at}")
        lines.append(f"          快照：{_describe(report.snapshot.fingerprint)}")
    if report.actual_fingerprint is not None:
        lines.append(f"          实测：{_describe(report.actual_fingerprint)}")
    if report.snapshot_check is SnapshotCheck.MISMATCH:
        lines.append("          数据与快照对不上：要么数据变了，要么快照过期了，先查清哪一边。")
    if report.note:
        lines.append(f"          {report.note}")

    return "\n".join(lines)


def _describe(fingerprint: Fingerprint) -> str:
    return (
        f"{fingerprint.digest}"
        f"（{fingerprint.file_count} 个文件，{fingerprint.total_bytes} 字节）"
    )
