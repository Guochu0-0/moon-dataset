"""不依赖任何影像库的 TIFF 读取器——读 patch 产物与对齐影像。

patch 用 Deflate 压缩、按条带存储。**tifffile 读它们会报
`libdeflate_zlib_decompress returned LIBDEFLATE_BAD_DATA`**，而把同一段条带字节交给
标准库 `zlib` 却能完整解出、校验和也对得上。换句话说数据没坏，是 libdeflate 比
zlib 挑剔。所以这里自己解析 TIFF 目录、逐条带用 `zlib` 解压，绕开那一层。

它不放进 `moondata.raster`：那一层是 GDAL 的地盘，而读 patch 恰恰是没装 GDAL 的人
（训练服务器、只装了文档档的人）最需要的能力。本模块只用标准库和 numpy。

支持面刻意收窄到本数据集实际用到的编码：经典 TIFF（非 BigTIFF）、像素交错、
无 Predictor、不压缩或 Deflate；布局上 patch 是条带式，对齐影像（`raw/ROI_*/cropped/ce2/`）
是 256 × 256 分块式，两种都支持。**超出这个范围一律报错而不是尽力而为**——读错的
代价是一组看起来完全正常的错数字。

对齐影像动辄几 GB，读缩略图时不能整幅进内存，所以另有 `iter_blocks` 一块一块地给。
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from moondata.errors import TiffUnreadable

# 标签号，见 TIFF 6.0 与 GeoTIFF 1.0 规范
IMAGE_WIDTH = 256
IMAGE_LENGTH = 257
BITS_PER_SAMPLE = 258
COMPRESSION = 259
STRIP_OFFSETS = 273
SAMPLES_PER_PIXEL = 277
ROWS_PER_STRIP = 278
STRIP_BYTE_COUNTS = 279
PLANAR_CONFIGURATION = 284
PREDICTOR = 317
TILE_WIDTH = 322
TILE_LENGTH = 323
TILE_OFFSETS = 324
TILE_BYTE_COUNTS = 325
SAMPLE_FORMAT = 339
MODEL_PIXEL_SCALE = 33550
MODEL_TIEPOINT = 33922
GDAL_NODATA = 42113

NO_COMPRESSION = 1
DEFLATE = (8, 32946)  # 8 是 Adobe 登记的代号，32946 是更早的私有代号，同一种编码

# 字段类型 → (struct 格式字符, 字节数)。ASCII 单独处理。
_FIELD_TYPES: dict[int, tuple[str, int]] = {
    1: ("B", 1),
    3: ("H", 2),
    4: ("I", 4),
    5: ("II", 8),
    6: ("b", 1),
    7: ("B", 1),
    8: ("h", 2),
    9: ("i", 4),
    10: ("ii", 8),
    11: ("f", 4),
    12: ("d", 8),
}
_ASCII = 2

_SAMPLE_KIND = {1: "u", 2: "i", 3: "f"}


@dataclass(frozen=True)
class TiffInfo:
    """一幅 TIFF 的头信息。读它只需要几百字节，不解压像素。"""

    path: Path
    width: int
    height: int
    bands: int
    dtype: np.dtype
    compression: int
    nodata: float | None
    pixel_scale: tuple[float, float] | None
    """每像素的地面尺寸（x, y），单位随投影，本数据集为米。"""
    origin: tuple[float, float] | None
    """左上角像素的地图坐标。"""
    block_size: tuple[int, int]
    """每块的（宽, 高）。条带式的「块」就是一整行宽的条带，最后一条可以更短；
    分块式的边缘块按规范补齐到整块大小，多出来的部分要裁掉。"""
    block_offsets: tuple[int, ...]
    block_byte_counts: tuple[int, ...]
    tiled: bool
    byteorder: str

    @property
    def blocks_across(self) -> int:
        return -(-self.width // self.block_size[0])


def read_info(path: str | Path) -> TiffInfo:
    path = Path(path)
    try:
        with path.open("rb") as stream:
            return _parse(path, stream)
    except (OSError, struct.error) as error:
        raise TiffUnreadable(f"TIFF 读不动：{path}（{error}）") from error


def read_tiff(path: str | Path) -> tuple[TiffInfo, np.ndarray]:
    """读出头信息与像素。像素一律是 `(H, W, C)`，单波段也保留 C 这一维——
    调用方不必再为「光学是二维、SAR 是三维」分支。"""
    info = read_info(path)
    array = np.empty((info.height, info.width, info.bands), dtype=info.dtype)
    for top, left, block in iter_blocks(path):
        array[top : top + block.shape[0], left : left + block.shape[1]] = block
    return info, array


def iter_blocks(path: str | Path) -> Iterator[tuple[int, int, np.ndarray]]:
    """逐块给出 `(top, left, 像素)`，像素是 `(h, w, C)`，已裁到影像范围之内。

    各块互不重叠、合起来恰好铺满整幅。块内像素已转成本机字节序。
    """
    path = Path(path)
    try:
        with path.open("rb") as stream:
            info = _parse(path, stream)
            for index in range(len(info.block_offsets)):
                yield _block(info, stream, index)
    except (OSError, struct.error) as error:
        raise TiffUnreadable(f"TIFF 读不动：{path}（{error}）") from error


def _block(info: TiffInfo, stream, index: int) -> tuple[int, int, np.ndarray]:
    block_width, block_height = info.block_size
    row, column = divmod(index, info.blocks_across)
    top, left = row * block_height, column * block_width
    rows = min(block_height, info.height - top)
    columns = min(block_width, info.width - left)
    # 条带的最后一条只存有效的行；分块的边缘块存的是补齐后的整块
    stored_rows = block_height if info.tiled else rows

    what = "块" if info.tiled else "条带"
    count = info.block_byte_counts[index]
    stream.seek(info.block_offsets[index])
    data = stream.read(count)
    if len(data) != count:
        raise TiffUnreadable(f"TIFF 第 {index} {what}被截断：{info.path}")
    if info.compression != NO_COMPRESSION:
        try:
            data = zlib.decompress(data)
        except zlib.error as error:
            raise TiffUnreadable(
                f"TIFF 第 {index} {what}解压失败：{info.path}（{error}）"
            ) from error

    expected = stored_rows * block_width * info.bands * info.dtype.itemsize
    if len(data) != expected:
        raise TiffUnreadable(
            f"TIFF 第 {index} {what}的像素数据长度不对：{info.path}"
            f"（应为 {expected} 字节，实得 {len(data)}）"
        )
    pixels = np.frombuffer(data, dtype=info.dtype.newbyteorder(info.byteorder))
    pixels = pixels.reshape(stored_rows, block_width, info.bands)[:rows, :columns]
    return top, left, pixels.astype(info.dtype)


def _parse(path: Path, stream) -> TiffInfo:
    header = stream.read(8)
    if header[:2] == b"II":
        byteorder = "<"
    elif header[:2] == b"MM":
        byteorder = ">"
    else:
        raise TiffUnreadable(f"不是 TIFF 文件：{path}")
    magic, ifd_offset = struct.unpack(f"{byteorder}HI", header[2:8])
    if magic == 43:
        raise TiffUnreadable(f"不支持 BigTIFF：{path}")
    if magic != 42:
        raise TiffUnreadable(f"不是 TIFF 文件：{path}")

    tags = _read_ifd(path, stream, ifd_offset, byteorder)

    def require(code: int, name: str) -> tuple:
        if code not in tags:
            raise TiffUnreadable(f"TIFF 缺少必需的标签 {name}：{path}")
        return tags[code]

    compression = tags.get(COMPRESSION, (NO_COMPRESSION,))[0]
    if compression != NO_COMPRESSION and compression not in DEFLATE:
        raise TiffUnreadable(f"不支持的压缩方式 Compression={compression}：{path}")
    predictor = tags.get(PREDICTOR, (1,))[0]
    if predictor != 1:
        raise TiffUnreadable(f"不支持 Predictor={predictor}：{path}")
    bands = tags.get(SAMPLES_PER_PIXEL, (1,))[0]
    if bands > 1 and tags.get(PLANAR_CONFIGURATION, (1,))[0] != 1:
        raise TiffUnreadable(f"不支持按波段分平面存储（PlanarConfiguration=2）：{path}")

    bits = set(require(BITS_PER_SAMPLE, "BitsPerSample"))
    formats = set(tags.get(SAMPLE_FORMAT, (1,)))
    if len(bits) != 1 or len(formats) != 1 or next(iter(formats)) not in _SAMPLE_KIND:
        raise TiffUnreadable(
            f"不支持各波段类型不一致或未知的样本格式"
            f"（BitsPerSample={sorted(bits)}，SampleFormat={sorted(formats)}）：{path}"
        )
    bit_depth = next(iter(bits))
    if bit_depth % 8:
        raise TiffUnreadable(f"不支持非整字节的位深 {bit_depth}：{path}")
    dtype = np.dtype(f"{_SAMPLE_KIND[next(iter(formats))]}{bit_depth // 8}")

    width = require(IMAGE_WIDTH, "ImageWidth")[0]
    height = require(IMAGE_LENGTH, "ImageLength")[0]
    tiled = TILE_WIDTH in tags
    if tiled:
        block_size = (
            require(TILE_WIDTH, "TileWidth")[0],
            require(TILE_LENGTH, "TileLength")[0],
        )
        offsets = require(TILE_OFFSETS, "TileOffsets")
        counts = require(TILE_BYTE_COUNTS, "TileByteCounts")
    else:
        block_size = (width, tags.get(ROWS_PER_STRIP, (height,))[0])
        offsets = require(STRIP_OFFSETS, "StripOffsets")
        counts = require(STRIP_BYTE_COUNTS, "StripByteCounts")
    across = -(-width // block_size[0])
    down = -(-height // block_size[1])
    if not (len(offsets) == len(counts) == across * down):
        raise TiffUnreadable(
            f"TIFF 的块数对不上：{path}（按尺寸应有 {across * down} 块，"
            f"偏移表 {len(offsets)} 项，长度表 {len(counts)} 项）"
        )

    scale = tags.get(MODEL_PIXEL_SCALE)
    tiepoint = tags.get(MODEL_TIEPOINT)
    nodata = tags.get(GDAL_NODATA)
    return TiffInfo(
        path=path,
        width=width,
        height=height,
        bands=bands,
        dtype=dtype,
        compression=compression,
        nodata=float(nodata) if nodata else None,
        pixel_scale=(scale[0], scale[1]) if scale else None,
        # tiepoint 是 (I, J, K, X, Y, Z)：像素 (I, J) 对应地图 (X, Y)。本数据集 I=J=0。
        origin=(tiepoint[3], tiepoint[4]) if tiepoint else None,
        block_size=block_size,
        block_offsets=tuple(offsets),
        block_byte_counts=tuple(counts),
        tiled=tiled,
        byteorder=byteorder,
    )


def _read_ifd(path: Path, stream, offset: int, byteorder: str) -> dict[int, tuple | str]:
    """只读第一个 IFD。patch 与对齐影像都是单幅，没有内置金字塔或多页。"""
    stream.seek(offset)
    (count,) = struct.unpack(f"{byteorder}H", stream.read(2))
    entries = stream.read(12 * count)
    tags: dict[int, tuple | str] = {}
    for position in range(0, 12 * count, 12):
        code, kind, n = struct.unpack(
            f"{byteorder}HHI", entries[position : position + 8]
        )
        field = entries[position + 8 : position + 12]
        if kind == _ASCII:
            payload = _payload(path, stream, field, n, byteorder)
            tags[code] = payload.split(b"\0", 1)[0].decode("ascii", "replace").strip()
            continue
        if kind not in _FIELD_TYPES:
            continue  # 不认识的类型只可能出现在我们用不到的标签上
        fmt, size = _FIELD_TYPES[kind]
        payload = _payload(path, stream, field, size * n, byteorder)
        values = struct.unpack(f"{byteorder}{fmt * n}", payload)
        if kind in (5, 10):  # 有理数成对出现
            values = tuple(a / b for a, b in zip(values[::2], values[1::2]))
        tags[code] = values
    return tags


def _payload(path: Path, stream, field: bytes, size: int, byteorder: str) -> bytes:
    """不超过 4 字节的值直接存在目录项里，否则目录项里存的是它的偏移。"""
    if size <= 4:
        return field[:size]
    (offset,) = struct.unpack(f"{byteorder}I", field)
    here = stream.tell()
    stream.seek(offset)
    payload = stream.read(size)
    stream.seek(here)
    if len(payload) != size:
        raise TiffUnreadable(f"TIFF 目录项指向了文件末尾之外：{path}")
    return payload
