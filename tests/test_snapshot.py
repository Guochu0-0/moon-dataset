"""数据指纹与统计快照的读取。"""

import json
from pathlib import Path

import pytest

from moondata.errors import DataRootUnavailable, SnapshotUnreadable
from moondata.snapshot import (
    Fingerprint,
    Snapshot,
    compute_fingerprint,
    load_snapshot,
    write_snapshot,
)


def make_tree(root: Path, files: dict[str, str]) -> None:
    for relpath, content in files.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


class TestFingerprint:
    def test_counts_files_and_bytes(self, tmp_path: Path) -> None:
        make_tree(tmp_path, {"a.tif": "xx", "roi/b.tif": "yyy"})
        fingerprint = compute_fingerprint(tmp_path)
        assert fingerprint.file_count == 2
        assert fingerprint.total_bytes == 5
        assert fingerprint.digest.startswith("sha256:")

    def test_is_stable_across_calls(self, tmp_path: Path) -> None:
        make_tree(tmp_path, {"a.tif": "xx", "roi/b.tif": "yyy"})
        assert compute_fingerprint(tmp_path) == compute_fingerprint(tmp_path)

    def test_is_independent_of_where_the_tree_lives(self, tmp_path: Path) -> None:
        """换一块盘、换一个挂载点，指纹不该变——否则它没法跨机器比对。"""
        make_tree(tmp_path / "here", {"a.tif": "xx"})
        make_tree(tmp_path / "there", {"a.tif": "xx"})
        assert (
            compute_fingerprint(tmp_path / "here").digest
            == compute_fingerprint(tmp_path / "there").digest
        )

    def test_changes_when_a_file_is_added(self, tmp_path: Path) -> None:
        make_tree(tmp_path, {"a.tif": "xx"})
        before = compute_fingerprint(tmp_path)
        make_tree(tmp_path, {"b.tif": "zz"})
        assert compute_fingerprint(tmp_path) != before

    def test_changes_when_a_file_changes_size(self, tmp_path: Path) -> None:
        make_tree(tmp_path, {"a.tif": "xx"})
        before = compute_fingerprint(tmp_path)
        make_tree(tmp_path, {"a.tif": "xxx"})
        assert compute_fingerprint(tmp_path) != before

    def test_ignores_content_edits_that_preserve_size(self, tmp_path: Path) -> None:
        """指纹刻画的是目录形态，不是像素内容——955 GB 不可能逐字节哈希。"""
        make_tree(tmp_path, {"a.tif": "xx"})
        before = compute_fingerprint(tmp_path)
        make_tree(tmp_path, {"a.tif": "yy"})
        assert compute_fingerprint(tmp_path) == before

    def test_missing_root_is_reported_not_crashed(self, tmp_path: Path) -> None:
        with pytest.raises(DataRootUnavailable):
            compute_fingerprint(tmp_path / "no-such-drive")


class TestLoadSnapshot:
    def test_missing_snapshot_is_none(self, tmp_path: Path) -> None:
        assert load_snapshot(tmp_path / "snapshot.json") is None

    def test_reads_fingerprint_and_generation_time(self, tmp_path: Path) -> None:
        path = tmp_path / "snapshot.json"
        path.write_text(
            json.dumps(
                {
                    "generated_at": "2026-09-22T12:00:00+08:00",
                    "fingerprint": {
                        "digest": "sha256:abc",
                        "file_count": 2,
                        "total_bytes": 5,
                    },
                }
            ),
            encoding="utf-8",
        )
        snapshot = load_snapshot(path)
        assert snapshot is not None
        assert snapshot.generated_at == "2026-09-22T12:00:00+08:00"
        assert snapshot.fingerprint == Fingerprint("sha256:abc", 2, 5)

    def test_malformed_snapshot_names_itself(self, tmp_path: Path) -> None:
        path = tmp_path / "snapshot.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(SnapshotUnreadable) as excinfo:
            load_snapshot(path)
        assert str(path) in str(excinfo.value)

    def test_snapshot_without_a_fingerprint_names_itself(self, tmp_path: Path) -> None:
        path = tmp_path / "snapshot.json"
        path.write_text(json.dumps({"generated_at": "now"}), encoding="utf-8")
        with pytest.raises(SnapshotUnreadable) as excinfo:
            load_snapshot(path)
        assert str(path) in str(excinfo.value)


class TestWriteSnapshot:
    def test_round_trips_generation_time_fingerprint_and_stats(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "stats" / "snapshot.json"
        written = Snapshot(
            generated_at="2026-09-23T10:00:00+08:00",
            fingerprint=Fingerprint("sha256:abc", 2, 5),
            stats={"counts": {"Val": {"patch_count": 3}}, "note": "中文"},
        )
        write_snapshot(path, written)
        assert load_snapshot(path) == written

    def test_is_committed_text_with_readable_chinese_and_a_final_newline(
        self, tmp_path: Path
    ) -> None:
        """快照要提交进 git，diff 得能看。"""
        path = tmp_path / "snapshot.json"
        write_snapshot(
            path, Snapshot("now", Fingerprint("sha256:abc", 2, 5), {"note": "中文"})
        )
        text = path.read_text(encoding="utf-8")
        assert "中文" in text
        assert text.endswith("}\n")
        assert "\n  " in text

    def test_older_snapshot_without_stats_still_loads(self, tmp_path: Path) -> None:
        path = tmp_path / "snapshot.json"
        path.write_text(
            json.dumps(
                {
                    "generated_at": "now",
                    "fingerprint": {"digest": "sha256:a", "file_count": 1, "total_bytes": 1},
                }
            ),
            encoding="utf-8",
        )
        snapshot = load_snapshot(path)
        assert snapshot is not None
        assert snapshot.stats == {}
