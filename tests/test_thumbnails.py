"""ROI 缩略图：从对齐影像逐块降采样、拉伸、写 PNG。"""

import json
import struct
import zlib
from pathlib import Path

import numpy as np
import pytest

from moondata.errors import ThumbnailUnavailable
from moondata.thumbnails import (
    OPTICAL,
    SAR,
    block_mean,
    encode_png,
    generate_thumbnails,
    make_thumbnail,
    stretch,
)
from tiff_fixtures import write_tiff


def decode_png(blob: bytes) -> np.ndarray:
    """只解本模块写出的那一种 PNG：8 位灰度、不交错、每行滤波类型 0。"""
    assert blob[:8] == b"\x89PNG\r\n\x1a\n"
    position, chunks = 8, {}
    while position < len(blob):
        (length,) = struct.unpack(">I", blob[position : position + 4])
        kind = blob[position + 4 : position + 8]
        data = blob[position + 8 : position + 8 + length]
        (crc,) = struct.unpack(">I", blob[position + 8 + length : position + 12 + length])
        assert crc == zlib.crc32(kind + data)
        chunks[kind] = chunks.get(kind, b"") + data
        position += 12 + length
    width, height, depth, colour = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    assert (depth, colour) == (8, 0)
    raw = zlib.decompress(chunks[b"IDAT"])
    rows = np.frombuffer(raw, np.uint8).reshape(height, width + 1)
    assert (rows[:, 0] == 0).all()
    return rows[:, 1:]


def blocks_of(array: np.ndarray, size: int):
    for top in range(0, array.shape[0], size):
        for left in range(0, array.shape[1], size):
            yield top, left, array[top : top + size, left : left + size]


class TestBlockMean:
    def test_matches_a_plain_mean_over_each_cell_whatever_the_block_size(self) -> None:
        values = np.arange(7 * 5, dtype=float).reshape(7, 5)
        valid = np.ones_like(values, dtype=bool)
        for size in (2, 3, 7):
            result = block_mean(
                ((t, l, (v, np.ones_like(v, bool))) for t, l, v in blocks_of(values, size)),
                shape=values.shape,
                step=3,
            )
            assert result.shape == (3, 2)
            assert result[0, 0] == values[0:3, 0:3].mean()
            assert result[2, 1] == values[6:7, 3:5].mean()
        assert valid.all()

    def test_invalid_pixels_are_left_out_and_an_all_invalid_cell_is_nan(self) -> None:
        values = np.array([[1.0, 100.0], [3.0, 5.0]])
        valid = np.array([[True, False], [False, False]])
        result = block_mean([(0, 0, (values, valid))], shape=(2, 2), step=1)
        assert result[0, 0] == 1.0
        assert np.isnan(result[1, 1])


class TestStretch:
    def test_percentiles_map_to_the_ends_and_nan_to_black(self) -> None:
        image = np.array([[0.0, 1.0, 2.0, np.nan]])
        pixels, (low, high) = stretch(image, percentiles=(0, 100))
        assert (low, high) == (0.0, 2.0)
        assert pixels.tolist() == [[0, 128, 255, 0]]

    def test_a_flat_image_does_not_divide_by_zero(self) -> None:
        pixels, _ = stretch(np.full((2, 2), 7.0))
        assert pixels.dtype == np.uint8


def test_png_round_trips() -> None:
    pixels = (np.arange(12 * 5) % 256).astype(np.uint8).reshape(5, 12)
    np.testing.assert_array_equal(decode_png(encode_png(pixels)), pixels)


class TestMakeThumbnail:
    def test_optical_is_shrunk_to_fit_the_long_side(self, tmp_path: Path) -> None:
        image = np.full((40, 10), 50, np.uint8)
        image[:20] = 200
        path = write_tiff(tmp_path / "opt.tif", image, tile=(8, 8))
        thumb = make_thumbnail(path, OPTICAL, max_side=8)
        assert thumb.step == 5
        assert thumb.pixels.shape == (8, 2)
        assert thumb.source_size == (10, 40)
        assert thumb.pixels[0, 0] > thumb.pixels[-1, 0]

    def test_sar_is_total_power_in_decibels_and_skips_nodata(self, tmp_path: Path) -> None:
        image = np.zeros((4, 4, 4), np.float32)  # nodata = 0
        image[:2, :, 0] = 0.5
        image[:2, :, 1] = 0.5  # H + V = 1 → 0 dB
        image[2:, :, 0] = 5.0
        image[2:, :, 1] = 5.0  # → 10 dB
        image[3, 3] = 0.0  # 一个无效像素
        path = write_tiff(tmp_path / "sar.tif", image, tile=(4, 4))
        thumb = make_thumbnail(path, SAR, max_side=4)
        assert thumb.stretch == pytest.approx((0.0, 10.0))

    def test_a_file_with_no_valid_pixel_is_an_error(self, tmp_path: Path) -> None:
        path = write_tiff(tmp_path / "opt.tif", np.zeros((4, 4), np.uint8), tile=(4, 4))
        with pytest.raises(ThumbnailUnavailable, match="有效像素"):
            make_thumbnail(path, OPTICAL, max_side=4)


def test_generate_writes_pngs_and_a_manifest(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    aligned = raw / "ROI_6" / "cropped" / "ce2"
    write_tiff(aligned / "opt.tif", np.arange(64, dtype=np.uint8).reshape(8, 8) + 1, tile=(4, 4))
    write_tiff(aligned / "sar.tif", np.full((8, 8, 4), 2.0, np.float32), tile=(4, 4))
    out = tmp_path / "thumbs"

    manifest = generate_thumbnails(
        tmp_path, {"ROI_006": "ROI_6", "ROI_014": "ROI_14"}, out, max_side=4, generated_at="T"
    )

    assert (out / "ROI_006_optical.png").is_file()
    assert (out / "ROI_006_sar.png").is_file()
    written = json.loads((out / "thumbnails.json").read_text(encoding="utf-8"))
    assert written == manifest
    entry = manifest["rois"]["ROI_006"]["optical"]
    assert entry["file"] == "ROI_006_optical.png"
    assert entry["source"] == "raw/ROI_6/cropped/ce2/opt.tif"
    assert entry["step"] == 2
    assert manifest["generated_at"] == "T"
    assert manifest["missing"] == {"ROI_014": ["raw/ROI_14/cropped/ce2/opt.tif", "raw/ROI_14/cropped/ce2/sar.tif"]}
