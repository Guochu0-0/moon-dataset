"""验证集、测试集每个 patch 的窗口位置（issue #40，地图 #34）。

    python research/ground-truth-residuals/collect.py

评测真值点标在 patch 内，要把它们放回重叠区影像坐标，得知道每个 patch 的窗口左上角。
成品 patch 与重叠区影像都带地理变换，窗口 = (patch 原点 − 重叠区原点) / 像元，由此直接算出，
不重跑 `02_patches.py`。三道校验，任一不过就报错退出：

1. 换算出的窗口必须是整数像素；光学窗口必须落在 512 的整数倍上（铺窗步长）。
2. 由控制点全局仿射按 `moondata.geometry.sar_window` 推出的 SAR 窗口，与读出的逐个相等。
3. `work/windows/` 下若有当年的窗口记录（ROI_037、054、070），逐条相等。

产出 `windows.csv`（入库，小表）：划分、ROI、patch 编号、光学与 SAR 窗口左上角、有无真值点。
需要 GDAL，用 `newest` 环境、`PYTHONPATH=src`。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
from osgeo import gdal

from moondata.geometry import TARGET_RESOLUTION, estimate_affine, sar_window
from moondata.sources import load_tie_points, raw_roi_name

gdal.UseExceptions()

DATASET_ROOT = Path("G:/Lunar_Optical_SAR_Registration_Dataset")
REPO_ROOT = Path(__file__).resolve().parents[2]
GROUND_TRUTH = REPO_ROOT / "data" / "ground-truth"
OLD_WINDOWS = Path("D:/Code/moon-dataset/work/windows")
OUT = Path(__file__).resolve().parent / "windows.csv"
SIZE = 512
SPLITS = ("Val", "Test")


def origin(path: Path) -> tuple[float, float]:
    ds = gdal.Open(str(path))
    x0, dx, rx, y0, ry, dy = ds.GetGeoTransform()
    if not np.allclose((dx, rx, ry, dy), (TARGET_RESOLUTION, 0.0, 0.0, -TARGET_RESOLUTION), atol=1e-9):
        raise SystemExit(f"{path}：地理变换不是 7.5 m 北向上：{(dx, rx, ry, dy)}")
    return x0, y0


def window(patch: Path, grid: tuple[float, float]) -> tuple[int, int]:
    x0, y0 = origin(patch)
    col, row = (x0 - grid[0]) / TARGET_RESOLUTION, (grid[1] - y0) / TARGET_RESOLUTION
    if abs(col - round(col)) > 1e-6 or abs(row - round(row)) > 1e-6:
        raise SystemExit(f"{patch}：窗口不是整数像素：{(col, row)}")
    return round(col), round(row)


def old_windows(roi: str) -> dict[int, tuple[tuple[int, int], tuple[int, int]]]:
    path = OLD_WINDOWS / f"{roi}.json"
    if not path.is_file():
        return {}
    patches = json.loads(path.read_text(encoding="utf-8"))["rois"][roi]["patches"]
    return {p["index"]: (tuple(p["optical"]), tuple(p["sar"])) for p in patches}


def main() -> int:
    rows = []
    for split in SPLITS:
        for roi_dir in sorted((GROUND_TRUTH / split).iterdir()):
            roi = roi_dir.name
            overlap = DATASET_ROOT / "raw" / raw_roi_name(roi) / "cropped" / "ce2"
            opt_grid, sar_grid = origin(overlap / "opt.tif"), origin(overlap / "sar.tif")
            matrix = estimate_affine(*load_tie_points(REPO_ROOT, roi))
            patch_dir = DATASET_ROOT / "Processed_Data" / split / roi
            labelled = {int(p.stem.split("_")[1]) for p in roi_dir.glob("patch_*.txt")}
            old = old_windows(roi)
            indices = sorted(int(p.stem.split("_")[1]) for p in (patch_dir / "Optical").glob("patch_*.tif"))
            for index in indices:
                opt = window(patch_dir / "Optical" / f"patch_{index}.tif", opt_grid)
                sar = window(patch_dir / "SAR" / f"patch_{index}.tif", sar_grid)
                if opt[0] % SIZE or opt[1] % SIZE:
                    raise SystemExit(f"{roi} patch_{index}：光学窗口 {opt} 不在铺窗网格上")
                if sar_window(opt, SIZE, matrix) != sar:
                    raise SystemExit(
                        f"{roi} patch_{index}：SAR 窗口 {sar} ≠ 全局仿射推出的 {sar_window(opt, SIZE, matrix)}"
                    )
                if old and old.get(index) != (opt, sar):
                    raise SystemExit(f"{roi} patch_{index}：与当年记录 {old.get(index)} 不符")
                rows.append((split, roi, index, *opt, *sar, int(index in labelled)))
            missing = labelled - set(indices)
            if missing:
                raise SystemExit(f"{roi}：有真值点却没有 patch：{sorted(missing)}")
            print(f"{split} {roi}：{len(indices)} 个 patch，{len(labelled)} 个有真值点"
                  + ("，与当年窗口记录逐条一致" if old else ""), flush=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(("split", "roi", "patch", "opt_col", "opt_row", "sar_col", "sar_row", "labelled"))
        writer.writerows(rows)
    print(f"{len(rows)} 行 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
