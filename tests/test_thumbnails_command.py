"""`moondata thumbnails`：接上数据盘，为元数据表里的每个 ROI 画缩略图。"""

import json
from pathlib import Path

import numpy as np
import pytest

from moondata.cli import main
from tiff_fixtures import write_tiff


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    metadata = root / "data" / "metadata"
    metadata.mkdir(parents=True)
    (metadata / "minirf_metadata.csv").write_text(
        "ROI,划分\nROI_6,Test\nROI_60,已删除\n", encoding="utf-8"
    )
    monkeypatch.chdir(root)
    monkeypatch.delenv("MOONDATA_DATA_ROOT", raising=False)
    return root


def test_draws_every_roi_in_the_metadata_table(repo: Path, tmp_path: Path) -> None:
    drive = tmp_path / "drive"
    aligned = drive / "raw" / "ROI_6" / "cropped" / "ce2"
    write_tiff(aligned / "opt.tif", np.arange(16, dtype=np.uint8).reshape(4, 4) + 1)
    write_tiff(aligned / "sar.tif", np.full((4, 4, 4), 3.0, np.float32))

    assert main(["thumbnails", "--data-root", str(drive)]) == 0

    out = repo / "docs" / "rois" / "thumbnails"
    assert (out / "ROI_006_optical.png").is_file()
    manifest = json.loads((out / "thumbnails.json").read_text(encoding="utf-8"))
    assert list(manifest["rois"]) == ["ROI_006"]
    assert list(manifest["missing"]) == ["ROI_060"]


def test_refuses_cleanly_when_the_drive_is_detached(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["thumbnails", "--data-root", str(tmp_path / "absent")]) == 1
    assert "Traceback" not in capsys.readouterr().err
    assert not (repo / "docs" / "rois" / "thumbnails").exists()


def test_pages_command_needs_no_drive(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """档案页的输入都在仓库里——没有快照时要报「去 scan」，而不是报数据根。"""
    assert main(["pages"]) == 1
    err = capsys.readouterr().err
    assert "moondata scan" in err
    assert "Traceback" not in err
