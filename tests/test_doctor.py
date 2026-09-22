"""自检：数据根解析到哪、是否可达、与统计快照的指纹是否一致。"""

import json
from pathlib import Path

import pytest

from moondata.config import load_config
from moondata.doctor import Reachability, SnapshotCheck, format_report, run_doctor
from moondata.snapshot import compute_fingerprint


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    return tmp_path


@pytest.fixture
def imagery(tmp_path: Path) -> Path:
    """一块「插着」的盘。"""
    root = tmp_path / "drive"
    (root / "ROI_1").mkdir(parents=True)
    (root / "ROI_1" / "opt.tif").write_text("xx", encoding="utf-8")
    return root


def write_snapshot(repo: Path, digest: str, file_count: int, total_bytes: int) -> Path:
    path = repo / "stats" / "snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-09-22T12:00:00+08:00",
                "fingerprint": {
                    "digest": digest,
                    "file_count": file_count,
                    "total_bytes": total_bytes,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def config_for(repo: Path, root: Path | str | None):
    env = {} if root is None else {"MOONDATA_DATA_ROOT": str(root)}
    return load_config(env=env, start=repo)


class TestDriveAttached:
    def test_reports_reachable(self, repo: Path, imagery: Path) -> None:
        report = run_doctor(config_for(repo, imagery))
        assert report.reachability is Reachability.REACHABLE
        assert report.data_root == imagery

    def test_no_snapshot_yet_is_not_a_failure(self, repo: Path, imagery: Path) -> None:
        report = run_doctor(config_for(repo, imagery))
        assert report.snapshot_check is SnapshotCheck.NO_SNAPSHOT
        assert report.ok

    def test_matching_fingerprint(self, repo: Path, imagery: Path) -> None:
        actual = compute_fingerprint(imagery)
        write_snapshot(repo, actual.digest, actual.file_count, actual.total_bytes)
        report = run_doctor(config_for(repo, imagery))
        assert report.snapshot_check is SnapshotCheck.MATCH
        assert report.ok

    def test_mismatching_fingerprint_fails_and_shows_both_sides(
        self, repo: Path, imagery: Path
    ) -> None:
        write_snapshot(repo, "sha256:stale", 999, 12345)
        report = run_doctor(config_for(repo, imagery))
        assert report.snapshot_check is SnapshotCheck.MISMATCH
        assert not report.ok
        text = format_report(report)
        assert "sha256:stale" in text
        assert "999" in text


class TestDriveDetached:
    def test_missing_root_is_reported_cleanly(self, repo: Path, tmp_path: Path) -> None:
        absent = tmp_path / "G_drive_not_plugged_in"
        report = run_doctor(config_for(repo, absent))
        assert report.reachability is Reachability.MISSING
        assert not report.ok
        text = format_report(report)
        assert str(absent) in text
        assert "不可达" in text

    def test_fingerprint_is_skipped_rather_than_attempted(
        self, repo: Path, tmp_path: Path
    ) -> None:
        write_snapshot(repo, "sha256:whatever", 1, 1)
        report = run_doctor(config_for(repo, tmp_path / "absent"))
        assert report.snapshot_check is SnapshotCheck.SKIPPED

    def test_a_file_where_a_directory_belongs(self, repo: Path, tmp_path: Path) -> None:
        impostor = tmp_path / "root.txt"
        impostor.write_text("x", encoding="utf-8")
        report = run_doctor(config_for(repo, impostor))
        assert report.reachability is Reachability.NOT_A_DIRECTORY
        assert not report.ok


class TestUnset:
    def test_unset_root_explains_how_to_set_it(self, repo: Path) -> None:
        report = run_doctor(config_for(repo, None))
        assert report.reachability is Reachability.UNSET
        assert not report.ok
        text = format_report(report)
        assert "MOONDATA_DATA_ROOT" in text
        assert "moondata.toml" in text


class TestReportText:
    def test_always_names_the_resolved_path_and_where_it_came_from(
        self, repo: Path, imagery: Path
    ) -> None:
        text = format_report(run_doctor(config_for(repo, imagery)))
        assert str(imagery) in text
        assert "MOONDATA_DATA_ROOT" in text

    def test_names_the_snapshot_path(self, repo: Path, imagery: Path) -> None:
        text = format_report(run_doctor(config_for(repo, imagery)))
        assert "snapshot.json" in text
