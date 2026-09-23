"""第二步：读入仓库里的对齐控制点。不需要 GDAL，也不需要数据盘。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from moondata.errors import TiePointsUnreadable
from moondata.tiepoints import load_tie_points

REPO = Path(__file__).resolve().parents[1]

ENVI_HEADER = (
    "; ENVI Image to Image GCP File\n"
    "; base file: F:\\多元数据集\\ROI_2\\cropped\\ce2\\opt.tif\n"
    "; warp file: F:\\多元数据集\\ROI_2\\cropped\\ce2\\sar.tif\n"
    "; Base Image (x,y), Warp Image (x,y)\n"
    ";\n"
)


def _write_pts(path: Path, rows: list[tuple[float, ...]], *, encoding: str = "gbk") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join("  ".join(f"{v:.2f}" for v in row) + "\n" for row in rows)
    path.write_bytes((ENVI_HEADER + body).replace("\n", "\r\n").encode(encoding))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return tmp_path


class TestReadsEnviPts:
    def test_gbk_paths_in_the_header_do_not_stop_the_read(self, repo: Path) -> None:
        """ENVI 用系统代码页写头部注释里的路径，中文 Windows 上是 GBK 而不是 UTF-8。"""
        _write_pts(
            repo / "data/tie-points/ROI_2/cropped/opt_tie.pts",
            [(10.5, 20.25, 12.0, 19.0, 1.0), (300.0, 400.0, 301.5, 398.0, 1.0),
             (50.0, 900.0, 52.0, 897.5, 1.0)],
        )
        points = load_tie_points(repo, "ROI_2")
        np.testing.assert_array_equal(points.optical, [[10.5, 20.25], [300.0, 400.0], [50.0, 900.0]])
        np.testing.assert_array_equal(points.sar, [[12.0, 19.0], [301.5, 398.0], [52.0, 897.5]])

    def test_y_is_taken_as_written(self, repo: Path) -> None:
        """`.pts` 不取负 y（与标签文件不同），读进来原样就是向下为正的行号。"""
        _write_pts(repo / "data/tie-points/ROI_2/cropped/opt_tie.pts", [(1.0, 2.0, 3.0, 4.0, 1.0)])
        assert load_tie_points(repo, "ROI_2").optical[0, 1] == 2.0

    def test_a_non_numeric_data_row_is_an_error(self, repo: Path) -> None:
        path = repo / "data/tie-points/ROI_2/cropped/opt_tie.pts"
        _write_pts(path, [(1.0, 2.0, 3.0, 4.0, 1.0)])
        path.write_bytes(path.read_bytes() + b"1.0 two 3.0 4.0\r\n")
        with pytest.raises(TiePointsUnreadable, match="opt_tie.pts"):
            load_tie_points(repo, "ROI_2")


class TestPicksTheGenerationUsedForProduction:
    def test_cropped_is_the_default(self, repo: Path) -> None:
        _write_pts(repo / "data/tie-points/ROI_9/cropped/opt_tie.pts", [(1.0, 1.0, 1.0, 1.0, 1.0)])
        _write_pts(repo / "data/tie-points/ROI_9/cropped_1/opt_tie.pts", [(9.0, 9.0, 9.0, 9.0, 1.0)])
        points = load_tie_points(repo, "ROI_009")
        assert points.path.parent.name == "cropped"
        assert points.roi == "ROI_009"

    def test_a_relabelled_cropped_2_supersedes_cropped(self, repo: Path) -> None:
        """ROI_73 的 `cropped/` 实为 ROI_74 的标注，正确的标注在 `cropped_2/`。"""
        _write_pts(repo / "data/tie-points/ROI_73/cropped/opt_tie.pts", [(1.0, 1.0, 1.0, 1.0, 1.0)])
        _write_pts(repo / "data/tie-points/ROI_73/cropped_2/opt_tie.pts", [(2.0, 2.0, 2.0, 2.0, 1.0)])
        assert load_tie_points(repo, "ROI_73").path.parent.name == "cropped_2"

    def test_the_abandoned_cropped_1_is_never_used(self, repo: Path) -> None:
        _write_pts(repo / "data/tie-points/ROI_9/cropped_1/opt_tie.pts", [(9.0, 9.0, 9.0, 9.0, 1.0)])
        with pytest.raises(TiePointsUnreadable, match="ROI_9"):
            load_tie_points(repo, "ROI_9")


class TestCommittedTiePoints:
    def test_every_dataset_roi_has_readable_tie_points(self) -> None:
        """67 个 ROI 加上已删除的 ROI_60，每个都至少有 19 对（见 data/README.md）。"""
        rois = sorted(p.name for p in (REPO / "data/tie-points").iterdir())
        assert len(rois) == 68
        for roi in rois:
            assert len(load_tie_points(REPO, roi).optical) >= 19, roi
