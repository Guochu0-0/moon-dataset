"""两个脚本的输入从哪来、怎么读。

- 数据根下的原始输入：一个 ROI 的 CE-2 分幅与 Mini-RF 条带各是哪些文件；
- 仓库里的控制点 `.pts`；
- 元数据表给出的 ROI 清单与划分（不带参数跑全部 ROI、产物该放哪个划分下，都要它）；
- ROI 名两种写法之间的换算。

不 import 地理库：这里只做查表、正则、路径与文本解析。分幅头里的坐标系怎么读、
怎么纠正，在 `moondata.raster`。
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from moondata.errors import MetadataUnreadable, RawInputsUnavailable, TiePointsUnreadable

METADATA_RELPATH = Path("data") / "metadata" / "minirf_metadata.csv"
TIE_POINTS_RELDIR = Path("data") / "tie-points"
RAW_DIRNAME = "raw"
_ROI_NAME = re.compile(r"ROI_(\d+)")

CE2_TILE = re.compile(r"^CE2_GRAS_DOM_07m_([A-L][12]\d{2})_\d{2}[NS]\d{3}[EW]_A\.tif$")
"""CE-2 7 m DOM 的墨卡托分幅文件名，捕获分幅号（如 `K236`）。

`ce2/` 下不止分幅：历史上的镶嵌脚本往这里写过 `merged.tif`，把它当分幅就又多镶嵌、
多插值一次；极区分幅（`N0nn`、`S0nn`，极射赤面投影）本数据集没有用到，也不匹配。
"""

MINIRF_PRODUCT = re.compile(r"^lsz_\d{5}_\dcd_[eo]ku_\d{2}[ns]\d{3}_v\d\.tif$")
"""Mini-RF 条带的产品 ID 文件名。产品 ID 的逐段含义写在文档站，代码只要认出文件。

只在 `minirf/` 下有多个 `.tif` 时用来挑：ROI_054 的目录里既有产品 ID 命名的条带，
又有一份同样大小的 `sar.tif` 副本，当年按文件名排序取到的是前者。其余 ROI 有的只有
`sar.tif`，那就用它。
"""

LAT_TS_CORRECTIONS = {"E215": 35.0, "E218": 35.0, "E219": 35.0, "I219": -21.0, "I236": -21.0}
"""分幅号 → 正确的墨卡托标准纬线（度）。

这 5 幅的头里把 `lat_ts` 写成了相邻纬度带的值（E 带写成 21、I 带写成 −35），像素与
geotransform 都没动，于是整幅图被放到几度之外，而且不报任何错。**只在读取时经临时
VRT 纠正，源文件一个字节都不改**（`raster.read_footprint`）。

只在这张表里的分幅上纠正：其余分幅头里的 `lat_ts` 有北半球写成负值的，那不是错——
墨卡托只取标准纬线的余弦。
"""


def padded_roi(name: str) -> str:
    """补零写法 `ROI_006`：本包对外一律用它。"""
    match = _ROI_NAME.fullmatch(name.strip())
    if match is None:
        raise MetadataUnreadable(f"认不出的 ROI 名：{name!r}")
    return f"ROI_{int(match.group(1)):03d}"


def raw_roi_name(name: str) -> str:
    """不补零的写法 `ROI_6`：数据根下 `raw/` 与元数据表都按它命名。"""
    return f"ROI_{int(padded_roi(name)[4:])}"


@dataclass(frozen=True)
class RoiRow:
    roi: str
    """补零写法。"""
    split: str


def load_roi_table(repo_root: Path) -> list[RoiRow]:
    """元数据表里的 67 个 ROI，按编号升序。表里只有数据集的 ROI。"""
    path = repo_root / METADATA_RELPATH
    try:
        rows = [RoiRow(roi, record["划分"].strip()) for roi, record in load_metadata(repo_root).items()]
    except KeyError as error:
        raise MetadataUnreadable(f"元数据表缺少列 {error}：{path}") from error
    return sorted(rows, key=lambda row: row.roi)


def load_metadata(repo_root: Path) -> dict[str, dict[str, str]]:
    """元数据表的全部列，键是补零写法的 ROI 名，按编号升序。"""
    path = repo_root / METADATA_RELPATH
    try:
        # utf-8-sig：文件带 BOM，否则第一个列名会变成 '﻿ROI'
        with path.open(encoding="utf-8-sig", newline="") as stream:
            records = list(csv.DictReader(stream))
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        raise MetadataUnreadable(f"元数据表读不动：{path}（{error}）") from error
    try:
        return dict(sorted(((padded_roi(r["ROI"]), r) for r in records), key=lambda item: item[0]))
    except KeyError as error:
        raise MetadataUnreadable(f"元数据表缺少列 {error}：{path}") from error


@dataclass(frozen=True)
class RoiInputs:
    roi: str
    """补零写法。"""
    optical_tiles: list[Path]
    sar: Path


def locate_inputs(data_root: Path, roi: str) -> RoiInputs:
    """一个 ROI 的原始输入：`raw/ROI_<n>/ce2/` 下的分幅与 `raw/ROI_<n>/minirf/` 下的条带。"""
    roi_dir = data_root / RAW_DIRNAME / raw_roi_name(roi)
    tiles = sorted(p for p in (roi_dir / "ce2").glob("*.tif") if CE2_TILE.match(p.name))
    if not tiles:
        raise RawInputsUnavailable(f"{roi_dir / 'ce2'} 下没有 CE-2 分幅")
    strips = sorted((roi_dir / "minirf").glob("*.tif"))
    if len(strips) > 1:
        strips = [p for p in strips if MINIRF_PRODUCT.match(p.name)]
    if len(strips) != 1:
        raise RawInputsUnavailable(
            f"{roi_dir / 'minirf'} 下应恰有一条 Mini-RF 条带，实际认出 {len(strips)} 条"
        )
    return RoiInputs(padded_roi(roi), tiles, strips[0])


DATASET_DIRNAME = "Processed_Data"
GROUND_TRUTH_RELDIR = Path("data") / "ground-truth"
ASSETS_RELDIR = Path("docs") / "assets"
"""文档站素材：`scripts/make_assets.py` 写、`scripts/build_site.py` 读。"""
FACTS_NAME = "roi-facts.json"
SAMPLES_NAME = "samples.json"
OVERLAY_NAME = "overlay.json"
PROCESS_NAME = "process.json"


def ground_truth_files(repo_root: Path, split: str, roi: str) -> list[Path]:
    """仓库里一个 ROI 的评测真值点文件，按 patch 编号升序。训练集没有。"""
    directory = repo_root / GROUND_TRUTH_RELDIR / split / padded_roi(roi)
    return sorted(directory.glob("patch_*.txt"), key=lambda p: int(p.stem.split("_")[1]))


def ground_truth_file(repo_root: Path, split: str, roi: str, patch: int) -> Path:
    return repo_root / GROUND_TRUTH_RELDIR / split / padded_roi(roi) / f"patch_{patch}.txt"


def dataset_patch_dir(data_root: Path, split: str, roi: str) -> Path:
    """数据盘上现有数据集里一个 ROI 的 patch 对：其下 `Optical/`、`SAR/`。"""
    return data_root / DATASET_DIRNAME / split / padded_roi(roi)


def dataset_overlap_images(data_root: Path, roi: str) -> tuple[Path, Path]:
    """数据盘上现有数据集的一对重叠区影像 (光学, SAR)，patch 就是从它们上切的。
    当年的脚本把它们写在原始输入旁边的 `cropped/ce2/` 下。"""
    base = data_root / RAW_DIRNAME / raw_roi_name(roi) / "cropped" / "ce2"
    return base / "opt.tif", base / "sar.tif"


def corrected_lat_ts(tile_path: Path) -> float | None:
    """该分幅要不要纠正 `lat_ts`；不在纠正表里就返回 `None`。"""
    match = CE2_TILE.match(tile_path.name)
    return LAT_TS_CORRECTIONS.get(match.group(1)) if match else None


# ---------------------------------------------------------------------------
# 控制点：人工在重叠区影像上标的光学–SAR 同名点。
#
# `data/tie-points/ROI_<nnn>.pts` 是 ENVI Image-to-Image Tie Points 的导出，每 ROI 一个
# 文件、约 30 对点。它在仓库里，所以解算变换这一步不接盘也能跑。
#
# `.pts` 的 y **不取负**，读进来就是向下为正的行号；patch 旁的评测真值点才取负，
# 两者不要混。


def load_tie_points(repo_root: Path, roi: str) -> tuple[np.ndarray, np.ndarray]:
    """返回 (光学, SAR) 两组 `(n, 2)` 的 (列, 行)。"""
    path = repo_root / TIE_POINTS_RELDIR / f"{padded_roi(roi)}.pts"
    if not path.is_file():
        raise TiePointsUnreadable(f"{padded_roi(roi)} 没有控制点：{path} 不存在")
    # 头部注释里的文件路径是 ENVI 按系统代码页写的（中文 Windows 上是 GBK），按 UTF-8
    # 硬解码会在第一行就失败。数据行是纯 ASCII，注释行反正丢弃，所以降级解码即可。
    text = path.read_text(encoding="utf-8", errors="replace")
    rows = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        try:
            values = [float(token) for token in line.split()]
        except ValueError:
            raise TiePointsUnreadable(f"{path}:{lineno} 不是数值行：{line!r}") from None
        if len(values) < 4:
            raise TiePointsUnreadable(f"{path}:{lineno} 不足 4 列：{line!r}")
        rows.append(values[:4])
    if not rows:
        raise TiePointsUnreadable(f"{path} 里一对点也没有")
    data = np.asarray(rows, dtype=np.float64)
    return data[:, :2], data[:, 2:4]
