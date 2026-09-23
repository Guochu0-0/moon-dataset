"""Mini-RF 逐 ROI 元数据表（`data/metadata/minirf_metadata.csv`）的读取。

表里的 ROI 名不补零（`ROI_6`，与 `raw/ROI_6/`、对齐控制点目录一致），patch 产物目录
却补零到三位（`ROI_006`）。两套写法指同一个 ROI，**本包对外一律用补零的写法**，
原名留在 `raw_name` 里，只在拼 `raw/` 下的路径时用。

列不做类型转换、原样保留为字符串：这张表的用途是被原样展示，而「51.20」被转成
浮点再写回去就成了「51.2」——展示出来的就不再是表里写的那个值了。
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from moondata.errors import MetadataUnreadable
from moondata.stats import SPLITS

ROI_COLUMN = "ROI"
SPLIT_COLUMN = "划分"
_ROI_NAME = re.compile(r"ROI_(\d+)")


@dataclass(frozen=True)
class MetadataRow:
    roi: str
    """补零写法，如 `ROI_006`。"""
    raw_name: str
    """表里的原名，如 `ROI_6`，也是 `raw/` 下的目录名。"""
    split: str
    fields: dict[str, str]
    """整行，按文件中的列序。"""


def padded_roi(name: str) -> str:
    match = _ROI_NAME.fullmatch(name.strip())
    if match is None:
        raise MetadataUnreadable(f"认不出的 ROI 名：{name!r}")
    return f"ROI_{int(match.group(1)):03d}"



def raw_roi_name(name: str) -> str:
    """不补零的写法（`ROI_6`）：`raw/` 与对齐控制点目录都按它命名。"""
    return f"ROI_{int(padded_roi(name)[4:])}"

def dataset_rows(rows: list[MetadataRow]) -> list[MetadataRow]:
    """属于数据集的行。表里还留着已删除 ROI 的行（ROI_60），它的划分一栏写的是删除原因。"""
    return [row for row in rows if row.split in SPLITS]


def load_metadata(path: Path) -> list[MetadataRow]:
    """按 ROI 编号排序返回。"""
    try:
        # utf-8-sig：真实文件带 BOM，否则第一个列名会变成 '﻿ROI'
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            records = list(csv.DictReader(stream))
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        raise MetadataUnreadable(f"元数据表读不动：{path}（{error}）") from error

    rows = []
    for record in records:
        try:
            name, split = record[ROI_COLUMN], record[SPLIT_COLUMN]
        except KeyError as error:
            raise MetadataUnreadable(f"元数据表缺少列 {error}：{path}") from error
        try:
            roi = padded_roi(name)
        except MetadataUnreadable as error:
            raise MetadataUnreadable(f"{error}（{path}）") from error
        rows.append(MetadataRow(roi, name.strip(), split, dict(record)))
    return sorted(rows, key=lambda row: row.roi)
