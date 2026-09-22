"""扫描 patch 产物，产出写进统计快照的全部统计量。

文档里出现的每一个数字都从这里来。它们不手写，理由很具体：数据集已冻结，但文档会被
反复编辑，手写的数字会在无人察觉时过期——窗口清单记录的数量与实际产物差 18 条，
就是这样一直没人发现的。

## 两种口径

ROI_060 与 ROI_037 逐像素重复，已从数据盘删除，但它曾经是验证集的一部分，且它的
窗口仍在窗口清单里。所以 ROI 与 patch 的数量**一律给两套**：
`excluding_removed`（盘上现存的）与 `including_removed`（加回被删的）。
被删 ROI 的数量取自删除时留下的文件清单——那是它唯一的剩余记录。清单只有文件名，
所以它的评测真值点**点数未知，记为 None 而不是 0**。

## 为什么输出是 dict 而不是 dataclass

`scan_products` 的产出原样写进 JSON 快照，文档页再按键名取值。键名就是快照的格式契约，
中间再套一层 dataclass 只会多出一套要与键名保持同步的字段名。

## 只读产物，不读原始影像

本模块只扫 `Processed_Data/`，读取靠 `moondata.tiff`，不依赖 GDAL。
"""

from __future__ import annotations

import json
import re
import statistics
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from moondata.errors import StatsUnavailable
from moondata.tiff import DEFLATE, NO_COMPRESSION, TiffInfo, read_tiff

PRODUCT_DIRNAME = "Processed_Data"
SPLITS = ("Train", "Val", "Test")
OPTICAL = "Optical"
SAR = "SAR"
MODALITIES = (OPTICAL, SAR)
LABEL_DIRNAME = "Label"
READ_THREADS = 8
"""zlib 解压时释放 GIL，几个线程就足以把 USB 盘读满。"""

_PATCH_RE = re.compile(r"patch_(\d+)\.tif")
_LABEL_RE = re.compile(r"patch_(\d+)\.(txt|prj)")
_ROI_RE = re.compile(r"ROI_\d+")
_GUID_RE = re.compile(r"\{[0-9A-Fa-f-]+\}")

# 删除清单的头部，形如 `# 已删除: Processed_Data/Val/ROI_060`
_REMOVED_HEADER_RE = re.compile(r"^#\s*已删除:\s*\S*?/?(Train|Val|Test)/(ROI_\d+)\s*$", re.M)
_REASON_RE = re.compile(r"^#\s*原因:\s*(.+?)\s*$", re.M)
_DATE_RE = re.compile(r"^#\s*删除日期:\s*(\S+)\s*$", re.M)

Progress = Callable[[str], None]


@dataclass(frozen=True)
class RemovedRoi:
    roi: str
    split: str
    reason: str
    deleted_on: str
    patch_count: int
    labeled_patch_count: int


def parse_removed_manifest(text: str) -> RemovedRoi:
    header = _REMOVED_HEADER_RE.search(text)
    if header is None:
        raise StatsUnavailable("删除清单缺少「# 已删除: <划分>/<ROI>」这一行，认不出删的是谁")
    reason = _REASON_RE.search(text)
    date = _DATE_RE.search(text)
    # 与现存 ROI 同一口径：patch 要光学与 SAR 都在，标签只算落在这些 patch 上的
    found: dict[str, set[int]] = {OPTICAL: set(), SAR: set(), LABEL_DIRNAME: set()}
    for line in text.splitlines():
        parts = line.strip().removeprefix("./").split("/")
        if len(parts) != 2 or parts[0] not in found:
            continue
        directory, name = parts
        pattern = _LABEL_RE if directory == LABEL_DIRNAME else _PATCH_RE
        match = pattern.fullmatch(name)
        if match is None or (directory == LABEL_DIRNAME and match.group(2) != "txt"):
            continue
        found[directory].add(int(match.group(1)))
    patches = found[OPTICAL] & found[SAR]
    return RemovedRoi(
        roi=header.group(2),
        split=header.group(1),
        reason=reason.group(1) if reason else "",
        deleted_on=date.group(1) if date else "",
        patch_count=len(patches),
        labeled_patch_count=len(found[LABEL_DIRNAME] & patches),
    )


def scan_products(
    product_root: Path,
    *,
    removed: Sequence[RemovedRoi] = (),
    window_manifests: Sequence[Path] = (),
    progress: Progress | None = None,
) -> dict:
    """扫描 `product_root`（即数据根下的 `Processed_Data/`），返回可直接写进快照的字典。"""
    product_root = Path(product_root)
    if not product_root.is_dir():
        raise StatsUnavailable(f"找不到 patch 产物目录：{product_root}")

    naming = _Naming()
    rois: dict[str, dict] = {}
    images = {modality: _ImageAccumulator() for modality in MODALITIES}
    labels = _LabelAccumulator()

    with ThreadPoolExecutor(max_workers=READ_THREADS) as pool:
        for split, roi_dir in _roi_dirs(product_root, naming):
            if progress is not None:
                progress(f"{split}/{roi_dir.name}")
            indices = _patch_indices(product_root, split, roi_dir, naming)
            for modality in MODALITIES:
                paths = [roi_dir / modality / f"patch_{i}.tif" for i in sorted(indices[modality])]
                for info, array in pool.map(read_tiff, paths):
                    images[modality].add(info, array)
            label_points = labels.add_roi(roi_dir / LABEL_DIRNAME, indices[LABEL_DIRNAME])
            rois[roi_dir.name] = {
                "split": split,
                "patch_count": len(indices[OPTICAL] & indices[SAR]),
                "labeled_patch_count": len(label_points),
                "label_point_count": sum(label_points),
            }

    return {
        "product_root": PRODUCT_DIRNAME,
        "splits": list(SPLITS),
        "rois": rois,
        "removed_rois": [asdict(roi) for roi in removed],
        "counts": {
            "excluding_removed": _counts(rois, ()),
            "including_removed": _counts(rois, removed),
        },
        "images": {modality: acc.summary() for modality, acc in images.items()},
        "labels": labels.summary(),
        "naming": naming.summary(),
        "window_manifests": _compare_windows(window_manifests, rois, removed),
    }


def _roi_dirs(product_root: Path, naming: _Naming) -> Iterable[tuple[str, Path]]:
    for split in SPLITS:
        split_dir = product_root / split
        if not split_dir.is_dir():
            continue
        for roi_dir in sorted(split_dir.iterdir()):
            if roi_dir.is_dir() and _ROI_RE.fullmatch(roi_dir.name):
                yield split, roi_dir
            else:
                naming.unexpected(roi_dir.relative_to(product_root))


def _patch_indices(
    product_root: Path, split: str, roi_dir: Path, naming: _Naming
) -> dict[str, set[int]]:
    indices: dict[str, set[int]] = {}
    for sub, pattern in (
        (OPTICAL, _PATCH_RE),
        (SAR, _PATCH_RE),
        (LABEL_DIRNAME, _LABEL_RE),
    ):
        found: set[int] = set()
        directory = roi_dir / sub
        if directory.is_dir():
            for path in directory.iterdir():
                match = pattern.fullmatch(path.name)
                if match is None:
                    naming.unexpected(path.relative_to(product_root))
                    continue
                if sub == LABEL_DIRNAME and match.group(2) != "txt":
                    continue
                found.add(int(match.group(1)))
        indices[sub] = found

    where = f"{split}/{roi_dir.name}"
    for index in sorted(indices[OPTICAL] ^ indices[SAR]):
        naming.unpaired.append(f"{where}/patch_{index}")
    patches = indices[OPTICAL] | indices[SAR]
    if patches and patches != set(range(max(patches) + 1)):
        naming.index_gaps.append(where)
    # 只统计「光学与 SAR 都在」的那部分标签——孤零零一个标签对不上任何 patch
    indices[LABEL_DIRNAME] &= indices[OPTICAL] & indices[SAR]
    return indices


@dataclass
class _Naming:
    unpaired: list[str] = field(default_factory=list)
    index_gaps: list[str] = field(default_factory=list)
    unexpected_files: list[str] = field(default_factory=list)

    def unexpected(self, relpath: Path) -> None:
        self.unexpected_files.append(relpath.as_posix())

    def summary(self) -> dict:
        return {
            "unpaired": self.unpaired,
            "index_gaps": self.index_gaps,
            "unexpected_files": sorted(self.unexpected_files),
        }


class _ImageAccumulator:
    """跨全部 patch 累计一种模态的类型、形状与数值范围。数值范围只算有效像素（≠ nodata）。"""

    def __init__(self) -> None:
        self.file_count = 0
        self.bytes = 0
        self.dtypes: set[str] = set()
        self.bands: set[int] = set()
        self.sizes: set[tuple[int, int]] = set()
        self.compressions: set[str] = set()
        self.nodata: set[float | None] = set()
        self.pixel_scales: set[tuple[float, float]] = set()
        self.minima: np.ndarray | None = None
        self.maxima: np.ndarray | None = None
        self.patches_with_negative = 0
        self.nan_pixels = 0
        self.nodata_pixels = 0
        self.pixels = 0

    def add(self, info: TiffInfo, array: np.ndarray) -> None:
        self.file_count += 1
        self.bytes += info.path.stat().st_size
        self.dtypes.add(str(info.dtype))
        self.bands.add(info.bands)
        self.sizes.add((info.width, info.height))
        self.compressions.add(_compression_name(info.compression))
        self.nodata.add(info.nodata)
        if info.pixel_scale is not None:
            # 浮点误差会让 7.5 变成 7.499999999999998，不收敛的话同一个值会被列两遍
            self.pixel_scales.add(tuple(round(v, 6) for v in info.pixel_scale))

        valid = ~np.isnan(array) if array.dtype.kind == "f" else np.ones(array.shape, bool)
        self.nan_pixels += int(np.count_nonzero(~valid))
        if info.nodata is not None:
            is_nodata = array == info.nodata
            self.nodata_pixels += int(np.count_nonzero(is_nodata.all(axis=2)))
            valid &= ~is_nodata
        self.pixels += info.width * info.height

        minima = np.array([_band_extreme(array[..., b], valid[..., b], np.min) for b in range(info.bands)])
        maxima = np.array([_band_extreme(array[..., b], valid[..., b], np.max) for b in range(info.bands)])
        if self.minima is None:
            self.minima, self.maxima = minima, maxima
        elif self.minima.shape != minima.shape:
            # 逐波段的范围只在波段数一致时有意义；混着来说明产物本身出了问题
            raise StatsUnavailable(
                f"同一模态的 patch 波段数不一致：{info.path} 有 {info.bands} 个波段，"
                f"此前的是 {self.minima.shape[0]} 个"
            )
        else:
            self.minima = np.fmin(self.minima, minima)
            self.maxima = np.fmax(self.maxima, maxima)
        if np.any(array[valid] < 0):
            self.patches_with_negative += 1

    def summary(self) -> dict:
        ranges = []
        if self.minima is not None:
            for low, high in zip(self.minima, self.maxima):
                ranges.append({"min": _plain(low), "max": _plain(high)})
        return {
            "file_count": self.file_count,
            "bytes": self.bytes,
            "dtypes": sorted(self.dtypes),
            "bands": sorted(self.bands),
            "sizes": [list(size) for size in sorted(self.sizes)],
            "compressions": sorted(self.compressions),
            "nodata": sorted(self.nodata, key=lambda v: (v is None, v)),
            "pixel_scales": [list(scale) for scale in sorted(self.pixel_scales)],
            "band_ranges": ranges,
            "patches_with_negative": self.patches_with_negative,
            "nan_pixel_count": self.nan_pixels,
            "nodata_pixel_fraction": self.nodata_pixels / self.pixels if self.pixels else 0.0,
        }


def _band_extreme(
    band: np.ndarray, valid: np.ndarray, extreme: Callable[[np.ndarray], object]
) -> float:
    values = band[valid]
    return float(extreme(values)) if values.size else np.nan


def _plain(value: float) -> int | float | None:
    """JSON 里整数就写整数（光学的 0–255），浮点保留 float32 能表达的精度。"""
    if np.isnan(value):
        return None
    if float(value).is_integer() and abs(value) < 2**53:
        return int(value)
    return float(np.float32(value))


def _compression_name(code: int) -> str:
    if code == NO_COMPRESSION:
        return "None"
    if code in DEFLATE:
        return "Deflate"
    return str(code)


class _LabelAccumulator:
    def __init__(self) -> None:
        self.points_per_patch: list[int] = []
        self.columns: set[int] = set()
        self.y_all_nonpositive = True
        self.prj_kinds: dict[str, int] = {}

    def add_roi(self, label_dir: Path, indices: set[int]) -> list[int]:
        counts = []
        for index in sorted(indices):
            rows = _read_label(label_dir / f"patch_{index}.txt")
            for row in rows:
                self.columns.add(len(row))
                # 评测真值点文件对 y 取负（见术语表「坐标符号约定」）：第 2、4 列应全 ≤ 0
                if any(value > 0 for value in row[1::2]):
                    self.y_all_nonpositive = False
            counts.append(len(rows))
            prj = label_dir / f"patch_{index}.prj"
            if prj.is_file():
                kind = _prj_kind(prj.read_text(encoding="utf-8", errors="replace"))
                self.prj_kinds[kind] = self.prj_kinds.get(kind, 0) + 1
        self.points_per_patch.extend(counts)
        return counts

    def summary(self) -> dict:
        points = self.points_per_patch
        return {
            "file_count": len(points),
            "points_per_patch": (
                {
                    "min": min(points),
                    "median": _plain(statistics.median(points)),
                    "max": max(points),
                }
                if points
                else None
            ),
            "columns": sorted(self.columns),
            "y_all_nonpositive": self.y_all_nonpositive,
            "prj_kinds": dict(sorted(self.prj_kinds.items())),
        }


def _prj_kind(text: str) -> str:
    """标签旁的 `.prj` 多数只是标注软件写下的一个 GUID 占位，少数是完整的 WKT 投影。"""
    text = text.strip()
    if _GUID_RE.fullmatch(text):
        return "guid"
    if text.startswith(("PROJCS[", "GEOGCS[")):
        return "wkt"
    return "other"


def _read_label(path: Path) -> list[tuple[float, ...]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(tuple(float(value) for value in line.split()))
        except ValueError as error:
            raise StatsUnavailable(f"评测真值点文件第 {line_number} 行读不动：{path}（{error}）") from error
    return rows


def _counts(rois: dict[str, dict], removed: Iterable[RemovedRoi]) -> dict:
    per_split = {
        split: {
            "roi_count": 0,
            "patch_count": 0,
            "labeled_patch_count": 0,
            "label_point_count": 0,
        }
        for split in (*SPLITS, "all")
    }

    def add(split: str, patches: int, labeled: int, points: int | None) -> None:
        for key in (split, "all"):
            bucket = per_split[key]
            bucket["roi_count"] += 1
            bucket["patch_count"] += patches
            bucket["labeled_patch_count"] += labeled
            if points is None or bucket["label_point_count"] is None:
                bucket["label_point_count"] = None
            else:
                bucket["label_point_count"] += points

    for record in rois.values():
        add(
            record["split"],
            record["patch_count"],
            record["labeled_patch_count"],
            record["label_point_count"],
        )
    for roi in removed:
        # 被删 ROI 若本身没有标签，点数确实是 0，而不是未知
        points = None if roi.labeled_patch_count else 0
        add(roi.split, roi.patch_count, roi.labeled_patch_count, points)
    return per_split


def _compare_windows(
    manifests: Sequence[Path], rois: dict[str, dict], removed: Sequence[RemovedRoi]
) -> dict:
    """窗口清单与产物逐 ROI 对数量。被删 ROI 按删除清单里的数量参与比对。"""
    product = {roi: record["patch_count"] for roi, record in rois.items()}
    product |= {roi.roi: roi.patch_count for roi in removed}
    split_of = {roi: record["split"] for roi, record in rois.items()}
    split_of |= {roi.roi: roi.split for roi in removed}

    listed: dict[str, tuple[str, int, int]] = {}
    for path in manifests:
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
            for roi, record in document["rois"].items():
                listed[roi] = (
                    record["split"],
                    len(record["patches"]),
                    len(record.get("unresolved", [])),
                )
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise StatsUnavailable(f"窗口清单读不动：{path}（{error}）") from error

    splits = {split: {"windows": 0, "unresolved": 0, "product_patches": 0} for split in SPLITS}
    differences = []
    for roi in sorted(set(listed) | set(product)):
        split, windows, unresolved = listed.get(roi, (split_of[roi], 0, 0))
        patches = product.get(roi, 0)
        bucket = splits[split]
        bucket["windows"] += windows
        bucket["unresolved"] += unresolved
        bucket["product_patches"] += patches
        # unresolved 是清单自己承认没对上的窗口，数量碰巧相等也要列出来
        if windows != patches or unresolved:
            differences.append(
                {
                    "roi": roi,
                    "split": split,
                    "windows": windows,
                    "unresolved": unresolved,
                    "product_patches": patches,
                }
            )
    return {
        "files": [Path(path).name for path in manifests],
        "splits": splits,
        "differences": differences,
    }
