"""几何层：由对齐控制点估计全局变换。纯 numpy，不需要 GDAL。

期望值一律来自手写的已知变换（先定矩阵、再造点），不拿被测代码的算法重算一遍。
"""

from __future__ import annotations

import numpy as np
import pytest

from moondata.errors import DegeneratePoints, InsufficientPoints
from moondata.geometry import TransformModel, apply_transform, estimate_transform

# 一组铺满「对齐影像」尺度的点：几千像素量级，不共线。
SRC = np.array(
    [[120.0, 340.0], [3050.5, 410.25], [2980.0, 9120.0], [80.0, 8870.5],
     [1500.0, 4500.0], [2210.75, 1333.0], [640.0, 6002.5]]
)


def _apply(matrix: list[list[float]], points: np.ndarray) -> np.ndarray:
    m = np.asarray(matrix, dtype=float)
    homo = np.column_stack([points, np.ones(len(points))]) @ m.T
    return homo[:, :2] / homo[:, 2:3]


class TestRecoversAKnownTransform:
    def test_affine(self) -> None:
        known = [[1.002, 0.013, -35.5], [-0.004, 0.998, 91.25], [0, 0, 1]]
        got = estimate_transform(SRC, _apply(known, SRC), TransformModel.AFFINE)
        np.testing.assert_allclose(got, known, atol=1e-9)

    def test_rigid(self) -> None:
        c, s = np.cos(np.radians(1.5)), np.sin(np.radians(1.5))
        known = [[c, -s, 12.0], [s, c, -7.5], [0, 0, 1]]
        got = estimate_transform(SRC, _apply(known, SRC), TransformModel.RIGID)
        np.testing.assert_allclose(got, known, atol=1e-9)

    def test_similarity(self) -> None:
        c, s = 0.97 * np.cos(np.radians(-2.0)), 0.97 * np.sin(np.radians(-2.0))
        known = [[c, -s, 300.0], [s, c, 45.0], [0, 0, 1]]
        got = estimate_transform(SRC, _apply(known, SRC), TransformModel.SIMILARITY)
        np.testing.assert_allclose(got, known, atol=1e-9)

    def test_homography(self) -> None:
        """像素坐标上千，不做归一化的 DLT 在这个尺度上会丢好几位精度。"""
        known = [[0.99, 0.02, 15.0], [-0.01, 1.01, -40.0], [2e-6, -1e-6, 1.0]]
        got = estimate_transform(SRC, _apply(known, SRC), TransformModel.HOMOGRAPHY)
        np.testing.assert_allclose(got, known, rtol=1e-7, atol=1e-9)


class TestRigidNeverReflects:
    """刚体是旋转 + 平移。SVD 的 `U·Vᵀ` 在点集近似镜像时会给出 det = −1 的反射矩阵，
    那不是刚体变换——必须拉回到最近的真旋转。"""

    def test_mirrored_points_still_give_a_proper_rotation(self) -> None:
        mirrored = SRC * [-1.0, 1.0]  # 关于 y 轴镜像：只有反射能精确拟合
        got = estimate_transform(SRC, mirrored, TransformModel.RIGID)
        rotation = got[:2, :2]
        np.testing.assert_allclose(rotation @ rotation.T, np.eye(2), atol=1e-12)
        assert np.linalg.det(rotation) == pytest.approx(1.0)

    def test_it_is_the_best_proper_rotation(self) -> None:
        """独立的对照：逐 0.01° 暴力搜索旋转角，取残差最小者——解出的角度应与它一致。"""
        mirrored = SRC * [-1.0, 1.0] + [40.0, -15.0]
        got = estimate_transform(SRC, mirrored, TransformModel.RIGID)
        src_c, dst_c = SRC - SRC.mean(axis=0), mirrored - mirrored.mean(axis=0)

        def cost(theta: float) -> float:
            c, s = np.cos(theta), np.sin(theta)
            return float(((src_c @ np.array([[c, s], [-s, c]]) - dst_c) ** 2).sum())

        angles = np.radians(np.arange(-180.0, 180.0, 0.01))
        best = angles[np.argmin([cost(a) for a in angles])]
        solved = np.arctan2(got[1, 0], got[0, 0])
        assert np.degrees(np.angle(np.exp(1j * (solved - best)))) == pytest.approx(0.0, abs=0.01)


class TestFailsLoudlyInsteadOfDegrading:
    @pytest.mark.parametrize(
        ("model", "minimum"),
        [
            (TransformModel.RIGID, 2),
            (TransformModel.SIMILARITY, 2),
            (TransformModel.AFFINE, 3),
            (TransformModel.HOMOGRAPHY, 4),
        ],
    )
    def test_one_pair_short_of_the_minimum(self, model: TransformModel, minimum: int) -> None:
        src = SRC[: minimum - 1]
        with pytest.raises(InsufficientPoints, match=f"至少需要 {minimum} 对"):
            estimate_transform(src, src + 1.0, model)

    @pytest.mark.parametrize(
        ("model", "minimum"),
        [
            (TransformModel.RIGID, 2),
            (TransformModel.SIMILARITY, 2),
            (TransformModel.AFFINE, 3),
            (TransformModel.HOMOGRAPHY, 4),
        ],
    )
    def test_exactly_the_minimum_is_enough(self, model: TransformModel, minimum: int) -> None:
        src = SRC[:minimum]
        got = estimate_transform(src, src + [5.0, -3.0], model)
        np.testing.assert_allclose(apply_transform(src, got), src + [5.0, -3.0], atol=1e-6)

    @pytest.mark.parametrize("model", [TransformModel.AFFINE, TransformModel.HOMOGRAPHY])
    def test_collinear_points_are_degenerate(self, model: TransformModel) -> None:
        line = np.column_stack([np.arange(6.0) * 100, np.arange(6.0) * 37])
        with pytest.raises(DegeneratePoints):
            estimate_transform(line, line + 2.0, model)

    @pytest.mark.parametrize("model", [TransformModel.RIGID, TransformModel.SIMILARITY])
    def test_coincident_points_are_degenerate(self, model: TransformModel) -> None:
        same = np.full((5, 2), 42.0)
        with pytest.raises(DegeneratePoints):
            estimate_transform(same, same, model)


class TestIllConditionedInput:
    def test_thin_strip_far_from_the_origin(self) -> None:
        """真实 ROI 是 3000×35000 的细长条带，控制点几乎排成一列；再平移到 1e5 量级。
        正规方程在这里把条件数平方，旧代码的解会明显失真。"""
        rng = np.random.default_rng(8)
        src = np.column_stack([rng.uniform(0, 30, 40), rng.uniform(0, 35000, 40)]) + 1e5
        known = [[1.001, 0.002, -12.0], [-0.003, 0.999, 8.0], [0, 0, 1]]
        got = estimate_transform(src, _apply(known, src), TransformModel.AFFINE)
        np.testing.assert_allclose(apply_transform(src, got), _apply(known, src), atol=1e-6)
