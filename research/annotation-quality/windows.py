"""带评测真值点的 patch 在重叠区影像上的窗口位置，写 `windows.csv`。

    PYTHONPATH=src python research/annotation-quality/windows.py [数据根]

评测真值点标在 patch 内；变异函数与重复测量要把它们放回重叠区影像坐标，得知道每个
patch 的窗口左上角。成品 patch 与重叠区影像都带地理变换，窗口 = (patch 原点 − 重叠区
原点) / 像元，由此直接读出，不重跑 `02_patches.py`。两道校验，任一不过就报错退出：

1. 窗口必须是整数像素，光学窗口必须落在 patch 边长的整数倍上（铺窗步长）；
2. 由控制点全局仿射按 `moondata.geometry.sar_window` 推出的 SAR 窗口，与读出的逐个相等。

只有这一步要数据盘。数据根默认取 `config.toml`，本机路径不同时作为参数给出。
`windows.csv` 入库，`estimate.py` 只读仓库。
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from moondata.config import load_config
from moondata.errors import MoonDataError
from moondata.geometry import PixelGrid, estimate_affine, sar_window
from moondata.raster import read_grid
from moondata.sources import dataset_overlap_images, dataset_patch_dir, ground_truth_files, load_tie_points

HERE = Path(__file__).resolve().parent
SPLITS = ("Val", "Test")


class WindowMismatch(MoonDataError):
    pass


def window(patch: Path, grid: PixelGrid) -> tuple[int, int]:
    origin = read_grid(patch)
    col = (origin.origin_x - grid.origin_x) / grid.resolution
    row = (grid.origin_y - origin.origin_y) / grid.resolution
    if abs(col - round(col)) > 1e-6 or abs(row - round(row)) > 1e-6:
        raise WindowMismatch(f"{patch}：窗口不是整数像素：{(col, row)}")
    return round(col), round(row)


def main() -> int:
    config = load_config()
    data_root = Path(sys.argv[1]) if len(sys.argv) > 1 else config.require_data_root()
    size = config.patch_size
    rows = []
    for split in SPLITS:
        for roi_dir in sorted((config.repo_root / "data" / "ground-truth" / split).iterdir()):
            roi = roi_dir.name
            optical_image, sar_image = dataset_overlap_images(data_root, roi)
            optical_grid, sar_grid = read_grid(optical_image), read_grid(sar_image)
            matrix = estimate_affine(*load_tie_points(config.repo_root, roi))
            patch_dir = dataset_patch_dir(data_root, split, roi)
            indices = sorted(int(p.stem.split("_")[1]) for p in ground_truth_files(config.repo_root, split, roi))
            for index in indices:
                optical = window(patch_dir / "Optical" / f"patch_{index}.tif", optical_grid)
                sar = window(patch_dir / "SAR" / f"patch_{index}.tif", sar_grid)
                if optical[0] % size or optical[1] % size:
                    raise WindowMismatch(f"{roi} patch_{index}：光学窗口 {optical} 不在铺窗网格上")
                if sar_window(optical, size, matrix) != sar:
                    raise WindowMismatch(
                        f"{roi} patch_{index}：SAR 窗口 {sar} ≠ 全局仿射推出的 {sar_window(optical, size, matrix)}"
                    )
                rows.append((split, roi, index, *optical, *sar))
            print(f"{split} {roi}：{len(indices)} 个 patch", flush=True)
    with (HERE / "windows.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(("split", "roi", "patch", "opt_col", "opt_row", "sar_col", "sar_row"))
        writer.writerows(rows)
    print(f"{len(rows)} 个 patch → {HERE / 'windows.csv'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MoonDataError as error:
        print(error, file=sys.stderr)
        sys.exit(1)
