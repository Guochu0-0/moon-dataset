"""第四步的两块纯逻辑：像素检查（窗口留不留），与第一级验收的逐条比对。

都不读影像、不要 GDAL：前者吃数组，后者吃两份窗口记录。
"""

from __future__ import annotations

import numpy as np

from moondata.geometry import PixelGrid
from moondata.manifest import ManifestRoi, ManifestWindow
from moondata.patches import compare_windows, usable_pair

GRID = PixelGrid("WKT", 100.0, 200.0, 7.5, 4000, 9000)


def _optical(value: int = 80) -> np.ndarray:
    return np.full((1, 4, 4), value, np.uint8)


def _sar(value: float = 0.05) -> np.ndarray:
    return np.full((4, 4, 4), value, np.float32)


class TestUsablePair:
    def test_a_pair_without_zeros_is_kept(self) -> None:
        assert usable_pair(_optical(), _sar())

    def test_one_zero_pixel_in_the_optical_patch_drops_the_pair(self) -> None:
        optical = _optical()
        optical[0, 3, 3] = 0
        assert not usable_pair(optical, _sar())

    def test_one_zero_in_a_single_sar_band_drops_the_pair(self) -> None:
        # 当年的 SAR 检查是「任一波段任一像素等于 nodata」，不要求四个波段同时为 0
        sar = _sar()
        sar[2, 0, 1] = 0.0
        assert not usable_pair(_optical(), sar)

    def test_negative_sar_values_are_valid_data(self) -> None:
        assert usable_pair(_optical(), _sar(-0.013))

    def test_a_single_band_optical_patch_may_come_without_a_band_axis(self) -> None:
        assert usable_pair(np.full((4, 4), 80, np.uint8), _sar())


def _roi(windows: list[tuple[int, tuple[int, int], tuple[int, int]]],
         grid: PixelGrid = GRID) -> ManifestRoi:
    return ManifestRoi(
        "ROI_001", "Test", 512, grid,
        [ManifestWindow(index, optical, sar) for index, optical, sar in windows],
    )


class TestCompareWindows:
    WINDOWS = [(0, (0, 0), (10, 20)), (1, (512, 0), (522, 20)), (2, (0, 512), (11, 532))]

    def test_identical_records_are_consistent(self) -> None:
        result = compare_windows(_roi(self.WINDOWS), _roi(self.WINDOWS))
        assert result.consistent
        assert result.windows == 3
        assert result.mismatches == []

    def test_a_shifted_sar_window_is_reported_with_its_index_and_pixel_offset(self) -> None:
        forward = _roi([self.WINDOWS[0], (1, (512, 0), (523, 18)), self.WINDOWS[2]])
        result = compare_windows(forward, _roi(self.WINDOWS))
        assert not result.consistent
        [mismatch] = result.mismatches
        assert mismatch.index == 1
        assert mismatch.optical_offset == (0, 0)
        assert mismatch.sar_offset == (1, -2)  # 正向减清单

    def test_an_extra_forward_window_is_named_and_shifts_the_numbering_after_it(self) -> None:
        forward = _roi([
            self.WINDOWS[0],
            (1, (1024, 0), (1034, 20)),  # 清单里没有的窗口
            (2, (512, 0), (522, 20)),
            (3, (0, 512), (11, 532)),
        ])
        result = compare_windows(forward, _roi(self.WINDOWS))
        assert not result.consistent
        assert [(w.index, w.optical) for w in result.only_forward] == [(1, (1024, 0))]
        assert result.only_manifest == []
        assert result.first_divergence == 1
        # 同一光学位置、编号却不同：清单的 1、2 号在正向里成了 2、3 号
        assert result.renumbered == [(1, 2), (2, 3)]

    def test_a_window_missing_from_the_forward_result_is_named(self) -> None:
        forward = _roi([self.WINDOWS[0], (1, (0, 512), (11, 532))])
        result = compare_windows(forward, _roi(self.WINDOWS))
        assert [(w.index, w.optical) for w in result.only_manifest] == [(1, (512, 0))]
        assert result.first_divergence == 1

    def test_a_different_grid_is_inconsistent_even_if_every_window_agrees(self) -> None:
        wider = GRID._replace(width=4001)
        result = compare_windows(_roi(self.WINDOWS, wider), _roi(self.WINDOWS))
        assert not result.consistent
        assert result.grid_differences

    def test_an_empty_forward_result_is_not_consistent(self) -> None:
        result = compare_windows(_roi([]), _roi(self.WINDOWS))
        assert not result.consistent
        assert result.first_divergence == 0
