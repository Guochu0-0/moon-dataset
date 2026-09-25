"""光学全局标准化的数值范围（issue #38，地图 #34）。

    python research/sar-normalization/optical_range.py   # 写 optical_tables.md

逐像素读全部光学 patch（uint8），不抽样。训练集 μ、σ 由精确的灰度直方图算；
z = (灰度 − μ) / σ 的范围、尾部比例，以及各 patch 的 z 极值。
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from osgeo import gdal

gdal.UseExceptions()

DATASET_ROOT = Path("G:/Lunar_Optical_SAR_Registration_Dataset/Processed_Data")
OUT_DIR = Path(__file__).resolve().parent
SPLITS = ("Train", "Val", "Test")
EXCLUDED_ROIS = {"ROI_060"}
Z_LEVELS = (2, 3, 4, 5, 6)


def collect_roi(split: str, roi: str) -> tuple[str, np.ndarray, np.ndarray]:
    hists = []
    for path in sorted((DATASET_ROOT / split / roi / "Optical").glob("patch_*.tif")):
        hists.append(np.bincount(gdal.Open(str(path)).ReadAsArray().ravel(), minlength=256))
    return split, roi, np.array(hists, np.int64)


def main() -> None:
    jobs = [
        (split, roi.name)
        for split in SPLITS
        for roi in sorted((DATASET_ROOT / split).iterdir())
        if roi.is_dir() and roi.name not in EXCLUDED_ROIS
    ]
    per_patch = {s: [] for s in SPLITS}
    with ProcessPoolExecutor(6) as pool:
        for split, roi, hists in pool.map(collect_roi, *zip(*jobs)):
            per_patch[split].append(hists)
    per_patch = {s: np.concatenate(v) for s, v in per_patch.items()}

    levels = np.arange(256)
    train = per_patch["Train"].sum(0)
    w = train / train.sum()
    mu = float((w * levels).sum())
    sigma = float(np.sqrt((w * (levels - mu) ** 2).sum()))
    lines = [
        "# 光学全局标准化的数值范围：数字表",
        "",
        "由 `optical_range.py` 生成，勿手改。全部像素逐个统计，不抽样。",
        "",
        f"训练集光学灰度：**μ = {mu:.3f}，σ = {sigma:.3f}**（含阴影饱和的灰度 1）。z = (灰度 − μ) / σ。",
        f"uint8 决定了 z 的理论范围：灰度 0 → {-mu / sigma:.2f}，灰度 255 → {(255 - mu) / sigma:.2f}。",
        "",
        "| 划分 | patch | 最小灰度 | 最大灰度 | z 最小 | z 最大 | 灰度 1 | 灰度 255 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in SPLITS:
        h = per_patch[s].sum(0)
        present = np.nonzero(h)[0]
        lines.append(
            f"| {s} | {len(per_patch[s])} | {present[0]} | {present[-1]} | {(present[0] - mu) / sigma:.2f} "
            f"| {(present[-1] - mu) / sigma:.2f} | {h[1] / h.sum():.2e} | {h[255] / h.sum():.2e} |"
        )
    lines += ["", "## z 的尾部", "", "像素比例；括号里是至少有一个这种像素的 patch 数。", ""]
    lines += ["| 划分 | 方向 | " + " | ".join(f"\\|z\\| > {k}" for k in Z_LEVELS) + " |", "|---|---|" + "---|" * len(Z_LEVELS)]
    for s in SPLITS:
        p = per_patch[s]
        for side, sign in (("低端 z < −k", -1), ("高端 z > k", 1)):
            cells = []
            for k in Z_LEVELS:
                z = (levels - mu) / sigma
                mask = z < -k if sign < 0 else z > k
                cells.append(f"{p[:, mask].sum() / p.sum():.2e} ({int((p[:, mask].sum(1) > 0).sum())})")
            lines.append(f"| {s} | {side} | " + " | ".join(cells) + " |")
    (OUT_DIR / "optical_tables.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
