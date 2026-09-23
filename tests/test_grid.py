"""几何层：对齐影像的像素网格怎么定——重叠区、外扩、取整。纯 numpy，不需要 GDAL。

期望值是手算的；「与数据盘上既有网格一致」这件事由 `moondata overlap --verify`
在真实数据上端到端地检验，不在这里。
"""

from __future__ import annotations

import pytest

from moondata.errors import NoOverlap
from moondata.geometry import LonLatBox, PixelGrid, overlap_region, reference_tile


class TestLonLatBox:
    def test_a_span_across_180_becomes_continuous(self) -> None:
        """坐标变换给出的经度区间跨 180° 时是 `west > east`，要接成一个连续区间。"""
        box = LonLatBox.from_bounds(178.0, -10.0, -178.0, 10.0)
        assert (box.west, box.east) == (178.0, 182.0)


class TestOverlapRegion:
    def test_intersection_expanded_about_its_centre(self) -> None:
        optical = [LonLatBox(100.0, -30.0, 108.0, -20.0)]
        sar = LonLatBox(102.0, -40.0, 103.0, -24.0)
        # 交集 lon [102, 103]、lat [-30, -24]；各向外扩 10%（总宽的 1.2 倍）
        got = overlap_region(optical, sar, expand=1.2)
        assert got == pytest.approx(LonLatBox(101.9, -30.6, 103.1, -23.4))

    def test_tiles_are_unioned_first(self) -> None:
        tiles = [LonLatBox(0.0, 0.0, 8.0, 7.0), LonLatBox(0.0, 7.0, 8.0, 14.0)]
        sar = LonLatBox(3.0, 5.0, 4.0, 9.0)
        assert overlap_region(tiles, sar, expand=1.0) == pytest.approx(sar)

    def test_sar_on_the_other_side_of_the_antimeridian(self) -> None:
        """旧代码在 0–360 与 ±180 之间来回换算，跨 0° 或 180° 经线的 ROI 会得到空交集
        或者绕月一圈的范围。这里只整体平移 360° 的整数倍再求交，结果中心归一到 ±180 内。"""
        optical = [LonLatBox(176.0, 0.0, 184.0, 7.0)]
        sar = LonLatBox(-179.0, 2.0, -178.0, 5.0)
        assert overlap_region(optical, sar, expand=1.0) == pytest.approx(
            LonLatBox(-179.0, 2.0, -178.0, 5.0)
        )

    def test_across_the_prime_meridian(self) -> None:
        optical = [LonLatBox(-7.0, -66.0, 1.0, -60.0)]
        sar = LonLatBox(351.0, -70.0, 355.0, -62.0)  # 即 [-9°, -5°]
        assert overlap_region(optical, sar, expand=1.0) == pytest.approx(
            LonLatBox(-7.0, -66.0, -5.0, -62.0)
        )

    def test_disjoint_footprints_are_an_error(self) -> None:
        with pytest.raises(NoOverlap):
            overlap_region([LonLatBox(0.0, 0.0, 8.0, 7.0)], LonLatBox(20.0, 0.0, 21.0, 7.0))


class TestPixelGrid:
    def test_roi_6_worked_example(self) -> None:
        """ROI_6 的交集外扩后投到 CE-2 墨卡托里的范围，与数据盘上既有 `opt.tif` 的网格对照：
        宽 3621.598 → 3622、高 12748.227 → 12748，原点取左上角。"""
        bounds = (4063284.545346473, -695639.2197453816, 4090446.5315861404, -600027.5154862015)
        grid = PixelGrid.covering("WKT", bounds, 7.5)
        assert (grid.width, grid.height) == (3622, 12748)
        assert grid.geotransform == pytest.approx(
            (4063284.545346473, 7.5, 0.0, -600027.5154862015, 0.0, -7.5)
        )

    @pytest.mark.parametrize(("extent_px", "expected"), [(10.4, 10), (10.6, 11)])
    def test_size_is_rounded_to_nearest(self, extent_px: float, expected: int) -> None:
        grid = PixelGrid.covering("WKT", (0.0, 0.0, extent_px * 7.5, extent_px * 7.5), 7.5)
        assert (grid.width, grid.height) == (expected, expected)

    def test_bounds_follow_the_rounded_size(self) -> None:
        grid = PixelGrid("WKT", origin_x=100.0, origin_y=50.0, resolution=7.5, width=4, height=2)
        assert grid.bounds == (100.0, 35.0, 130.0, 50.0)


class TestGridDifferences:
    GRID = PixelGrid("WKT", origin_x=4063284.5, origin_y=-600027.5, resolution=7.5, width=3622, height=12748)

    def test_identical_grids_have_no_differences(self) -> None:
        assert self.GRID.differences(self.GRID) == []

    def test_a_one_row_difference_is_reported(self) -> None:
        other = self.GRID._replace(height=12749)
        assert any("高" in d and "12749" in d for d in self.GRID.differences(other))

    def test_a_sub_pixel_origin_shift_is_reported_in_metres(self) -> None:
        """ROI_65 那种 0.27 m 的原点偏差：不到 1/20 像素，照样要报出来。"""
        other = self.GRID._replace(origin_y=self.GRID.origin_y + 0.267)
        assert any("原点" in d and "0.267" in d for d in self.GRID.differences(other))

    def test_float_noise_in_the_pixel_size_is_not_a_difference(self) -> None:
        """盘上 ROI_52 的像元写成 7.499999999999902——是 GDAL 算出来的浮点噪声，不是另一个网格。"""
        other = self.GRID._replace(resolution=7.499999999999902)
        assert self.GRID.differences(other) == []


class TestReferenceTile:
    def test_the_tile_covering_most_of_the_sar_wins(self) -> None:
        """ROI_65：I 带分幅只擦到条带北端，J 带分幅盖住大半——网格用 J 带的投影。"""
        tiles = [LonLatBox(100.0, -28.0, 108.0, -21.0), LonLatBox(99.0, -35.0, 108.0, -28.0)]
        sar = LonLatBox(102.0, -40.0, 103.4, -24.0)
        assert reference_tile(tiles, sar) == 1

    def test_ties_keep_the_first_tile(self) -> None:
        tiles = [LonLatBox(0.0, 0.0, 8.0, 7.0), LonLatBox(0.0, 7.0, 8.0, 14.0)]
        assert reference_tile(tiles, LonLatBox(3.0, 5.0, 4.0, 9.0)) == 0
