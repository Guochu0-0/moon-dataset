"""第三步：由对齐控制点求全局变换，并与既有窗口清单对照。不需要 GDAL，也不需要数据盘。

「求出的变换与既有结果一致」在这里有一个不读影像的判据：清单里每个窗口的 SAR 位置，
当年就是拿光学窗口四角经全局变换后的中心定的。所以用我们求出的变换重算中心，
它与清单的偏差只能来自取整——落在 [0, 2) 像素内（取整方式本身由 issue #9 复现）。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from moondata.geometry import TransformModel
from moondata.manifest import load_window_manifests
from moondata.tiepoints import TiePoints, load_tie_points
from moondata.transform import compare_with_manifest, solve

REPO = Path(__file__).resolve().parents[1]
MANIFESTS = sorted((REPO / "data" / "windows").glob("*.json"))


def _tie_points(shift: tuple[float, float]) -> TiePoints:
    optical = np.array([[0.0, 0.0], [3000.0, 50.0], [2900.0, 9000.0], [40.0, 8800.0]])
    return TiePoints("ROI_001", Path("opt_tie.pts"), optical, optical + shift)


def _manifest(tmp_path: Path, windows: list[dict]) -> Path:
    grid = {"width": 4000, "height": 9000, "transform": [7.5, 0, 0, 0, -7.5, 0], "crs": "WKT"}
    document = {
        "patch_size": 512,
        "rois": {"ROI_001": {"grid": grid, "split": "Test", "roi": 1, "patches": windows}},
    }
    path = tmp_path / "windows.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class TestSolve:
    def test_defaults_to_the_affine_model_used_for_the_dataset(self) -> None:
        solved = solve(_tie_points((10.3, 20.7)))
        assert solved.model is TransformModel.AFFINE
        np.testing.assert_allclose(solved.matrix[:2, 2], [10.3, 20.7], atol=1e-9)
        assert solved.rmse == pytest.approx(0.0, abs=1e-9)

    def test_the_model_can_be_chosen(self) -> None:
        assert solve(_tie_points((1.0, 1.0)), TransformModel.RIGID).model is TransformModel.RIGID


class TestCompareWithManifest:
    def test_windows_within_rounding_of_the_prediction_are_consistent(self, tmp_path: Path) -> None:
        # 平移 (10.3, 20.7)：窗口 (0, 0) 的 SAR 连续位置是 (10.3, 20.7)，清单写的是取整后的 (10, 20)
        path = _manifest(tmp_path, [{"index": 0, "optical": [0, 0], "sar": [10, 20]}])
        roi = load_window_manifests([path])["ROI_001"]
        result = compare_with_manifest(solve(_tie_points((10.3, 20.7))), roi)
        assert result.consistent
        assert result.dx_range == pytest.approx((0.3, 0.3))
        assert result.dy_range == pytest.approx((0.7, 0.7))

    def test_an_offending_window_is_named_with_its_deviation(self, tmp_path: Path) -> None:
        path = _manifest(
            tmp_path,
            [
                {"index": 0, "optical": [0, 0], "sar": [10, 20]},
                {"index": 7, "optical": [512, 0], "sar": [525, 20]},  # 应为 522
            ],
        )
        roi = load_window_manifests([path])["ROI_001"]
        result = compare_with_manifest(solve(_tie_points((10.3, 20.7))), roi)
        assert not result.consistent
        [offender] = result.outliers
        assert offender.index == 7
        assert (offender.dx, offender.dy) == pytest.approx((-2.7, 0.7))


class TestCommittedTransformsMatchTheDataset:
    """用仓库里的对齐控制点求变换，逐窗口对照仓库里的窗口清单——每个 ROI 都要一致。"""

    MANIFEST = load_window_manifests(MANIFESTS)

    @pytest.mark.parametrize("roi", sorted(set(MANIFEST) - {"ROI_073"}))
    def test_every_window_agrees(self, roi: str) -> None:
        result = compare_with_manifest(solve(load_tie_points(REPO, roi)), self.MANIFEST[roi])
        assert result.consistent, result.outliers[:3]

    def test_roi_73_is_the_known_exception(self) -> None:
        """清单里 ROI_73 的窗口是按当年**错误的**标注（实为 ROI_74）算的，正确标注在
        `cropped_2/`，所以它对不上是预期内的（见 data/README.md）。"""
        result = compare_with_manifest(
            solve(load_tie_points(REPO, "ROI_073")), self.MANIFEST["ROI_073"]
        )
        assert not result.consistent

    def test_both_manifests_are_covered(self) -> None:
        assert len(self.MANIFEST) == 68
