"""测试用的极简 TIFF 写入器。

只写 `moondata.tiff` 需要读的那几个标签，外加若干开关用来造出「读取器应当拒绝」
的文件。测试不能依赖真实数据盘，所以 fixture 影像只能自己造。
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

SHORT, LONG, DOUBLE, ASCII = 3, 4, 12, 2
_TYPE_FORMAT = {SHORT: "H", LONG: "I", DOUBLE: "d"}

SAMPLE_FORMAT = {"u": 1, "i": 2, "f": 3}


def write_tiff(
    path: Path,
    array: np.ndarray,
    *,
    rows_per_strip: int | None = None,
    compression: int = 8,
    byteorder: str = "<",
    predictor: int = 1,
    tiled: bool = False,
    nodata: str | None = "0",
    pixel_scale: tuple[float, float, float] | None = (7.5, 7.5, 0.0),
    tiepoint: tuple[float, ...] | None = (0.0, 0.0, 0.0, 100.0, -200.0, 0.0),
) -> Path:
    """把 `(H, W)` 或 `(H, W, C)` 数组写成条带式 TIFF。"""
    if array.ndim == 2:
        array = array[:, :, np.newaxis]
    height, width, bands = array.shape
    if rows_per_strip is None:
        rows_per_strip = height
    data = np.ascontiguousarray(array.astype(array.dtype.newbyteorder(byteorder)))

    strips: list[bytes] = []
    for top in range(0, height, rows_per_strip):
        raw = data[top : top + rows_per_strip].tobytes()
        strips.append(zlib.compress(raw) if compression in (8, 32946) else raw)

    header_size = 8
    offsets: list[int] = []
    cursor = header_size
    for strip in strips:
        offsets.append(cursor)
        cursor += len(strip)
    ifd_offset = cursor + (cursor % 2)

    itemsize = array.dtype.itemsize
    tags: list[tuple[int, int, list | bytes]] = [
        (256, LONG, [width]),
        (257, LONG, [height]),
        (258, SHORT, [itemsize * 8] * bands),
        (259, SHORT, [compression]),
        (262, SHORT, [1]),
        (273, LONG, offsets),
        (277, SHORT, [bands]),
        (278, LONG, [rows_per_strip]),
        (279, LONG, [len(s) for s in strips]),
        (284, SHORT, [1]),
        (317, SHORT, [predictor]),
        (339, SHORT, [SAMPLE_FORMAT[array.dtype.kind]] * bands),
    ]
    if tiled:
        tags.append((322, LONG, [16]))
    if pixel_scale is not None:
        tags.append((33550, DOUBLE, list(pixel_scale)))
    if tiepoint is not None:
        tags.append((33922, DOUBLE, list(tiepoint)))
    if nodata is not None:
        tags.append((42113, ASCII, nodata.encode("ascii") + b"\0"))
    tags.sort(key=lambda tag: tag[0])

    entries = b""
    extra = b""
    extra_start = ifd_offset + 2 + 12 * len(tags) + 4
    for code, kind, values in tags:
        if kind == ASCII:
            payload = bytes(values)
            count = len(payload)
        else:
            count = len(values)
            payload = struct.pack(f"{byteorder}{count}{_TYPE_FORMAT[kind]}", *values)
        if len(payload) <= 4:
            field = payload.ljust(4, b"\0")
        else:
            field = struct.pack(f"{byteorder}I", extra_start + len(extra))
            extra += payload + (b"\0" if len(payload) % 2 else b"")
        entries += struct.pack(f"{byteorder}HHI", code, kind, count) + field

    magic = b"II" if byteorder == "<" else b"MM"
    blob = (
        magic
        + struct.pack(f"{byteorder}HI", 42, ifd_offset)
        + b"".join(strips)
        + b"\0" * (ifd_offset - cursor)
        + struct.pack(f"{byteorder}H", len(tags))
        + entries
        + struct.pack(f"{byteorder}I", 0)
        + extra
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)
    return path
