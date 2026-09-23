"""不依赖任何影像库的 TIFF 读取：光学（uint8 单波段）与 SAR（float32 四波段）。"""

from pathlib import Path

import numpy as np
import pytest

from moondata.errors import TiffUnreadable
from moondata.tiff import iter_blocks, read_info, read_tiff
from tiff_fixtures import write_tiff


def optical(height: int = 20, width: int = 12) -> np.ndarray:
    return (np.arange(height * width) % 251).astype(np.uint8).reshape(height, width)


def sar(height: int = 10, width: int = 6) -> np.ndarray:
    values = np.linspace(-3.5, 9.25, height * width * 4, dtype=np.float32)
    return values.reshape(height, width, 4)


class TestReadsTheDatasetsTwoKindsOfPatch:
    def test_optical_single_band_uint8(self, tmp_path: Path) -> None:
        expected = optical()
        info, array = read_tiff(write_tiff(tmp_path / "opt.tif", expected))
        assert array.shape == (20, 12, 1)
        assert array.dtype == np.uint8
        np.testing.assert_array_equal(array[:, :, 0], expected)
        assert (info.width, info.height, info.bands) == (12, 20, 1)

    def test_sar_four_band_float32_keeps_negative_values(self, tmp_path: Path) -> None:
        expected = sar()
        _, array = read_tiff(write_tiff(tmp_path / "sar.tif", expected))
        assert array.dtype == np.float32
        np.testing.assert_array_equal(array, expected)
        assert array.min() < 0

    def test_many_strips_with_a_short_last_one(self, tmp_path: Path) -> None:
        """真实光学 patch 是每 16 行一条带；尺寸不整除时最后一条带更短。"""
        expected = optical(height=21)
        _, array = read_tiff(write_tiff(tmp_path / "opt.tif", expected, rows_per_strip=4))
        np.testing.assert_array_equal(array[:, :, 0], expected)

    def test_big_endian(self, tmp_path: Path) -> None:
        expected = sar()
        _, array = read_tiff(write_tiff(tmp_path / "sar.tif", expected, byteorder=">"))
        np.testing.assert_array_equal(array, expected)

    def test_uncompressed(self, tmp_path: Path) -> None:
        expected = optical()
        _, array = read_tiff(write_tiff(tmp_path / "opt.tif", expected, compression=1))
        np.testing.assert_array_equal(array[:, :, 0], expected)


class TestReadsTheTiledAlignedImages:
    """对齐影像（`raw/ROI_*/cropped/ce2/*.tif`）是 256 × 256 分块存储的，宽高不整除。"""

    def test_edge_tiles_are_cropped_to_the_image(self, tmp_path: Path) -> None:
        expected = optical(height=21, width=13)
        _, array = read_tiff(write_tiff(tmp_path / "opt.tif", expected, tile=(8, 16)))
        assert array.shape == (21, 13, 1)
        np.testing.assert_array_equal(array[:, :, 0], expected)

    def test_four_band_float(self, tmp_path: Path) -> None:
        expected = sar(height=10, width=7)
        _, array = read_tiff(write_tiff(tmp_path / "sar.tif", expected, tile=(4, 4)))
        np.testing.assert_array_equal(array, expected)


class TestIterBlocks:
    """缩略图要扫几十 GB 的对齐影像，不能整幅读进内存，所以要能一块一块地走。"""

    def test_blocks_tile_the_image_exactly_once(self, tmp_path: Path) -> None:
        expected = sar(height=10, width=7)
        path = write_tiff(tmp_path / "sar.tif", expected, tile=(4, 4))
        rebuilt = np.full(expected.shape, np.nan, dtype=np.float32)
        for top, left, block in iter_blocks(path):
            assert np.isnan(rebuilt[top : top + block.shape[0], left : left + block.shape[1]]).all()
            rebuilt[top : top + block.shape[0], left : left + block.shape[1]] = block
        np.testing.assert_array_equal(rebuilt, expected)

    def test_strips_are_blocks_too(self, tmp_path: Path) -> None:
        expected = optical(height=21)
        path = write_tiff(tmp_path / "opt.tif", expected, rows_per_strip=4)
        blocks = list(iter_blocks(path))
        assert [(top, left) for top, left, _ in blocks] == [(t, 0) for t in range(0, 21, 4)]
        assert blocks[-1][2].shape == (1, 12, 1)


class TestHeader:
    def test_reports_georeferencing_and_nodata_without_decoding(
        self, tmp_path: Path
    ) -> None:
        info = read_info(
            write_tiff(
                tmp_path / "sar.tif",
                sar(),
                pixel_scale=(7.5, 7.5, 0.0),
                tiepoint=(0.0, 0.0, 0.0, 4066779.5, -612237.5, 0.0),
                nodata="0",
            )
        )
        assert info.dtype == np.dtype(np.float32)
        assert info.bands == 4
        assert info.compression == 8
        assert info.nodata == 0.0
        assert info.pixel_scale == (7.5, 7.5)
        assert info.origin == (4066779.5, -612237.5)

    def test_absent_optional_tags_are_none(self, tmp_path: Path) -> None:
        info = read_info(
            write_tiff(
                tmp_path / "opt.tif", optical(), nodata=None, pixel_scale=None, tiepoint=None
            )
        )
        assert info.nodata is None
        assert info.pixel_scale is None
        assert info.origin is None


class TestRefusesWhatItCannotReadCorrectly:
    """读错的代价是静默的错数字，所以读不了就明说，而不是返回一个看起来正常的数组。"""

    def test_predictor(self, tmp_path: Path) -> None:
        path = write_tiff(tmp_path / "opt.tif", optical(), predictor=2)
        with pytest.raises(TiffUnreadable, match="Predictor"):
            read_tiff(path)

    def test_unknown_compression(self, tmp_path: Path) -> None:
        path = write_tiff(tmp_path / "opt.tif", optical(), compression=5)
        with pytest.raises(TiffUnreadable, match="压缩"):
            read_tiff(path)

    def test_not_a_tiff(self, tmp_path: Path) -> None:
        path = tmp_path / "opt.tif"
        path.write_bytes(b"GIF89a....")
        with pytest.raises(TiffUnreadable) as excinfo:
            read_info(path)
        assert str(path) in str(excinfo.value)

    def test_truncated_file(self, tmp_path: Path) -> None:
        path = write_tiff(tmp_path / "opt.tif", optical())
        path.write_bytes(path.read_bytes()[:40])
        with pytest.raises(TiffUnreadable):
            read_tiff(path)

    def test_corrupt_strip(self, tmp_path: Path) -> None:
        path = write_tiff(tmp_path / "opt.tif", optical())
        blob = bytearray(path.read_bytes())
        blob[10:30] = b"\xff" * 20  # 第一条带的 deflate 数据从偏移 8 开始
        path.write_bytes(bytes(blob))
        with pytest.raises(TiffUnreadable, match="解压"):
            read_tiff(path)
