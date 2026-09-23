"""`moondata verify-patches`：第二级验收的命令行行为。

读 patch 与对齐影像只用 `moondata.tiff`，所以不要 GDAL；数据根与 `work/` 都用 fixture 造。
三项检查的判据继承自旧的新旧产物比对工具（`compare_to_legacy.py`），次序固定：
位置 → 数据完整性 → 网纹；最后是逐字节。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from moondata.cli import main
from moondata.patches.acceptance import LATTICE_PERIOD, lattice_period
from tiff_fixtures import write_tiff

SIZE = 16
ORIGIN = (1000.0, 5000.0)
RES = 7.5
WINDOWS = [(0, [0, 0], [2, 1]), (1, [16, 0], [18, 1])]


def _patch(path: Path, array: np.ndarray, corner: list[int], **kwargs) -> Path:
    x = ORIGIN[0] + corner[0] * RES
    y = ORIGIN[1] - corner[1] * RES
    return write_tiff(path, array, rows_per_strip=4, strips_last=True,
                      tiepoint=(0.0, 0.0, 0.0, x, y, 0.0), **kwargs)


def _optical(seed: int) -> np.ndarray:
    return (np.random.default_rng(seed).integers(1, 255, (SIZE, SIZE))).astype(np.uint8)


def _sar(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.1, 0.05, (SIZE, SIZE, 4)).astype(np.float32)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """一个仓库、一块数据盘：清单两个窗口、历史产物，以及与之逐字节相同的新产物。"""
    repo, drive = tmp_path / "repo", tmp_path / "drive"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("MOONDATA_DATA_ROOT", str(drive))

    grid = {"width": 40, "height": 40, "crs": "WKT",
            "transform": [RES, 0.0, ORIGIN[0], 0.0, -RES, ORIGIN[1]]}
    patches = [{"index": i, "optical": o, "sar": s} for i, o, s in WINDOWS]
    document = {"patch_size": SIZE, "rois": {
        "ROI_006": {"grid": grid, "split": "Test", "roi": 6, "patches": patches},
        "ROI_001": {"grid": grid, "split": "Train", "roi": 1, "patches": patches},
    }}
    (repo / "data" / "windows").mkdir(parents=True)
    (repo / "data" / "windows" / "windows.json").write_text(json.dumps(document), encoding="utf-8")

    legacy = drive / "Processed_Data" / "Test" / "ROI_006"
    for index, optical, sar in WINDOWS:
        _patch(legacy / "Optical" / f"patch_{index}.tif", _optical(index), optical)
        _patch(legacy / "SAR" / f"patch_{index}.tif", _sar(index), sar)
    shutil.copytree(legacy, repo / "work" / "patches" / "Test" / "ROI_006")

    aligned = np.full((40, 40), 90, np.uint8)
    aligned[:, 30:] = 0
    write_tiff(drive / "raw" / "ROI_6" / "cropped" / "ce2" / "opt.tif", aligned, tile=(16, 16))
    write_tiff(repo / "work" / "aligned" / "ROI_006" / "opt.tif", aligned, tile=(16, 16))
    return repo, drive


def _new(repo: Path, kind: str, index: int) -> Path:
    return repo / "work" / "patches" / "Test" / "ROI_006" / kind / f"patch_{index}.tif"


def test_products_identical_to_the_dataset_pass(
    world: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["verify-patches"]) == 0
    out = capsys.readouterr().out
    assert "ROI_006" in out
    assert "2/2 对逐字节一致" in out
    assert "通过 1/1 个 ROI" in out


def test_the_default_gate_is_validation_and_test_only(
    world: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    main(["verify-patches"])
    assert "ROI_001" not in capsys.readouterr().out


def test_the_three_checks_are_reported_in_their_fixed_order(
    world: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    main(["verify-patches", "6"])
    out = capsys.readouterr().out
    assert out.index("位置") < out.index("数据完整性") < out.index("网纹") < out.index("逐字节")


def test_a_patch_moved_by_one_pixel_is_named_as_misplaced(
    world: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = world
    _patch(_new(repo, "SAR", 1), _sar(1), [19, 1])
    assert main(["verify-patches", "6"]) == 1
    out = capsys.readouterr().out
    assert "位置错 1 个" in out
    assert "patch_1" in out


def test_a_missing_patch_is_counted(
    world: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = world
    _new(repo, "Optical", 0).unlink()
    assert main(["verify-patches", "6"]) == 1
    assert "缺 1 个" in capsys.readouterr().out


def test_data_valid_in_the_old_aligned_image_but_empty_in_the_new_is_lost(
    world: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    # 旧图有效 40 × 30 = 1200 像素，新图丢掉其中 40 × 6 = 240 个：20%
    repo, _ = world
    thinner = np.full((40, 40), 90, np.uint8)
    thinner[:, 24:] = 0
    write_tiff(repo / "work" / "aligned" / "ROI_006" / "opt.tif", thinner, tile=(16, 16))
    assert main(["verify-patches", "6"]) == 1
    assert "丢数据 20.0%" in capsys.readouterr().out


def test_same_pixels_in_a_different_deflate_stream_are_not_byte_identical(
    world: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = world
    _patch(_new(repo, "Optical", 1), _optical(1), [16, 0], zlevel=1)
    assert main(["verify-patches", "6"]) == 1
    out = capsys.readouterr().out
    assert "1/2 对逐字节一致" in out
    assert "位置错" not in out and "内容不符" not in out


def test_a_missing_forward_result_fails_with_the_command_to_run(
    world: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = world
    shutil.rmtree(repo / "work" / "patches")
    assert main(["verify-patches"]) == 1
    assert "moondata patches ROI_006" in capsys.readouterr().out


def test_an_roi_deleted_from_the_dataset_is_named_and_left_out_of_the_gate(
    world: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = world
    manifest = repo / "data" / "windows" / "windows.json"
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["rois"]["ROI_060"] = {**document["rois"]["ROI_006"], "split": "Val", "roi": 60}
    manifest.write_text(json.dumps(document), encoding="utf-8")
    (repo / "data" / "metadata").mkdir(parents=True)
    (repo / "data" / "metadata" / "removed_ROI_060_manifest.txt").write_text(
        "# 已删除: Processed_Data/Val/ROI_060\n# 原因: 与 Test/ROI_037 逐像素相同\n"
        "# 删除日期: 2026-09-20\n./Optical/patch_0.tif\n./SAR/patch_0.tif\n",
        encoding="utf-8",
    )
    assert main(["verify-patches"]) == 0
    out = capsys.readouterr().out
    assert "ROI_060" in out and "已删除" in out
    assert "通过 1/1 个 ROI" in out


class TestLatticePeriod:
    def test_nearest_neighbour_7_to_7_5_m_locks_onto_14_rows(self) -> None:
        # 7.0 m → 7.5 m 最近邻：每 14 行输出里有一行源数据被跳过，梯度在那里突变
        terrain = np.random.default_rng(0).normal(0, 1, (600, 64)).cumsum(axis=0)
        source_rows = np.floor(np.arange(512) * 7.5 / 7.0).astype(int)
        assert lattice_period(terrain[source_rows]) == LATTICE_PERIOD

    def test_a_constant_patch_has_no_period(self) -> None:
        assert lattice_period(np.full((64, 64), 7, np.uint8)) == 0
