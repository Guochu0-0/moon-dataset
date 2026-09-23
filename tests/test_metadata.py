"""Mini-RF 逐 ROI 元数据表的读取。"""

from pathlib import Path

import pytest

from moondata.errors import MetadataUnreadable
from moondata.metadata import load_metadata, padded_roi

HEADER = "ROI,划分,PRODUCT_ID,入射角_deg\n"


def write_csv(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "minirf_metadata.csv"
    # 真实文件是 UTF-8 with BOM（Excel 另存的），BOM 不能混进第一个列名
    path.write_bytes(("﻿" + HEADER + body).encode("utf-8"))
    return path


def test_rows_keep_every_column_in_file_order(tmp_path: Path) -> None:
    rows = load_metadata(write_csv(tmp_path, "ROI_6,Test,LSZ_02833,51.2\n"))
    assert [(r.roi, r.raw_name, r.split) for r in rows] == [("ROI_006", "ROI_6", "Test")]
    assert list(rows[0].fields) == ["ROI", "划分", "PRODUCT_ID", "入射角_deg"]
    assert rows[0].fields["PRODUCT_ID"] == "LSZ_02833"


def test_rows_are_sorted_by_roi_number_not_by_text(tmp_path: Path) -> None:
    rows = load_metadata(write_csv(tmp_path, "ROI_10,Train,a,1\nROI_9,Train,b,1\n"))
    assert [r.roi for r in rows] == ["ROI_009", "ROI_010"]


@pytest.mark.parametrize("name, expected", [("ROI_6", "ROI_006"), ("ROI_060", "ROI_060")])
def test_padded_roi(name: str, expected: str) -> None:
    assert padded_roi(name) == expected


def test_an_unrecognised_roi_name_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(MetadataUnreadable, match="ROI six"):
        load_metadata(write_csv(tmp_path, "ROI six,Test,a,1\n"))


def test_a_missing_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(MetadataUnreadable):
        load_metadata(tmp_path / "nope.csv")
