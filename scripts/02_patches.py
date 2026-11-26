"""协同切片：从重叠区影像与控制点做出 patch 对。

    python scripts/02_patches.py [ROI_054 ...]

不带 ROI 就跑元数据表里的全部 67 个。已有产物直接覆盖。参数全部来自 `config.toml`。

输入是 `work/01_overlap/ROI_<nnn>/` 的一对重叠区影像与 `data/tie-points/ROI_<nnn>.pts`
的控制点；输出是 `work/02_patches/<划分>/ROI_<nnn>/` 下的 `Optical/`、`SAR/`，以及一份
记下仿射矩阵与窗口列表的 `windows.json`。

一个 ROI 的流程：

1. 全部控制点做最小二乘仿射（光学 → SAR），打印拟合残差 RMSE；
2. 在光学影像上 512×512、步长 512 铺窗，四角经仿射映射定出 SAR 窗口；
3. 剔除：SAR 窗口出界、四边形与 SAR 窗口重叠比低于 70%、任一边含 nodata（0）、
   剔除表命中；
4. 剩下的按铺窗顺序从 `patch_0` 起编号；按编号后排除表留空号，再切出光学与 SAR。

编号是评测真值点的钥匙（`data/ground-truth/` 里的点按 patch 编号绑定），所以第 3 步
多丢或少丢一个窗口，其后全部编号错位、真值点全部作废。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np

from moondata import raster
from moondata.config import Config, load_config
from moondata.errors import MoonDataError, OverlapImagesMissing
from moondata.geometry import (
    EXCLUDED_WINDOWS,
    Window,
    candidate_windows,
    estimate_affine,
    number_windows,
    rmse,
    usable_pair,
)
from moondata.sources import load_roi_table, load_tie_points, padded_roi

OPTICAL_DIRNAME, SAR_DIRNAME = "Optical", "SAR"
WINDOWS_NAME = "windows.json"

DELETED_NUMBERS: dict[str, frozenset[int]] = {
    # 成品光学覆盖与测试 ROI_054 有正面积交集，排除训练侧的整对 patch。
    "ROI_017": frozenset({9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45, 48, 51, 54, 57, 61}),
    # 历史成品在编号后删掉了纯色废块，后续编号沿用原样。
    "ROI_027": frozenset({95, 98, 99}),
}
"""编号后排除的 patch。按原窗口编号查表，避免后续编号前移。"""


def main(argv: list[str]) -> int:
    config = load_config()
    splits = {row.roi: row.split for row in load_roi_table(config.repo_root)}
    rois = [padded_roi(name) for name in argv] or sorted(splits)
    for roi in rois:
        cut_roi(config, roi, splits[roi])
    return 0


def cut_roi(config: Config, roi: str, split: str) -> None:
    optical_tie, sar_tie = load_tie_points(config.repo_root, roi)
    matrix = estimate_affine(optical_tie, sar_tie)
    print(
        f"{roi}（{split}）：{len(optical_tie)} 对控制点，仿射拟合残差 RMSE "
        f"{rmse(matrix, optical_tie, sar_tie):.2f} px",
        flush=True,
    )

    overlap_dir = config.overlap_dir(roi)
    optical_path, sar_path = overlap_dir / "opt.tif", overlap_dir / "sar.tif"
    for path in (optical_path, sar_path):
        if not path.is_file():
            raise OverlapImagesMissing(
                f"{path} 不存在——先跑 python scripts/01_overlap.py {roi}"
            )
    grid = raster.read_grid(optical_path)
    sar_grid = raster.read_grid(sar_path)

    size = config.patch_size
    plan = candidate_windows(
        (grid.width, grid.height), (sar_grid.width, sar_grid.height), matrix, size
    )
    excluded = EXCLUDED_WINDOWS.get(roi, frozenset())
    with raster.Blocks(optical_path) as optical, raster.Blocks(sar_path) as sar:
        windows = number_windows(
            plan.pairs,
            usable=lambda pair: usable_pair(
                optical.read(pair.optical, size), sar.read(pair.sar, size)
            ),
            excluded=excluded,
        )
    tiled = len(plan.pairs) + plan.out_of_bounds + plan.low_overlap
    hits = sum(1 for pair in plan.pairs if pair.optical in excluded)
    print(
        f"  铺 {tiled} 个窗口：SAR 出界 {plan.out_of_bounds}、重叠不足 {plan.low_overlap}、"
        f"含 nodata {len(plan.pairs) - hits - len(windows)}、剔除表 {hits}，"
        f"留下 {len(windows)} 个",
        flush=True,
    )

    deleted = DELETED_NUMBERS.get(roi, frozenset())
    kept = [window for window in windows if window.index not in deleted]
    if deleted:
        print(f"  编号后排除 {sorted(deleted)}，编号留空")

    out_dir = config.patches_dir(split, roi)
    # 整个 ROI 目录先清掉：窗口变少时，上一轮留下的 patch 会顶着正确的文件名冒充新产物。
    if out_dir.exists():
        shutil.rmtree(out_dir)
    print(f"  切 {len(kept)} 对 patch → {out_dir}", flush=True)
    for dirname, source, corners in (
        (OPTICAL_DIRNAME, optical_path, [w.optical for w in kept]),
        (SAR_DIRNAME, sar_path, [w.sar for w in kept]),
    ):
        outputs = [out_dir / dirname / f"patch_{w.index}.tif" for w in kept]
        raster.write_patches(source, corners, size, outputs)
    write_record(out_dir / WINDOWS_NAME, roi, split, size, matrix, kept)
    print(f"  已写出 {len(kept)} 对 patch 与 {out_dir / WINDOWS_NAME}", flush=True)


def write_record(
    path: Path, roi: str, split: str, size: int, matrix: np.ndarray, windows: list[Window]
) -> None:
    """仿射矩阵与窗口列表——中间结果要能被翻出来看，不然「窗口为什么在这里」无从回答。"""
    document = {
        "roi": roi,
        "split": split,
        "patch_size": size,
        "affine": [list(row) for row in matrix],
        "windows": [
            {"index": w.index, "optical": list(w.optical), "sar": list(w.sar)} for w in windows
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except MoonDataError as error:
        print(f"错误：{error}", file=sys.stderr)
        sys.exit(1)
