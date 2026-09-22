"""`moondata scan`：一条命令扫描真实数据、写出统计快照。"""

import json
from pathlib import Path

import numpy as np
import pytest

from moondata.cli import main
from moondata.config import load_config
from moondata.snapshot import compute_fingerprint, load_snapshot
from tiff_fixtures import write_tiff


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    windows = root / "data" / "windows"
    windows.mkdir(parents=True)
    (windows / "windows.json").write_text(
        json.dumps(
            {
                "patch_size": 4,
                "rois": {
                    "ROI_035": {
                        "split": "Val",
                        "patches": [{"index": 0, "optical": [0, 0], "sar": [0, 0]}],
                        "unresolved": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    metadata = root / "data" / "metadata"
    metadata.mkdir(parents=True)
    (metadata / "removed_ROI_060_manifest.txt").write_text(
        "# 已删除: Processed_Data/Val/ROI_060\n# 原因: 重复\n# 删除日期: 2026-09-20\n"
        "./Optical/patch_0.tif\n./SAR/patch_0.tif\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(root)
    monkeypatch.delenv("MOONDATA_DATA_ROOT", raising=False)
    return root


@pytest.fixture
def drive(tmp_path: Path) -> Path:
    root = tmp_path / "drive"
    patch = root / "Processed_Data" / "Val" / "ROI_035"
    write_tiff(patch / "Optical" / "patch_0.tif", np.full((4, 4), 9, np.uint8))
    write_tiff(patch / "SAR" / "patch_0.tif", np.full((4, 4, 4), -1.5, np.float32))
    (patch / "Label").mkdir()
    (patch / "Label" / "patch_0.txt").write_text("1\t-2\t3\t-4\n", encoding="utf-8")
    (root / "raw" / "ROI_35").mkdir(parents=True)
    (root / "raw" / "ROI_35" / "opt.tif").write_bytes(b"xx")
    return root


def test_writes_a_snapshot_with_time_fingerprint_and_stats(
    repo: Path, drive: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["scan", "--data-root", str(drive)]) == 0

    snapshot = load_snapshot(load_config(env={}, start=repo).snapshot_path)
    assert snapshot is not None
    assert snapshot.generated_at[:4].isdigit() and "T" in snapshot.generated_at
    assert snapshot.fingerprint == compute_fingerprint(drive)
    counts = snapshot.stats["counts"]
    assert counts["excluding_removed"]["Val"]["patch_count"] == 1
    assert counts["including_removed"]["Val"]["patch_count"] == 2
    assert snapshot.stats["window_manifests"]["files"] == ["windows.json"]
    assert snapshot.stats["images"]["SAR"]["patches_with_negative"] == 1
    assert str(repo / "stats" / "snapshot.json") in capsys.readouterr().out


def test_doctor_agrees_with_a_fresh_snapshot(repo: Path, drive: Path) -> None:
    assert main(["scan", "--data-root", str(drive)]) == 0
    assert main(["doctor", "--data-root", str(drive)]) == 0


def test_refuses_cleanly_when_the_drive_is_detached(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    absent = tmp_path / "absent-drive"
    assert main(["scan", "--data-root", str(absent)]) == 1
    captured = capsys.readouterr()
    assert str(absent) in captured.err
    assert "Traceback" not in captured.err
    assert not (repo / "stats" / "snapshot.json").exists()


def test_a_drive_without_products_is_an_error_not_an_empty_snapshot(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """插错了盘时写出一份全是 0 的快照，比报错糟糕得多。"""
    wrong = tmp_path / "wrong-drive"
    wrong.mkdir()
    assert main(["scan", "--data-root", str(wrong)]) == 1
    assert "Processed_Data" in capsys.readouterr().err
    assert not (repo / "stats" / "snapshot.json").exists()
