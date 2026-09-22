"""文档页从统计快照取值、排版数字的那几个小工具。"""

import json
from pathlib import Path

import pytest

from moondata.docvalues import (
    dtype_label,
    load_stats_snapshot,
    num,
    pct,
    size,
    table,
)
from moondata.errors import SnapshotUnreadable
from moondata.snapshot import Fingerprint, Snapshot, write_snapshot


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / "docs").mkdir()
    return tmp_path


class TestLoadStatsSnapshot:
    def test_finds_the_snapshot_from_a_page_inside_the_repo(self, repo: Path) -> None:
        """Quarto 以 .qmd 所在目录为工作目录执行代码，页面可能在 docs/ 下。"""
        written = Snapshot("t", Fingerprint("sha256:a", 1, 1), {"counts": {}})
        write_snapshot(repo / "stats" / "snapshot.json", written)
        assert load_stats_snapshot(repo / "docs") == written

    def test_missing_snapshot_fails_the_render(self, repo: Path) -> None:
        """宁可渲染失败，也不能渲染出一页没有数字的文档。"""
        with pytest.raises(SnapshotUnreadable, match="moondata scan"):
            load_stats_snapshot(repo / "docs")

    def test_snapshot_without_stats_fails_the_render(self, repo: Path) -> None:
        path = repo / "stats" / "snapshot.json"
        path.parent.mkdir()
        path.write_text(
            json.dumps(
                {
                    "generated_at": "t",
                    "fingerprint": {"digest": "sha256:a", "file_count": 1, "total_bytes": 1},
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(SnapshotUnreadable, match="moondata scan"):
            load_stats_snapshot(repo)


class TestFormatting:
    def test_num_groups_thousands(self) -> None:
        assert num(22934) == "22,934"
        assert num(7) == "7"

    def test_num_keeps_floats_short(self) -> None:
        assert num(-0.52088827) == "-0.5209"
        assert num(7.5) == "7.5"

    def test_pct(self) -> None:
        assert pct(1605, 1966) == "81.6%"
        assert pct(0, 0) == "—"

    def test_size(self) -> None:
        assert size(39_600_000_000) == "36.9 GiB"
        assert size(2048) == "2.0 KiB"

    def test_dtype_label(self) -> None:
        assert dtype_label("uint8") == "8 位无符号整型（`uint8`）"
        assert dtype_label("float32") == "32 位浮点（`float32`）"
        assert dtype_label("int16") == "16 位有符号整型（`int16`）"

    def test_table(self) -> None:
        assert table(["划分", "ROI"], [["Train", 54], ["Val", 6]]) == (
            "| 划分 | ROI |\n|---|---|\n| Train | 54 |\n| Val | 6 |"
        )

    def test_table_right_aligns_numbers(self) -> None:
        assert table(["ROI", "patch"], [["ROI_1", 3]], align="lr").splitlines()[1] == (
            "|:---|---:|"
        )
