"""几何层：窗口生成。纯 numpy，不要 GDAL、不要数据盘。

规则取自当年真正产出数据集的脚本（`image_patch_cropping.py` 的
`generate_aligned_patches`），期望值一律按那份脚本的写法手算，不照着本包的实现推。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from moondata.geometry import grid_windows, plan_windows, sar_window
from moondata.manifest import load_window_manifests
from moondata.tiepoints import load_tie_points
from moondata.transform import solve


def _affine(a: float = 1.0, b: float = 0.0, tx: float = 0.0,
            c: float = 0.0, d: float = 1.0, ty: float = 0.0) -> np.ndarray:
    """x' = a·x + b·y + tx，y' = c·x + d·y + ty。"""
    return np.array([[a, b, tx], [c, d, ty], [0.0, 0.0, 1.0]])


class TestGridWindows:
    def test_starts_at_the_origin_and_steps_by_the_patch_size_row_by_row(self) -> None:
        assert grid_windows(width=1024, height=1024, size=512) == [
            (0, 0), (512, 0), (0, 512), (512, 512),
        ]

    def test_an_edge_remainder_one_pixel_short_of_a_window_is_dropped(self) -> None:
        assert grid_windows(width=1023, height=512, size=512) == [(0, 0)]

    def test_the_remainder_is_dropped_without_padding_or_shifting(self) -> None:
        # 1535 = 2 × 512 + 511：第三列差一个像素，不补边、也不往回挪去贴右边
        assert grid_windows(width=1535, height=512, size=512) == [(0, 0), (512, 0)]

    def test_an_exact_multiple_keeps_the_last_window_flush_with_the_edge(self) -> None:
        assert grid_windows(width=1536, height=512, size=512)[-1] == (1024, 0)

    def test_an_image_smaller_than_one_patch_has_no_windows(self) -> None:
        assert grid_windows(width=511, height=4096, size=512) == []

    def test_rows_and_columns_are_dropped_independently(self) -> None:
        windows = grid_windows(width=1100, height=1600, size=512)
        assert {x for x, _ in windows} == {0, 512}
        assert {y for _, y in windows} == {0, 512, 1024}

    @pytest.mark.parametrize("size", [0, -512])
    def test_a_non_positive_size_is_refused(self, size: int) -> None:
        with pytest.raises(ValueError):
            grid_windows(width=1024, height=1024, size=size)


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


class TestPlanWindows:
    def test_pairs_every_grid_window_with_its_sar_window_in_grid_order(self) -> None:
        plan = plan_windows((1024, 512), (2048, 2048), _affine(tx=10.3, ty=20.7), size=512)
        assert [(w.optical, w.sar) for w in plan.windows] == [
            ((0, 0), (10, 20)), ((512, 0), (522, 20)),
        ]
        assert (plan.out_of_bounds, plan.low_overlap) == (0, 0)

    def test_a_sar_window_past_the_right_or_bottom_edge_is_dropped(self) -> None:
        # SAR 宽 1034：第一格落在 x=10、右缘 522 在内；第二格右缘 1034 恰好贴边也在内
        # SAR 宽 1033：第二格右缘 1034 越界
        assert len(plan_windows((1024, 512), (1034, 600), _affine(tx=10.3), 512).windows) == 2
        plan = plan_windows((1024, 512), (1033, 600), _affine(tx=10.3), 512)
        assert [w.optical for w in plan.windows] == [(0, 0)]
        assert plan.out_of_bounds == 1

    def test_a_sar_window_past_the_left_or_top_edge_is_dropped(self) -> None:
        plan = plan_windows((1024, 512), (4096, 4096), _affine(tx=-300.0), 512)
        assert [w.optical for w in plan.windows] == [(512, 0)]
        assert plan.out_of_bounds == 1

    def test_a_window_whose_warped_quad_covers_too_little_of_the_sar_window_is_dropped(self) -> None:
        # 缩小 0.8 倍：变换后的四边形约 409×409，只占 512² 窗口的约 64%，低于 0.7
        plan = plan_windows((512, 512), (4096, 4096), _affine(a=0.8, d=0.8, tx=500, ty=500), 512)
        assert plan.windows == []
        assert plan.low_overlap == 1

    def test_a_quad_covering_just_over_the_threshold_is_kept(self) -> None:
        # 缩小 0.85 倍：约 435×435，约占 72%
        plan = plan_windows((512, 512), (4096, 4096), _affine(a=0.85, d=0.85, tx=500, ty=500), 512)
        assert len(plan.windows) == 1

    def test_the_overlap_threshold_can_be_set(self) -> None:
        matrix = _affine(a=0.85, d=0.85, tx=500, ty=500)
        assert plan_windows((512, 512), (4096, 4096), matrix, 512, min_overlap=0.75).windows == []

    def test_a_rotated_quad_counts_only_its_part_inside_the_sar_window(self) -> None:
        # 绕窗口中心转 45°：交集是正八边形，面积 (2√2 − 2)·512² ≈ 0.83·512²，留下；
        # 阈值抬到 0.84 就丢
        c, s = np.cos(np.pi / 4), np.sin(np.pi / 4)
        cx = cy = 1000.0
        matrix = _affine(a=c, b=-s, c=s, d=c,
                         tx=cx - (c * 256 - s * 256), ty=cy - (s * 256 + c * 256))
        assert len(plan_windows((512, 512), (4096, 4096), matrix, 512).windows) == 1
        assert plan_windows((512, 512), (4096, 4096), matrix, 512, min_overlap=0.84).windows == []


REPO = Path(__file__).resolve().parents[1]
MANIFEST = load_window_manifests(sorted((REPO / "data" / "windows").glob("*.json")))


class TestCommittedWindowsLieOnTheForwardGeometry:
    """真实数据上的几何半边：清单里每个窗口都必须是正向铺窗、定位之后的候选之一，
    SAR 坐标**逐像素相等**，且先后顺序不变——清单只能比候选少（被像素检查丢掉的），
    不能多、不能挪。不读影像，秒级跑完全部 ROI。

    编号（也就是哪些候选被像素检查丢掉）要读筛选影像，由 `moondata verify-windows` 验收。
    网格尺寸这里取自清单——测试只借它的宽高，正向命令用的是自己规划出的网格。
    """

    @pytest.mark.parametrize("roi", sorted(set(MANIFEST) - {"ROI_073"}))
    def test_every_manifest_window_is_a_candidate_in_order(self, roi: str) -> None:
        record = MANIFEST[roi]
        size = (record.grid.width, record.grid.height)
        matrix = solve(load_tie_points(REPO, roi)).matrix
        candidates = [(w.optical, w.sar) for w in plan_windows(size, size, matrix, 512).windows]
        position = {pair: i for i, pair in enumerate(candidates)}
        found = [position.get((w.optical, w.sar)) for w in record.windows]
        assert None not in found, [w for w, i in zip(record.windows, found) if i is None][:3]
        assert found == sorted(found)
