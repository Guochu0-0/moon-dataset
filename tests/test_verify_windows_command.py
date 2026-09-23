"""`moondata verify-windows`：第一级验收的命令行行为。不读影像、不要数据盘。

正向结果由 `write_window_manifest` 写出（与 `moondata windows` 同一个写入函数），
清单按真实文件的格式手写——两边格式若有一处对不上，这里就会失败。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from moondata.cli import main
from moondata.geometry import PixelGrid
from moondata.manifest import ManifestRoi, ManifestWindow, write_window_manifest

GRID = PixelGrid("WKT", 4063284.545346474, -600027.5154862015, 7.5, 3622, 12748)
WINDOWS = [(0, [1024, 1536], [466, 1628]), (1, [1536, 1536], [935, 1629]), (2, [2048, 1536], [1404, 1629])]


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MOONDATA_DATA_ROOT", raising=False)
    grid = {"width": 3622, "height": 12748, "crs": "WKT",
            "transform": [7.5, 0.0, 4063284.545346474, 0.0, -7.5, -600027.5154862015]}
    patches = [{"index": i, "optical": o, "sar": s} for i, o, s in WINDOWS]
    document = {"patch_size": 512, "aligned_name": "cropped", "rois": {
        "ROI_006": {"grid": grid, "split": "Test", "roi": 6, "patches": patches, "unresolved": []},
        "ROI_001": {"grid": grid, "split": "Train", "roi": 1, "patches": patches, "unresolved": []},
    }}
    (tmp_path / "data" / "windows").mkdir(parents=True)
    (tmp_path / "data" / "windows" / "windows.json").write_text(json.dumps(document), encoding="utf-8")
    return tmp_path


def _forward(repo: Path, windows=WINDOWS, roi: str = "ROI_006") -> None:
    record = ManifestRoi(roi, "Test", 512, GRID,
                         [ManifestWindow(i, tuple(o), tuple(s)) for i, o, s in windows])
    write_window_manifest(repo / "work" / "windows" / f"{roi}.json", record, {"model": "affine"})


def test_a_forward_result_equal_to_the_manifest_passes(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _forward(repo)
    assert main(["verify-windows"]) == 0
    out = capsys.readouterr().out
    assert "ROI_006" in out and "逐条一致" in out
    assert "1/1" in out


def test_the_default_gate_is_validation_and_test_only(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _forward(repo)  # ROI_001 是训练集，没有正向结果也不拦
    assert main(["verify-windows"]) == 0
    assert "ROI_001" not in capsys.readouterr().out


def test_a_shifted_window_is_reported_by_roi_index_and_pixels(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _forward(repo, [WINDOWS[0], (1, [1536, 1536], [936, 1629]), WINDOWS[2]])
    assert main(["verify-windows", "6"]) == 1
    out = capsys.readouterr().out
    assert "ROI_006" in out
    assert "patch_1" in out
    assert "SAR 差 (+1, +0)" in out


def test_an_extra_window_is_named(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _forward(repo, [WINDOWS[0], (1, [512, 1536], [0, 1628]),
                    (2, [1536, 1536], [935, 1629]), (3, [2048, 1536], [1404, 1629])])
    assert main(["verify-windows", "ROI_006"]) == 1
    out = capsys.readouterr().out
    assert "正向多出 patch_1" in out
    assert "编号变了" in out


def test_a_missing_forward_result_fails_with_the_command_to_run(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["verify-windows"]) == 1
    assert "moondata windows ROI_006" in capsys.readouterr().out
