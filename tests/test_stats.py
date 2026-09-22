"""扫描 patch 产物、产出统计量。fixture 是一棵迷你的 Processed_Data。"""

import json
from pathlib import Path

import numpy as np
import pytest

from moondata.errors import StatsUnavailable
from moondata.stats import parse_removed_manifest, scan_products
from tiff_fixtures import write_tiff

REMOVED_MANIFEST = """\
# 已删除: Processed_Data/Val/ROI_060
# 原因: 与 Test/ROI_037 为同一地点, 造成 Test/Val 不独立
# 删除日期: 2026-09-20
# 原始数据仍保留于 raw/ROI_60
# --- 文件清单 ---
./Label/patch_0.prj
./Label/patch_0.txt
./Label/patch_2.prj
./Label/patch_2.txt
./Optical/patch_0.tif
./Optical/patch_1.tif
./Optical/patch_2.tif
./SAR/patch_0.tif
./SAR/patch_1.tif
./SAR/patch_2.tif
"""


def add_patch(
    root: Path,
    split: str,
    roi: str,
    index: int,
    *,
    label_points: int | None = None,
    optical_value: int = 50,
    sar_value: float = 0.25,
    size: int = 8,
) -> None:
    """造一对 patch；`label_points` 不为 None 时再造一份评测真值点文件（y 取负）。"""
    directory = root / split / roi
    optical = np.full((size, size), optical_value, dtype=np.uint8)
    optical[0, 0] = 0  # 一个 nodata 像素
    sar = np.full((size, size, 4), sar_value, dtype=np.float32)
    sar[1, 1] = [-0.5, 0.1, 0.2, 0.3]
    write_tiff(directory / "Optical" / f"patch_{index}.tif", optical)
    write_tiff(directory / "SAR" / f"patch_{index}.tif", sar)
    if label_points is not None:
        rows = [f"{10 + i}.5\t-{20 + i}.25\t{11 + i}.0\t-{21 + i}.0" for i in range(label_points)]
        label = directory / "Label" / f"patch_{index}.txt"
        label.parent.mkdir(parents=True, exist_ok=True)
        label.write_text("\n".join(rows) + "\n", encoding="utf-8")
        (directory / "Label" / f"patch_{index}.prj").write_text(
            "{B286C06B-0879-11D2-AACA-00C04FA33C20}", encoding="utf-8"
        )


def write_manifest(path: Path, rois: dict[str, tuple[str, int, int]]) -> Path:
    """窗口清单：ROI → (划分, 窗口数, unresolved 数)。"""
    document = {
        "patch_size": 512,
        "aligned_name": "cropped",
        "rois": {
            roi: {
                "split": split,
                "patches": [{"index": i, "optical": [0, 0], "sar": [0, 0]} for i in range(n)],
                "unresolved": [{"index": n + i} for i in range(unresolved)],
            }
            for roi, (split, n, unresolved) in rois.items()
        },
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.fixture
def products(tmp_path: Path) -> Path:
    root = tmp_path / "Processed_Data"
    for index in range(3):
        add_patch(root, "Train", "ROI_001", index)
    add_patch(root, "Train", "ROI_002", 0)
    add_patch(root, "Val", "ROI_035", 0, label_points=8)
    add_patch(root, "Val", "ROI_035", 1, label_points=6)
    add_patch(root, "Val", "ROI_035", 2)  # 没有评测真值点的 patch
    add_patch(root, "Test", "ROI_006", 0, label_points=9, optical_value=200, sar_value=3.0)
    return root


@pytest.fixture
def removed():
    return [parse_removed_manifest(REMOVED_MANIFEST)]


class TestRemovedManifest:
    def test_reads_which_roi_was_removed_from_which_split(self) -> None:
        roi = parse_removed_manifest(REMOVED_MANIFEST)
        assert (roi.roi, roi.split) == ("ROI_060", "Val")
        assert roi.deleted_on == "2026-09-20"
        assert "不独立" in roi.reason

    def test_counts_patches_and_labeled_patches_from_the_file_list(self) -> None:
        roi = parse_removed_manifest(REMOVED_MANIFEST)
        assert roi.patch_count == 3
        assert roi.labeled_patch_count == 2

    def test_rejects_text_without_the_header(self) -> None:
        with pytest.raises(StatsUnavailable):
            parse_removed_manifest("./Optical/patch_0.tif\n")


class TestCounts:
    def test_per_split_counts_exclude_the_removed_roi(
        self, products: Path, removed
    ) -> None:
        counts = scan_products(products, removed=removed)["counts"]["excluding_removed"]
        assert counts["Train"]["roi_count"] == 2
        assert counts["Train"]["patch_count"] == 4
        assert counts["Val"] == {
            "roi_count": 1,
            "patch_count": 3,
            "labeled_patch_count": 2,
            "label_point_count": 14,
        }
        assert counts["all"]["roi_count"] == 4
        assert counts["all"]["patch_count"] == 8

    def test_including_removed_adds_the_deleted_roi_back(
        self, products: Path, removed
    ) -> None:
        counts = scan_products(products, removed=removed)["counts"]["including_removed"]
        assert counts["Val"]["roi_count"] == 2
        assert counts["Val"]["patch_count"] == 6
        assert counts["Val"]["labeled_patch_count"] == 4
        assert counts["all"]["roi_count"] == 5

    def test_label_points_of_the_removed_roi_are_unknown_not_zero(
        self, products: Path, removed
    ) -> None:
        """被删 ROI 的标签文件已不在盘上，清单里只有文件名。点数不知道就是不知道。"""
        counts = scan_products(products, removed=removed)["counts"]["including_removed"]
        assert counts["Val"]["label_point_count"] is None
        assert counts["all"]["label_point_count"] is None
        assert counts["Test"]["label_point_count"] == 9

    def test_per_roi_records(self, products: Path) -> None:
        rois = scan_products(products)["rois"]
        assert rois["ROI_035"] == {
            "split": "Val",
            "patch_count": 3,
            "labeled_patch_count": 2,
            "label_point_count": 14,
        }
        assert rois["ROI_001"]["labeled_patch_count"] == 0

    def test_train_has_no_ground_truth(self, products: Path) -> None:
        counts = scan_products(products)["counts"]["excluding_removed"]
        assert counts["Train"]["labeled_patch_count"] == 0


class TestImages:
    def test_reports_type_bands_size_and_georeferencing(self, products: Path) -> None:
        images = scan_products(products)["images"]
        assert images["Optical"]["dtypes"] == ["uint8"]
        assert images["Optical"]["bands"] == [1]
        assert images["SAR"]["dtypes"] == ["float32"]
        assert images["SAR"]["bands"] == [4]
        assert images["SAR"]["sizes"] == [[8, 8]]
        assert images["SAR"]["compressions"] == ["Deflate"]
        assert images["SAR"]["nodata"] == [0.0]
        assert images["SAR"]["pixel_scales"] == [[7.5, 7.5]]
        assert images["Optical"]["file_count"] == 8

    def test_value_range_ignores_nodata(self, products: Path) -> None:
        optical = scan_products(products)["images"]["Optical"]
        assert optical["band_ranges"] == [{"min": 50, "max": 200}]
        assert optical["nodata_pixel_fraction"] == pytest.approx(1 / 64)

    def test_sar_negative_values_are_reported(self, products: Path) -> None:
        sar = scan_products(products)["images"]["SAR"]
        assert sar["band_ranges"][0] == {"min": -0.5, "max": 3.0}
        assert sar["band_ranges"][1]["min"] == pytest.approx(0.1)
        assert sar["patches_with_negative"] == 8
        assert sar["nan_pixel_count"] == 0


class TestLabels:
    def test_points_per_patch_and_sign_convention(self, products: Path) -> None:
        labels = scan_products(products)["labels"]
        assert labels["file_count"] == 3
        assert labels["points_per_patch"] == {"min": 6, "median": 8, "max": 9}
        assert labels["columns"] == [4]
        assert labels["y_all_nonpositive"] is True

    def test_classifies_the_projection_sidecars(self, products: Path) -> None:
        """`.prj` 多数只是一个 GUID 占位，少数写了完整的 WKT 投影。"""
        prj = products / "Test" / "ROI_006" / "Label" / "patch_0.prj"
        prj.write_text('PROJCS["Moon_Mecator",GEOGCS["GCS_Moon_2000"]]', encoding="utf-8")
        assert scan_products(products)["labels"]["prj_kinds"] == {"guid": 2, "wkt": 1}

    def test_detects_a_label_file_with_positive_y(self, products: Path) -> None:
        label = products / "Test" / "ROI_006" / "Label" / "patch_0.txt"
        label.write_text("1.0\t2.0\t3.0\t-4.0\n", encoding="utf-8")
        assert scan_products(products)["labels"]["y_all_nonpositive"] is False


class TestNaming:
    def test_clean_tree_has_no_anomalies(self, products: Path) -> None:
        naming = scan_products(products)["naming"]
        assert naming == {"unpaired": [], "index_gaps": [], "unexpected_files": []}

    def test_reports_a_patch_missing_its_sar_half(self, products: Path) -> None:
        (products / "Train" / "ROI_002" / "SAR" / "patch_0.tif").unlink()
        naming = scan_products(products)["naming"]
        assert naming["unpaired"] == ["Train/ROI_002/patch_0"]

    def test_reports_gaps_in_the_numbering(self, products: Path) -> None:
        add_patch(products, "Train", "ROI_002", 5)
        assert scan_products(products)["naming"]["index_gaps"] == ["Train/ROI_002"]

    def test_reports_files_outside_the_naming_scheme(self, products: Path) -> None:
        (products / "Train" / "ROI_001" / "Optical" / "patch_0 - 副本.tif").write_bytes(b"")
        naming = scan_products(products)["naming"]
        assert naming["unexpected_files"] == ["Train/ROI_001/Optical/patch_0 - 副本.tif"]


class TestWindowManifests:
    def test_compares_window_counts_with_product_counts(
        self, products: Path, tmp_path: Path, removed
    ) -> None:
        manifest = write_manifest(
            tmp_path / "windows.json",
            {
                "ROI_035": ("Val", 3, 0),
                "ROI_006": ("Test", 1, 0),
                "ROI_060": ("Val", 3, 0),
            },
        )
        train = write_manifest(
            tmp_path / "windows_train.json",
            {"ROI_001": ("Train", 2, 1), "ROI_002": ("Train", 1, 0)},
        )
        result = scan_products(products, removed=removed, window_manifests=[manifest, train])
        windows = result["window_manifests"]
        assert windows["splits"]["Train"] == {
            "windows": 3,
            "unresolved": 1,
            "product_patches": 4,
        }
        assert windows["differences"] == [
            {"roi": "ROI_001", "split": "Train", "windows": 2, "unresolved": 1, "product_patches": 3}
        ]
        # 被删的 ROI 与清单对得上，不该出现在差异里
        assert windows["splits"]["Val"]["product_patches"] == 6

    def test_a_roi_with_unresolved_windows_is_listed_even_if_counts_agree(
        self, products: Path, tmp_path: Path
    ) -> None:
        """unresolved 是清单自己承认没对上的窗口，数量碰巧相等也得让人看见。"""
        train = write_manifest(
            tmp_path / "windows_train.json",
            {"ROI_001": ("Train", 3, 2), "ROI_002": ("Train", 1, 0)},
        )
        differences = scan_products(products, window_manifests=[train])["window_manifests"][
            "differences"
        ]
        assert [d["roi"] for d in differences if d["split"] == "Train"] == ["ROI_001"]


class TestRefusals:
    def test_missing_product_root(self, tmp_path: Path) -> None:
        with pytest.raises(StatsUnavailable):
            scan_products(tmp_path / "Processed_Data")


def test_mixed_band_counts_within_a_modality_are_an_error(products: Path) -> None:
    write_tiff(
        products / "Train" / "ROI_002" / "SAR" / "patch_0.tif",
        np.zeros((8, 8, 2), np.float32),
    )
    with pytest.raises(StatsUnavailable, match="波段数不一致"):
        scan_products(products)


def test_removed_roi_is_counted_like_a_present_one() -> None:
    """现存 ROI 的 patch 按「光学与 SAR 都在」计、标签只算落在这些 patch 上的；被删的也一样。"""
    roi = parse_removed_manifest(
        "# 已删除: Processed_Data/Val/ROI_060\n"
        "./Optical/patch_0.tif\n./Optical/patch_1.tif\n./SAR/patch_0.tif\n"
        "./Label/patch_0.txt\n./Label/patch_1.txt\n"
    )
    assert roi.patch_count == 1
    assert roi.labeled_patch_count == 1
