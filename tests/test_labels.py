"""生成标签：几何（标签点在全局变换下的传播）与磁盘格式（y 取负，只在读写边界翻）。

纯 numpy、纯文本，不要 GDAL、不要数据盘。期望值一律手算或取自真实文件，不照着实现推。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from moondata.geometry import label_points
from moondata.patches.labels import format_label, parse_label, read_label, write_label


def _affine(a: float = 1.0, b: float = 0.0, tx: float = 0.0,
            c: float = 0.0, d: float = 1.0, ty: float = 0.0) -> np.ndarray:
    return np.array([[a, b, tx], [c, d, ty], [0.0, 0.0, 1.0]])


class TestLabelPoints:
    def test_a_five_by_five_grid_spans_the_patch_corner_to_corner(self) -> None:
        optical, _ = label_points(_affine(), (0, 0), (0, 0), 512)
        assert optical.shape == (25, 2)
        assert optical[0].tolist() == [0.0, 0.0]
        assert optical[4].tolist() == [511.0, 0.0]
        assert optical[5].tolist() == [0.0, 127.75]
        assert optical[-1].tolist() == [511.0, 511.0]

    def test_sar_points_are_in_sar_patch_coordinates_not_whole_image(self) -> None:
        # 全局：光学 (X, Y) → SAR (X + 10, Y − 3)。光学窗口在 (512, 1024)、SAR 窗口在 (520, 1020)，
        # 局部点 (x, y) → 全局 (x + 512, y + 1024) → SAR 全局 (x + 522, y + 1021) → SAR 局部 (x + 2, y + 1)
        _, sar = label_points(_affine(tx=10, ty=-3), (512, 1024), (520, 1020), 512)
        assert sar[0].tolist() == [2.0, 1.0]
        assert sar[-1].tolist() == [513.0, 512.0]

    def test_scaling_in_the_global_transform_carries_into_the_patch(self) -> None:
        # 局部 (x, y) → 全局 (x + 100, y) → ×2 → (2x + 200, 2y) → 减 SAR 窗口 (150, 0) → (2x + 50, 2y)
        _, sar = label_points(_affine(a=2, d=2), (100, 0), (150, 0), 512)
        assert sar[4].tolist() == [1072.0, 0.0]
        assert sar[-1].tolist() == [1072.0, 1022.0]


# 真实评测真值点文件（Val/ROI_035/Label/patch_0.txt）的前三行，原样字节。
# 生成标签必须与它同一格式：四列、制表符、8 位小数、CRLF、y 取负。
REAL_LABEL = (
    b"279.60796221\t-186.31133603\t250.27759784\t-185.56315789\r\n"
    b"236.81929825\t-391.70404858\t201.30161943\t-392.66599190\r\n"
    b"146.70506372\t-29.95382982\t116.85656520\t-30.82971460\r\n"
)


class TestLabelFormat:
    def test_reading_turns_the_stored_negative_y_into_downward_rows(self) -> None:
        optical, sar = parse_label(REAL_LABEL)
        assert optical[0].tolist() == [279.60796221, 186.31133603]
        assert sar[2].tolist() == [116.8565652, 30.8297146]

    def test_a_real_label_file_survives_a_round_trip_byte_for_byte(self) -> None:
        assert format_label(*parse_label(REAL_LABEL)) == REAL_LABEL

    def test_writing_negates_y_and_only_y(self) -> None:
        text = format_label(np.array([[1.5, 2.25]]), np.array([[3.0, 4.0]]))
        assert text == b"1.50000000\t-2.25000000\t3.00000000\t-4.00000000\r\n"

    def test_the_top_row_is_written_as_zero_not_negative_zero(self) -> None:
        text = format_label(np.array([[0.0, 0.0]]), np.array([[0.0, 0.0]]))
        assert text == b"0.00000000\t0.00000000\t0.00000000\t0.00000000\r\n"

    def test_a_row_that_rounds_to_zero_is_written_as_zero_too(self) -> None:
        # 变换算出的 SAR 行号常是 1e-10 这种浮点残差，取负后同样不该写成 "-0.00000000"
        text = format_label(np.array([[0.0, 0.0]]), np.array([[-3e-9, 1e-10]]))
        assert text == b"0.00000000\t0.00000000\t0.00000000\t0.00000000\r\n"

    def test_the_files_on_disk_round_trip(self, tmp_path: Path) -> None:
        optical, sar = label_points(_affine(tx=10.25, ty=-3.5), (512, 0), (520, 0), 512)
        path = write_label(tmp_path / "Label" / "patch_7.txt", optical, sar)
        back_optical, back_sar = read_label(path)
        np.testing.assert_allclose(back_optical, optical, atol=5e-9)
        np.testing.assert_allclose(back_sar, sar, atol=5e-9)

    def test_a_row_with_the_wrong_number_of_columns_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="第 2 行"):
            parse_label(b"1\t-2\t3\t-4\r\n1\t-2\t3\r\n")
