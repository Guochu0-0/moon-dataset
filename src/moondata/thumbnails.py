"""ROI 档案页的缩略图：从对齐影像逐块降采样、拉伸成 8 位灰度 PNG。

**缩略图取自对齐影像**（`raw/ROI_<n>/cropped/ce2/{opt,sar}.tif`），不是拼 patch：patch 只
覆盖 ROI 的一部分，而档案页要让人一眼看出整个 ROI 长什么样、哪里没数据。

对齐影像合计六十多 GB、全在移动硬盘上，所以缩略图**生成一次、作为产物提交**，
文档渲染只读 PNG。生成前提（接上数据盘、跑 `moondata thumbnails`）与每张图的来源、
降采样步长、拉伸区间记在同目录的 `thumbnails.json` 里，档案页照着它写图注。

两个取舍：

- **块均值而不是隔点抽样。** SAR 有相干斑，隔点抽出来是一片噪点；在线性功率上取均值
  相当于多视平滑，缩略图才看得出地形。
- **不依赖任何影像库。** 读用 `moondata.tiff`，写 PNG 用标准库 `zlib`。同样的输入
  永远写出同样的字节，重跑不会在 git 里制造无意义的二进制改动。
"""

from __future__ import annotations

import json
import math
import struct
import zlib
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from moondata.errors import ThumbnailUnavailable
from moondata.tiff import iter_blocks, read_info

MANIFEST_NAME = "thumbnails.json"
MAX_SIDE = 600
"""长边像素数。条带是细长的（长宽比常见 1:4 到 1:17），长边再大页面也放不下。"""
PERCENTILES = (2.0, 98.0)
"""拉伸区间取有效像素的这两个百分位，两端各让出一点，免得几个亮点把整幅压暗。"""
READ_THREADS = 4
"""按文件并行。瓶颈是移动硬盘的顺序读，再多线程只会让磁头来回跳。"""

BlockValues = tuple[np.ndarray, np.ndarray]
"""一块的（数值, 有效掩膜），都是 `(h, w)`。"""


@dataclass(frozen=True)
class Modality:
    name: str
    label: str
    """页面上的叫法。"""
    filename: str
    describe: str
    """图注里说明像素值是什么。"""
    values: Callable[[np.ndarray, float | None], BlockValues]
    to_display: Callable[[np.ndarray], np.ndarray]
    """均值算完之后、拉伸之前的变换。"""
    unit: str


def _optical_values(block: np.ndarray, nodata: float | None) -> BlockValues:
    values = block[:, :, 0].astype(np.float64)
    valid = values != nodata if nodata is not None else np.ones(values.shape, bool)
    return values, valid


def _sar_values(block: np.ndarray, nodata: float | None) -> BlockValues:
    # 波段 1、2 是 H、V 两路接收强度（功率），相加即总功率——来源文档里的 S1。
    # 波段 3、4 是交叉功率的实部虚部，可正可负，不适合直接看。
    power = block[:, :, 0].astype(np.float64) + block[:, :, 1]
    valid = np.isfinite(block).all(axis=2) & (power > 0)
    if nodata is not None:
        valid &= (block != nodata).any(axis=2)
    return power, valid


def _decibels(power: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return 10 * np.log10(power)


OPTICAL = Modality("optical", "光学", "opt.tif", "灰度值", _optical_values, lambda a: a, "")
SAR = Modality("sar", "SAR", "sar.tif", "H + V 总功率（dB）", _sar_values, _decibels, " dB")
MODALITIES = (OPTICAL, SAR)


@dataclass(frozen=True)
class Thumbnail:
    pixels: np.ndarray
    step: int
    source_size: tuple[int, int]
    """原图的（宽, 高）。"""
    stretch: tuple[float, float]
    """拉伸到 0 与 255 的两个值，单位同 `Modality.unit`。"""


def block_mean(
    blocks: Iterable[tuple[int, int, BlockValues]], *, shape: tuple[int, int], step: int
) -> np.ndarray:
    """把原图每 `step × step` 个像素并成一个，取其中有效像素的均值；一个有效像素都
    没有的格子是 NaN。块的边界不必与格子对齐。"""
    out_shape = (-(-shape[0] // step), -(-shape[1] // step))
    sums = np.zeros(out_shape)
    counts = np.zeros(out_shape)
    for top, left, (values, valid) in blocks:
        rows = (top + np.arange(values.shape[0])) // step
        columns = (left + np.arange(values.shape[1])) // step
        first_row, first_column = rows[0], columns[0]
        height, width = rows[-1] - first_row + 1, columns[-1] - first_column + 1
        # 只在这一块覆盖到的那几个格子上 bincount，免得每块都分配一整张输出图
        cell = (rows - first_row)[:, None] * width + (columns - first_column)[None, :]
        cell, kept = cell[valid], values[valid]
        region = (
            slice(first_row, first_row + height),
            slice(first_column, first_column + width),
        )
        sums[region] += np.bincount(cell, kept, height * width).reshape(height, width)
        counts[region] += np.bincount(cell, None, height * width).reshape(height, width)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(counts > 0, sums / counts, np.nan)


def stretch(
    image: np.ndarray, percentiles: tuple[float, float] = PERCENTILES
) -> tuple[np.ndarray, tuple[float, float]]:
    """线性拉伸到 0–255。NaN（没有数据）画成黑色。"""
    finite = image[np.isfinite(image)]
    low, high = (float(v) for v in np.percentile(finite, percentiles))
    scaled = (image - low) / (high - low) if high > low else np.zeros_like(image)
    scaled = np.nan_to_num(scaled, nan=0.0)
    pixels = np.rint(np.clip(scaled, 0, 1) * 255).astype(np.uint8)
    return pixels, (low, high)


def encode_png(pixels: np.ndarray) -> bytes:
    """8 位灰度 PNG。"""
    height, width = pixels.shape

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    rows = np.hstack([np.zeros((height, 1), np.uint8), pixels.astype(np.uint8)])
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows.tobytes(), 9))
        + chunk(b"IEND", b"")
    )


def make_thumbnail(path: Path, modality: Modality, *, max_side: int = MAX_SIDE) -> Thumbnail:
    info = read_info(path)
    step = max(1, math.ceil(max(info.width, info.height) / max_side))
    blocks = (
        (top, left, modality.values(block, info.nodata))
        for top, left, block in iter_blocks(path)
    )
    mean = block_mean(blocks, shape=(info.height, info.width), step=step)
    display = modality.to_display(mean)
    if not np.isfinite(display).any():
        raise ThumbnailUnavailable(f"整幅没有一个有效像素，画不出缩略图：{path}")
    pixels, limits = stretch(display)
    return Thumbnail(pixels, step, (info.width, info.height), limits)


def aligned_image(raw_name: str, modality: Modality) -> Path:
    """对齐影像相对数据根的路径。`raw_name` 是不补零的写法，如 `ROI_6`。"""
    return Path("raw") / raw_name / "cropped" / "ce2" / modality.filename


def generate_thumbnails(
    data_root: Path,
    rois: Mapping[str, str],
    out_dir: Path,
    *,
    max_side: int = MAX_SIDE,
    generated_at: str,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """为 `rois`（补零名 → `raw/` 下的目录名）画缩略图，写进 `out_dir`，返回并写出清单。

    `data_root` 下找不到对齐影像的 ROI 不算错：记进清单的 `missing`，档案页据此说明
    「没有对齐影像」。其余错误（文件坏了）照常抛出——那是要人去看的。
    """
    jobs, missing = [], {}
    for roi, raw_name in sorted(rois.items()):
        paths = [aligned_image(raw_name, m) for m in MODALITIES]
        absent = [p.as_posix() for p in paths if not (data_root / p).is_file()]
        if absent:
            missing[roi] = absent
            continue
        jobs += [(roi, m, p) for m, p in zip(MODALITIES, paths)]

    def run(job: tuple[str, Modality, Path]) -> tuple[str, Modality, Path, Thumbnail]:
        roi, modality, relpath = job
        if progress is not None:
            progress(relpath.as_posix())
        return roi, modality, relpath, make_thumbnail(
            data_root / relpath, modality, max_side=max_side
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    entries: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(READ_THREADS) as pool:
        for roi, modality, relpath, thumb in pool.map(run, jobs):
            filename = f"{roi}_{modality.name}.png"
            (out_dir / filename).write_bytes(encode_png(thumb.pixels))
            entries.setdefault(roi, {})[modality.name] = {
                "file": filename,
                "source": relpath.as_posix(),
                "source_size": list(thumb.source_size),
                "step": thumb.step,
                "shown": modality.describe,
                "stretch": [round(v, 4) for v in thumb.stretch],
                "unit": modality.unit,
            }

    manifest = {
        "generated_at": generated_at,
        "max_side": max_side,
        "percentiles": list(PERCENTILES),
        "rois": {roi: entries[roi] for roi in sorted(entries)},
        "missing": missing,
    }
    (out_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest
