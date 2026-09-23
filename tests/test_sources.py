"""来源文档用到的解码与汇总：Mini-RF 产品 ID、CE-2 分幅名、条带元数据。"""

from pathlib import Path

import pytest

from moondata.config import METADATA_RELPATH
from moondata.errors import MetadataUnreadable
from moondata.metadata import MetadataRow, dataset_rows, load_metadata
from moondata.sources import (
    CE2_BANDS,
    decode_product_id,
    parse_ce2_tile,
    summarize_strips,
)

REPO = Path(__file__).resolve().parents[1]


class TestProductId:
    def test_decodes_every_segment(self) -> None:
        pid = decode_product_id("LSZ_02319_2CD_EKU_23S131_V1")
        assert pid.orbit == 2319
        assert pid.mode == "Zoom"
        assert pid.level == "Level 2"
        assert pid.projection == "Equirectangular"
        assert pid.bin_ppd == 1024
        assert pid.center_lat == -23
        assert pid.center_lon == 131
        assert pid.version == 1

    def test_segments_cover_the_whole_id_in_order(self) -> None:
        """文档里的解码表逐段列出——拼回去必须是原来的 ID，才算没漏段。"""
        text = "LSZ_02319_2CD_EKU_23S131_V1"
        segments = decode_product_id(text).segments()
        assert "".join(s.code for s in segments) == text.replace("_", "")

    def test_lower_case_file_names_decode_too(self) -> None:
        """数据盘上的 SAR 文件名是小写的（`lsz_02833_2cd_eku_16s144_v1.tif`）。"""
        assert decode_product_id("lsz_02833_2cd_eku_16s144_v1").orbit == 2833

    @pytest.mark.parametrize(
        "text", ["LSZ_2319_2CD_EKU_23S131_V1", "LSQ_02319_2CD_EKU_23S131_V1", "garbage"]
    )
    def test_a_malformed_id_is_an_error(self, text: str) -> None:
        with pytest.raises(MetadataUnreadable, match="产品 ID"):
            decode_product_id(text)


@pytest.fixture(scope="module")
def rows() -> list[MetadataRow]:
    return load_metadata(REPO / METADATA_RELPATH)


class TestCommittedMetadataAgreesWithTheIds:
    """元数据表是从官方标签抄出来的，文件名是另一处独立来源——两者对得上，解码规则才算写对。"""

    def test_orbit_and_mode_match(self, rows) -> None:
        for row in rows:
            pid = decode_product_id(row.fields["PRODUCT_ID"])
            assert pid.orbit == int(row.fields["轨道号"]), row.roi
            assert row.fields["模式"] == "ZOOM_S" and pid.mode == "Zoom", row.roi
            assert pid.projection.upper() == row.fields["投影"], row.roi

    def test_the_resolution_letter_disagrees_with_the_label(self, rows) -> None:
        """文档里说「档位字母不可信」，依据就是这个。哪天它对上了，文档就得改。"""
        for row in rows:
            pid = decode_product_id(row.fields["PRODUCT_ID"])
            assert pid.bin_ppd != float(row.fields["MAP_RESOLUTION_ppd"]), row.roi


class TestCe2Tiles:
    def test_parses_band_row_and_column(self) -> None:
        tile = parse_ce2_tile("CE2_GRAS_DOM_07m_G203_03N161W_A.tif")
        assert (tile.band.letter, tile.row, tile.column) == ("G", 2, 3)

    @pytest.mark.parametrize(
        "name, bounds",
        [
            # 数值是拿 geotransform 反算出来的实测范围（四舍五入到整度或半度）
            ("CE2_GRAS_DOM_07m_G203_03N161W_A", (0, 7, -165, -157.5)),
            ("CE2_GRAS_DOM_07m_H216_10S063W_A", (-14, -7, -67.5, -60)),
            ("CE2_GRAS_DOM_07m_C104_66N127W_A", (63, 70, -135, -120)),
            ("CE2_GRAS_DOM_07m_K236_52S175E_A", (-56, -49, 170, 180)),
            ("CE2_GRAS_DOM_07m_F123_24N000W_A", (21, 28, -4, 4)),
        ],
    )
    def test_bounds_follow_from_the_name(self, name: str, bounds) -> None:
        assert parse_ce2_tile(name).bounds == bounds

    def test_the_name_coordinate_lies_inside_the_tile(self) -> None:
        tile = parse_ce2_tile("CE2_GRAS_DOM_07m_J135_31S130E_A")
        south, north, west, east = tile.bounds
        assert south <= tile.name_lat <= north
        assert west <= tile.name_lon <= east

    def test_bands_tile_the_mercator_zone_without_gaps(self) -> None:
        bands = sorted(CE2_BANDS, key=lambda b: b.south)
        assert bands[0].south == -70 and bands[-1].north == 70
        for lower, upper in zip(bands, bands[1:]):
            assert lower.north == upper.south
        for band in CE2_BANDS:
            assert 360 % band.column_width == 0
            # 标准纬线取在本带正中
            assert abs(band.lat_ts) == abs(band.south + band.north) / 2

    def test_an_unknown_band_is_an_error(self) -> None:
        with pytest.raises(MetadataUnreadable, match="N016"):
            parse_ce2_tile("CE2_GRAS_DOM_07m_N016_85N000W_A")


def strip(n: int, split: str = "Train", **fields: str) -> MetadataRow:
    columns = {
        "ROI": f"ROI_{n}",
        "划分": split,
        "任务阶段": "NOMINAL MISSION",
        "模式": "ZOOM_S",
        "中心频率_GHz": "2.3800",
        "投影": "EQUIRECTANGULAR",
        "MAP_RESOLUTION_ppd": "4096.0",
        "原生采样_m": "7.4032",
        "波段数": "4",
        "入射角_deg": "50.00",
        "视向": "LEFT",
        "条带宽_px": "3000",
        "条带长_px": "50000",
        "成像时刻UTC": "2010-01-01T00:00:00",
        "实测有效分辨率_距离向_m": "18.0",
        "实测有效分辨率_方位向_m": "18.5",
        **fields,
    }
    return MetadataRow(f"ROI_{n:03d}", f"ROI_{n}", split, columns)


class TestStripSummary:
    def test_summarises_the_dataset_rows(self) -> None:
        summary = summarize_strips(
            [
                strip(1, **{"入射角_deg": "45.50", "成像时刻UTC": "2009-11-02T01:00:00"}),
                strip(2, "Test", **{"入射角_deg": "54.90", "视向": "RIGHT"}),
                strip(3, "Val", **{"实测有效分辨率_距离向_m": "43.0", "条带长_px": "20000"}),
            ]
        )
        assert summary.count == 3
        assert summary.distinct["模式"] == ["ZOOM_S"]
        assert summary.distinct["原生采样_m"] == ["7.4032"]
        assert summary.incidence.low == 45.5
        assert summary.incidence.median == 50.0
        assert summary.incidence.high == 54.9
        assert summary.look_directions == {"LEFT": 2, "RIGHT": 1}
        assert summary.range_resolution.high == 43.0
        assert summary.length_px.low == 20000
        assert summary.width_px.median == 3000
        assert summary.first_acquisition == "2009-11-02T01:00:00"

    def test_rows_outside_the_dataset_are_an_error(self) -> None:
        """已删除的 ROI_60 还留在表里；算进去就多数了一条。调用方应先过 `dataset_rows`。"""
        with pytest.raises(MetadataUnreadable, match="ROI_060"):
            summarize_strips([strip(1), strip(60, "已删除(与ROI_37重复)")])

    def test_the_committed_table_summarises(self, rows) -> None:
        kept = dataset_rows(rows)
        summary = summarize_strips(kept)
        assert summary.count == len(kept)
        assert sum(summary.look_directions.values()) == len(kept)
