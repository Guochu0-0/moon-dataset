"""ROI 档案页：从元数据表、统计快照、缩略图清单与已知问题清单批量生成。"""

from pathlib import Path

import pytest

from moondata.errors import MetadataUnreadable
from moondata.metadata import MetadataRow
from moondata.roipages import (
    KnownIssue,
    RoiPageInputs,
    load_known_issues,
    render_pages,
    write_pages,
)
from moondata.snapshot import Fingerprint, Snapshot

RANGE = "实测有效分辨率_距离向_m"


def row(n: int, split: str = "Train", range_m: str = "18.0", **fields: str) -> MetadataRow:
    columns = {
        "ROI": f"ROI_{n}",
        "划分": split,
        "PRODUCT_ID": f"LSZ_{n:05d}_2CD_EKU_00N000_V1",
        "入射角_deg": "51.20",
        "视向": "LEFT",
        "条带宽_px": "3287",
        "条带长_px": "55819",
        RANGE: range_m,
        **fields,
    }
    return MetadataRow(f"ROI_{n:03d}", f"ROI_{n}", split, columns)


def snapshot(rois: dict, removed: list | None = None) -> Snapshot:
    return Snapshot(
        "2026-09-23T07:25:37+08:00",
        Fingerprint("sha256:abc", 1, 1),
        {"rois": rois, "removed_rois": removed or []},
    )


ISSUES_TOML = '''
[[issue]]
title = "明显的局部错位"
rois = ["ROI_6", "ROI_050"]
text = "重叠面积偏小。"
source = "2026-09-11 会话"

[issue.details]
ROI_50 = "约 1 km。"
'''


@pytest.fixture
def issues(tmp_path: Path):
    path = tmp_path / "known-issues.toml"
    path.write_text(ISSUES_TOML, encoding="utf-8")
    return load_known_issues(path)


@pytest.fixture
def inputs(issues) -> RoiPageInputs:
    return RoiPageInputs(
        metadata=[
            row(6, "Test"),
            row(50),
            row(60, "已删除(与ROI_37重复)"),
            row(7, "Test"),
        ],
        snapshot=snapshot(
            {
                "ROI_006": {"split": "Test", "patch_count": 152, "labeled_patch_count": 130, "label_point_count": 1234},
                "ROI_007": {"split": "Test", "patch_count": 10, "labeled_patch_count": 0, "label_point_count": 0},
                "ROI_050": {"split": "Train", "patch_count": 40, "labeled_patch_count": 0, "label_point_count": 0},
            },
            [{"roi": "ROI_060", "split": "Val", "patch_count": 152, "labeled_patch_count": 145}],
        ),
        issues=issues,
        thumbnails={
            "generated_at": "2026-09-23T08:10:00+08:00",
            "percentiles": [2.0, 98.0],
            "rois": {
                "ROI_006": {
                    "optical": {
                        "file": "ROI_006_optical.png", "source": "raw/ROI_6/cropped/ce2/opt.tif",
                        "source_size": [3622, 12748], "step": 22, "shown": "灰度值",
                        "stretch": [65.3, 111.76], "unit": "",
                    },
                    "sar": {
                        "file": "ROI_006_sar.png", "source": "raw/ROI_6/cropped/ce2/sar.tif",
                        "source_size": [3622, 12748], "step": 22, "shown": "H + V 总功率（dB）",
                        "stretch": [-13.58, -5.22], "unit": " dB",
                    },
                }
            },
            "missing": {},
        },
        tiepoint_dirs={"ROI_6", "ROI_60"},
    )


class TestKnownIssues:
    def test_roi_names_are_normalised_and_details_attach_to_their_roi(self, issues) -> None:
        misaligned = issues[0]
        assert misaligned.rois == ("ROI_006", "ROI_050")
        assert misaligned.details == {"ROI_050": "约 1 km。"}

    def test_a_detail_for_a_roi_the_issue_does_not_list_is_an_error(self, tmp_path: Path) -> None:
        """多半是抄错了编号——宁可生成失败，也不让一句说明悄悄挂到别的页面上或丢掉。"""
        path = tmp_path / "known-issues.toml"
        path.write_text(
            ISSUES_TOML.replace('ROI_50 = "约 1 km。"', 'ROI_51 = "约 1 km。"'), encoding="utf-8"
        )
        with pytest.raises(MetadataUnreadable, match="ROI_051"):
            load_known_issues(path)

    def test_a_missing_field_is_an_error(self, tmp_path: Path) -> None:
        path = tmp_path / "known-issues.toml"
        path.write_text('[[issue]]\ntitle = "x"\nrois = ["ROI_1"]\n', encoding="utf-8")
        with pytest.raises(MetadataUnreadable, match="text"):
            load_known_issues(path)


class TestPages:
    def test_one_page_per_dataset_roi_plus_the_overview_and_none_for_the_deleted_one(self, inputs) -> None:
        pages = render_pages(inputs)
        assert sorted(pages) == [
            "ROI_006.md", "ROI_007.md", "ROI_050.md", "index.md",
        ]

    def test_a_page_carries_metadata_counts_coverage_and_thumbnails(self, inputs) -> None:
        page = render_pages(inputs)["ROI_006.md"]
        assert 'title: "ROI_006"' in page
        assert "测试集" in page
        assert "LSZ_00006_2CD_EKU_00N000_V1" in page
        assert "51.20°" in page
        assert "3,287 × 55,819" in page
        assert "| 152 |" in page
        assert "130 / 152（85.5%）" in page
        assert "1,234" in page
        assert "thumbnails/ROI_006_optical.png" in page
        assert "thumbnails/ROI_006_sar.png" in page
        assert "-13.58 ~ -5.22 dB" in page
        assert "`data/tie-points/ROI_6/`" in page
        assert "明显的局部错位" in page
        assert "2026-09-23T07:25:37+08:00" in page

    def test_details_only_show_on_their_own_roi(self, inputs) -> None:
        pages = render_pages(inputs)
        assert "约 1 km" in pages["ROI_050.md"]
        assert "约 1 km" not in pages["ROI_006.md"]

    def test_training_rois_say_they_have_no_ground_truth_rather_than_zero(self, inputs) -> None:
        page = render_pages(inputs)["ROI_050.md"]
        assert "训练集没有评测真值点" in page

    def test_an_issue_naming_a_roi_outside_the_dataset_is_an_error(self, inputs) -> None:
        """多半是抄错了编号；ROI_60 已删除，也不再有页面可挂。"""
        inputs.issues.append(KnownIssue("x", ("ROI_060",), "y", "z"))
        with pytest.raises(MetadataUnreadable, match="ROI_060"):
            render_pages(inputs)

    def test_a_roi_without_thumbnails_says_why(self, inputs) -> None:
        assert "尚未生成" not in render_pages(inputs)["ROI_006.md"]
        page = render_pages(inputs)["ROI_050.md"]
        assert "没有缩略图" in page

    def test_the_overview_links_every_page(self, inputs) -> None:
        overview = render_pages(inputs)["index.md"]
        for name in ("ROI_006", "ROI_007", "ROI_050"):
            assert f"[{name}]({name}.md)" in overview

    def test_output_is_deterministic(self, inputs) -> None:
        assert render_pages(inputs) == render_pages(inputs)


class TestWritePages:
    def test_writes_changed_pages_and_removes_stale_ones(self, tmp_path: Path) -> None:
        (tmp_path / "ROI_099.md").write_text("old", encoding="utf-8")
        (tmp_path / "known-issues.toml").write_text("keep", encoding="utf-8")
        (tmp_path / "ROI_001.md").write_bytes(b"same\n")

        changed = write_pages(tmp_path, {"ROI_001.md": "same\n", "index.md": "new\n"})

        assert changed == ["index.md", "ROI_099.md"]
        assert not (tmp_path / "ROI_099.md").exists()
        assert (tmp_path / "known-issues.toml").read_text(encoding="utf-8") == "keep"
        assert (tmp_path / "index.md").read_bytes() == b"new\n"
