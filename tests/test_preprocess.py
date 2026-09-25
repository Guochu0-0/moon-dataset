"""输入表示：`sar_input`、`optical_input` 的输出。纯 numpy，不要数据盘。

期望值由 dB 与常数手算：S1 = 10^(dB/10)，z = (dB − μ) / σ。
"""

from __future__ import annotations

import numpy as np
import pytest

from moondata.preprocess import optical_input, sar_input


def _bands(s1: list[list[float]], cross: float = 0.0) -> np.ndarray:
    """总功率为 `s1` 的 4 波段 patch：功率平分给 H、V 两路，交叉功率取常数。"""
    half = np.asarray(s1, np.float32) / 2
    return np.stack([half, half, np.full_like(half, cross), np.full_like(half, -cross)])


def test_sar_standardizes_s1_db_with_training_constants():
    # dB：μ、μ + σ、μ − 2σ、−3
    s1 = [[10 ** (-10.976 / 10), 10 ** (-8.265 / 10)], [10 ** (-16.398 / 10), 10 ** (-0.3)]]
    z = sar_input(_bands(s1))
    assert z.shape == (2, 2) and z.dtype == np.float32
    np.testing.assert_allclose(z, [[0.0, 1.0], [-2.0, 7.976 / 2.711]], atol=1e-5)


def test_sar_floors_at_minus_25_db_including_non_positive_values():
    s1 = [[10 ** (-30 / 10), 0.0], [-0.01, 10 ** (-25 / 10)]]
    floor = (-25 + 10.976) / 2.711  # ≈ −5.173
    np.testing.assert_allclose(sar_input(_bands(s1)), np.full((2, 2), floor), atol=1e-5)


def test_sar_does_not_clip_bright_values():
    # 10 dB，比训练集任何像素都亮
    assert sar_input(_bands([[10.0]]))[0, 0] == pytest.approx((10 + 10.976) / 2.711, abs=1e-5)


def test_sar_ignores_cross_power():
    s1 = [[0.05, 0.2]]
    np.testing.assert_array_equal(sar_input(_bands(s1)), sar_input(_bands(s1, cross=-0.3)))


def test_sar_rejects_other_shapes():
    with pytest.raises(ValueError):
        sar_input(np.ones((2, 4, 4), np.float32))
    with pytest.raises(ValueError):
        sar_input(np.ones((4, 4), np.float32))


def test_optical_standardizes_gray_levels():
    z = optical_input(np.array([[0, 1], [74, 255]], np.uint8))
    assert z.shape == (2, 2) and z.dtype == np.float32
    expected = (np.array([[0, 1], [74, 255]]) - 73.786) / 26.533
    np.testing.assert_allclose(z, expected, atol=1e-5)
    assert z[1, 1] == pytest.approx(6.8298, abs=1e-4)


def test_optical_rejects_non_uint8_and_other_shapes():
    with pytest.raises(ValueError):
        optical_input(np.zeros((4, 4), np.float32))
    with pytest.raises(ValueError):
        optical_input(np.zeros((1, 4, 4), np.uint8))
