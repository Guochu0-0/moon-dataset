"""几何层：全部窗口位置与编号的来源。纯 numpy，不要 GDAL、不要数据盘。

期望值按当年那版切片脚本的规则手算，或来自「先定矩阵再造点」的已知变换，不拿被测
代码的算法重算一遍。
"""

from __future__ import annotations

import numpy as np
import pytest

from moondata.errors import DegeneratePoints, InsufficientPoints, NoOverlap
from moondata.geometry import (
    LonLatBox,
    PixelGrid,
    WindowPair,
    apply_transform,
    candidate_windows,
    estimate_affine,
    number_windows,
    overlap_region,
    reference_tile,
    rmse,
    sar_window,
    tile_windows,
    usable_pair,
)


def _affine(a: float = 1.0, b: float = 0.0, tx: float = 0.0,
            c: float = 0.0, d: float = 1.0, ty: float = 0.0) -> np.ndarray:
    """x' = a·x + b·y + tx，y' = c·x + d·y + ty。"""
    return np.array([[a, b, tx], [c, d, ty], [0.0, 0.0, 1.0]])


# 一组铺满重叠区影像尺度的点：几千像素量级，不共线。
SRC = np.array(
    [[120.0, 340.0], [3050.5, 410.25], [2980.0, 9120.0], [80.0, 8870.5],
     [1500.0, 4500.0], [2210.75, 1333.0], [640.0, 6002.5]]
)


def _map(matrix: list[list[float]], points: np.ndarray) -> np.ndarray:
    m = np.asarray(matrix, dtype=float)
    return (np.column_stack([points, np.ones(len(points))]) @ m.T)[:, :2]


class TestEstimateAffine:
    def test_it_recovers_a_known_transform(self) -> None:
        known = [[1.002, 0.013, -35.5], [-0.004, 0.998, 91.25], [0, 0, 1]]
        got = estimate_affine(SRC, _map(known, SRC))
        np.testing.assert_allclose(got, known, atol=1e-9)

    def test_the_last_row_is_always_the_homogeneous_one(self) -> None:
        got = estimate_affine(SRC, _map([[1, 0, 5], [0, 1, -3], [0, 0, 1]], SRC))
        np.testing.assert_allclose(got[2], [0.0, 0.0, 1.0])

    def test_it_is_the_least_squares_fit_when_the_points_disagree(self) -> None:
        """四角的 y 按对角各偏 4 px——仿射拟不出这种鞍形偏差（它需要 x·y 项）。
        对称性决定最小二乘解就是恒等变换，四个点各剩 4 px 残差。"""
        src = np.array([[0.0, 0.0], [1000.0, 0.0], [0.0, 1000.0], [1000.0, 1000.0]])
        dst = src + [[0.0, 4.0], [0.0, -4.0], [0.0, -4.0], [0.0, 4.0]]
        matrix = estimate_affine(src, dst)
        np.testing.assert_allclose(apply_transform(src, matrix), src, atol=1e-9)

    def test_two_pairs_are_not_enough(self) -> None:
        with pytest.raises(InsufficientPoints):
            estimate_affine(SRC[:2], SRC[:2])

    def test_collinear_points_are_refused(self) -> None:
        line = np.array([[0.0, 0.0], [10.0, 20.0], [20.0, 40.0], [30.0, 60.0]])
        with pytest.raises(DegeneratePoints):
            estimate_affine(line, line * 2.0)

    def test_a_mismatched_number_of_points_is_refused(self) -> None:
        with pytest.raises(ValueError):
            estimate_affine(SRC, SRC[:-1])


class TestRmse:
    def test_a_perfect_fit_has_zero_residual(self) -> None:
        known = [[1.002, 0.013, -35.5], [-0.004, 0.998, 91.25], [0, 0, 1]]
        assert rmse(np.asarray(known, float), SRC, _map(known, SRC)) == pytest.approx(0.0)

    def test_it_is_the_root_mean_square_of_the_point_distances(self) -> None:
        """三个点分别差 3、4、0 px：RMSE = √((9 + 16 + 0) / 3)。"""
        src = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]])
        dst = src + [[3.0, 0.0], [0.0, -4.0], [0.0, 0.0]]
        got = rmse(np.eye(3), src, dst)
        assert got == pytest.approx(np.sqrt((9.0 + 16.0 + 0.0) / 3))


class TestApplyTransform:
    def test_it_maps_points_by_the_matrix(self) -> None:
        got = apply_transform([[1.0, 2.0]], _affine(a=2.0, d=3.0, tx=10.0, ty=-1.0))
        np.testing.assert_allclose(got, [[12.0, 5.0]])

    def test_a_matrix_of_the_wrong_shape_is_refused(self) -> None:
        with pytest.raises(ValueError):
            apply_transform([[1.0, 2.0]], np.eye(2))


class TestTileWindows:
    def test_it_starts_at_the_origin_and_steps_by_the_patch_size_row_by_row(self) -> None:
        assert tile_windows(width=1024, height=1024, size=512) == [
            (0, 0), (512, 0), (0, 512), (512, 512),
        ]

    def test_an_edge_remainder_one_pixel_short_of_a_window_is_dropped(self) -> None:
        assert tile_windows(width=1023, height=512, size=512) == [(0, 0)]

    def test_the_remainder_is_dropped_without_padding_or_shifting(self) -> None:
        # 1535 = 2 × 512 + 511：第三列差一个像素，不补边、也不往回挪去贴右边
        assert tile_windows(width=1535, height=512, size=512) == [(0, 0), (512, 0)]

    def test_an_exact_multiple_keeps_the_last_window_flush_with_the_edge(self) -> None:
        assert tile_windows(width=1536, height=512, size=512)[-1] == (1024, 0)

    def test_an_image_smaller_than_one_patch_has_no_windows(self) -> None:
        assert tile_windows(width=511, height=4096, size=512) == []

    def test_rows_and_columns_are_dropped_independently(self) -> None:
        windows = tile_windows(width=1100, height=1600, size=512)
        assert {x for x, _ in windows} == {0, 512}
        assert {y for _, y in windows} == {0, 512, 1024}

    @pytest.mark.parametrize("size", [0, -512])
    def test_a_non_positive_size_is_refused(self, size: int) -> None:
        with pytest.raises(ValueError):
            tile_windows(width=1024, height=1024, size=size)


class TestSarWindow:
    def test_a_pure_shift_lands_on_the_truncated_shift(self) -> None:
        # 四角 (10.3, 20.7) … (522.3, 532.7)，截断后平均 (266, 276)，减 256
        assert sar_window((0, 0), 512, _affine(tx=10.3, ty=20.7)) == (10, 20)

    def test_the_centre_is_truncated_not_rounded(self) -> None:
        # 连续中心减 256 是 (0.9, 0.9)，四舍五入会得 1；当年截断成 0
        assert sar_window((0, 0), 512, _affine(tx=0.9, ty=0.9)) == (0, 0)

    def test_each_corner_is_truncated_before_averaging(self) -> None:
        # x' = x + 0.001·y + 0.6：四角 x 为 0.6、512.6、513.112、1.112
        # 先各自截断 → 0、512、513、1，平均 256.5，减 256 得 0.5，再截断 → 0
        # （若按连续值平均，是 256.856 → 0.856；若四舍五入，得 1）
        assert sar_window((0, 0), 512, _affine(b=0.001, tx=0.6))[0] == 0
        # 同一个变换，窗口右移一格：四角 512.6、1024.6、1025.112、513.112
        # → 512、1024、1025、513，平均 768.5，减 256 得 512.5 → 512
        assert sar_window((512, 0), 512, _affine(b=0.001, tx=0.6))[0] == 512

    def test_truncation_is_towards_zero_so_a_slightly_negative_centre_becomes_zero(self) -> None:
        # 四角 x 为 −0.5、511.5：向零截断得 0、511，平均 255.5，减 256 得 −0.5 → 0。
        # 向下取整会得 −1、窗口出界被丢——当年是 int()，窗口留下了
        assert sar_window((0, 0), 512, _affine(tx=-0.5)) == (0, 0)

    def test_the_far_corners_are_at_x_plus_size_not_x_plus_size_minus_one(self) -> None:
        # 放大 2 倍：四角 (1024, 0)…(2048, 1024)，中心 (1536, 512)，减 256
        assert sar_window((512, 0), 512, _affine(a=2.0, d=2.0)) == (1280, 256)


class TestCandidateWindows:
    def test_it_pairs_every_tiled_window_with_its_sar_window_in_tiling_order(self) -> None:
        plan = candidate_windows((1024, 512), (2048, 2048), _affine(tx=10.3, ty=20.7), size=512)
        assert plan.pairs == [
            WindowPair((0, 0), (10, 20)), WindowPair((512, 0), (522, 20)),
        ]
        assert (plan.out_of_bounds, plan.low_overlap) == (0, 0)

    def test_a_sar_window_past_the_right_or_bottom_edge_is_dropped(self) -> None:
        # SAR 宽 1034：第一格落在 x=10、右缘 522 在内；第二格右缘 1034 恰好贴边也在内
        # SAR 宽 1033：第二格右缘 1034 越界
        assert len(candidate_windows((1024, 512), (1034, 600), _affine(tx=10.3), 512).pairs) == 2
        plan = candidate_windows((1024, 512), (1033, 600), _affine(tx=10.3), 512)
        assert [w.optical for w in plan.pairs] == [(0, 0)]
        assert plan.out_of_bounds == 1

    def test_a_sar_window_past_the_left_or_top_edge_is_dropped(self) -> None:
        plan = candidate_windows((1024, 512), (4096, 4096), _affine(tx=-300.0), 512)
        assert [w.optical for w in plan.pairs] == [(512, 0)]
        assert plan.out_of_bounds == 1

    def test_a_window_whose_warped_quad_covers_too_little_of_the_sar_window_is_dropped(self) -> None:
        # 缩小 0.8 倍：变换后的四边形约 409×409，只占 512² 窗口的约 64%，低于 0.7
        plan = candidate_windows((512, 512), (4096, 4096), _affine(a=0.8, d=0.8, tx=500, ty=500), 512)
        assert plan.pairs == []
        assert plan.low_overlap == 1

    def test_a_quad_covering_just_over_the_threshold_is_kept(self) -> None:
        # 缩小 0.85 倍：约 435×435，约占 72%
        plan = candidate_windows((512, 512), (4096, 4096), _affine(a=0.85, d=0.85, tx=500, ty=500), 512)
        assert len(plan.pairs) == 1

    def test_the_overlap_threshold_can_be_set(self) -> None:
        matrix = _affine(a=0.85, d=0.85, tx=500, ty=500)
        assert candidate_windows((512, 512), (4096, 4096), matrix, 512, min_overlap=0.75).pairs == []

    def test_a_rotated_quad_counts_only_its_part_inside_the_sar_window(self) -> None:
        # 绕窗口中心转 45°：交集是正八边形，面积 (2√2 − 2)·512² ≈ 0.83·512²，留下；
        # 阈值抬到 0.84 就丢
        c, s = np.cos(np.pi / 4), np.sin(np.pi / 4)
        cx = cy = 1000.0
        matrix = _affine(a=c, b=-s, c=s, d=c,
                         tx=cx - (c * 256 - s * 256), ty=cy - (s * 256 + c * 256))
        assert len(candidate_windows((512, 512), (4096, 4096), matrix, 512).pairs) == 1
        assert candidate_windows((512, 512), (4096, 4096), matrix, 512, min_overlap=0.84).pairs == []


class TestUsablePair:
    def test_a_pair_without_a_single_zero_is_usable(self) -> None:
        assert usable_pair(np.ones((1, 4, 4)), np.full((4, 4, 4), -0.5))

    def test_one_zero_pixel_on_either_side_makes_the_pair_unusable(self) -> None:
        optical, sar = np.ones((1, 4, 4)), np.ones((4, 4, 4))
        optical[0, 3, 3] = 0
        assert not usable_pair(optical, np.ones((4, 4, 4)))
        sar[2, 0, 1] = 0
        assert not usable_pair(np.ones((1, 4, 4)), sar)

    def test_negative_sar_values_are_real_data_not_nodata(self) -> None:
        assert usable_pair(np.ones((1, 4, 4)), np.full((4, 4, 4), -3.25))


class TestNumberWindows:
    PAIRS = [
        WindowPair((0, 0), (10, 10)),
        WindowPair((512, 0), (522, 10)),
        WindowPair((0, 512), (10, 522)),
        WindowPair((512, 512), (522, 522)),
    ]

    def test_survivors_are_numbered_from_zero_in_tiling_order(self) -> None:
        got = number_windows(self.PAIRS, usable=lambda pair: True)
        assert [(w.index, w.optical) for w in got] == [
            (0, (0, 0)), (1, (512, 0)), (2, (0, 512)), (3, (512, 512)),
        ]

    def test_a_window_the_pixel_check_rejects_is_dropped_and_the_rest_close_up(self) -> None:
        """编号是评测真值点的钥匙：丢掉第二个窗口，其后的编号必须整体前移，不留空号。"""
        got = number_windows(self.PAIRS, usable=lambda pair: pair.optical != (512, 0))
        assert [(w.index, w.optical) for w in got] == [
            (0, (0, 0)), (1, (0, 512)), (2, (512, 512)),
        ]

    def test_the_pixel_check_can_be_driven_by_a_validity_mask(self) -> None:
        """有效掩膜给成数组：窗口全落在有效区内才留。"""
        valid = np.zeros((1024, 1024), dtype=bool)
        valid[:512, :] = True  # 只有第一行窗口的像素是有效的
        got = number_windows(
            self.PAIRS,
            usable=lambda pair: bool(
                valid[pair.optical[1]:pair.optical[1] + 512, pair.optical[0]:pair.optical[0] + 512].all()
            ),
        )
        assert [w.optical for w in got] == [(0, 0), (512, 0)]

    def test_a_window_in_the_exclusion_table_is_dropped(self) -> None:
        got = number_windows(self.PAIRS, usable=lambda pair: True, excluded={(0, 512)})
        assert [(w.index, w.optical) for w in got] == [
            (0, (0, 0)), (1, (512, 0)), (2, (512, 512)),
        ]

    def test_the_exclusion_table_keys_are_optical_top_left_corners(self) -> None:
        """键是光学窗口左上角 (列, 行)，不是 SAR 的、也不是 (行, 列)。"""
        assert len(number_windows(self.PAIRS, usable=lambda pair: True, excluded={(10, 10)})) == 4
        assert len(number_windows(self.PAIRS, usable=lambda pair: True, excluded={(0, 512)})) == 3

    def test_the_sar_corner_travels_with_the_window(self) -> None:
        got = number_windows(self.PAIRS[1:2], usable=lambda pair: True)
        assert (got[0].optical, got[0].sar) == ((512, 0), (522, 10))


class TestLonLatBox:
    def test_a_span_across_180_becomes_continuous(self) -> None:
        """坐标变换给出的经度区间跨 180° 时是 `west > east`，要接成一个连续区间。"""
        box = LonLatBox.from_bounds(178.0, -10.0, -178.0, 10.0)
        assert (box.west, box.east) == (178.0, 182.0)


class TestOverlapRegion:
    def test_the_intersection_is_expanded_1_2_times_about_its_centre(self) -> None:
        optical = [LonLatBox(100.0, -30.0, 108.0, -20.0)]
        sar = LonLatBox(102.0, -40.0, 103.0, -24.0)
        # 交集 lon [102, 103]、lat [-30, -24]；各向外扩 10%（总宽的 1.2 倍）
        assert overlap_region(optical, sar) == pytest.approx(LonLatBox(101.9, -30.6, 103.1, -23.4))

    def test_tiles_are_unioned_first(self) -> None:
        tiles = [LonLatBox(0.0, 0.0, 8.0, 7.0), LonLatBox(0.0, 7.0, 8.0, 14.0)]
        sar = LonLatBox(3.0, 5.0, 4.0, 9.0)
        assert overlap_region(tiles, sar, expand=1.0) == pytest.approx(sar)

    def test_sar_on_the_other_side_of_the_antimeridian(self) -> None:
        """只整体平移 360° 的整数倍再求交，结果中心归一到 ±180 内。"""
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
    def test_roi_006_worked_example(self) -> None:
        """ROI_006 的重叠区外扩后投到 CE-2 墨卡托里的范围：
        宽 3621.598 → 3622、高 12748.227 → 12748，原点取左上角。"""
        bounds = (4063284.545346473, -695639.2197453816, 4090446.5315861404, -600027.5154862015)
        grid = PixelGrid.covering("WKT", bounds, 7.5)
        assert (grid.width, grid.height) == (3622, 12748)
        assert grid.geotransform == pytest.approx(
            (4063284.545346473, 7.5, 0.0, -600027.5154862015, 0.0, -7.5)
        )

    @pytest.mark.parametrize(("extent_px", "expected"), [(10.4, 10), (10.6, 11)])
    def test_the_size_is_rounded_to_nearest(self, extent_px: float, expected: int) -> None:
        grid = PixelGrid.covering("WKT", (0.0, 0.0, extent_px * 7.5, extent_px * 7.5), 7.5)
        assert (grid.width, grid.height) == (expected, expected)

    def test_bounds_follow_the_rounded_size(self) -> None:
        grid = PixelGrid("WKT", origin_x=100.0, origin_y=50.0, resolution=7.5, width=4, height=2)
        assert grid.bounds == (100.0, 35.0, 130.0, 50.0)


class TestGridDifferences:
    GRID = PixelGrid("WKT", origin_x=4063284.5, origin_y=-600027.5, resolution=7.5,
                     width=3622, height=12748)

    def test_identical_grids_have_no_differences(self) -> None:
        assert self.GRID.differences(self.GRID) == []

    def test_a_one_row_difference_is_reported(self) -> None:
        other = self.GRID._replace(height=12749)
        assert any("高" in d and "12749" in d for d in self.GRID.differences(other))

    def test_a_sub_pixel_origin_shift_is_reported_in_metres(self) -> None:
        other = self.GRID._replace(origin_y=self.GRID.origin_y + 0.267)
        assert any("原点" in d and "0.267" in d for d in self.GRID.differences(other))

    def test_float_noise_in_the_pixel_size_is_not_a_difference(self) -> None:
        """盘上某些影像的像元写成 7.499999999999902——GDAL 的浮点噪声，不是另一个网格。"""
        other = self.GRID._replace(resolution=7.499999999999902)
        assert self.GRID.differences(other) == []


class TestReferenceTile:
    def test_the_tile_covering_most_of_the_sar_wins(self) -> None:
        """I 带分幅只擦到条带北端，J 带分幅盖住大半——网格用 J 带的投影。"""
        tiles = [LonLatBox(100.0, -28.0, 108.0, -21.0), LonLatBox(99.0, -35.0, 108.0, -28.0)]
        sar = LonLatBox(102.0, -40.0, 103.4, -24.0)
        assert reference_tile(tiles, sar) == 1

    def test_ties_keep_the_first_tile(self) -> None:
        tiles = [LonLatBox(0.0, 0.0, 8.0, 7.0), LonLatBox(0.0, 7.0, 8.0, 14.0)]
        assert reference_tile(tiles, LonLatBox(3.0, 5.0, 4.0, 9.0)) == 0
