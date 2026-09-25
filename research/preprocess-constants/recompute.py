"""用夹过下限的值精确重算训练集常数，并用 `moondata.preprocess` 本身跑一遍全部 patch。

    PYTHONPATH=src python research/preprocess-constants/recompute.py   # 写 tables.md

`research/sar-normalization/s1db_range.py` 的 μ、σ 由 0.01 dB 直方图算、非正值不计入；
这里改成逐像素 float64 累加（相对 μ₀ 取差再平方，避免相消），夹下限后非正值也计入。
同时记下 `sar_input`、`optical_input` 在三个划分上的输出范围。
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from osgeo import gdal

from moondata.preprocess import (
    OPTICAL_MEAN, OPTICAL_STD, SAR_FLOOR_DB, SAR_MEAN_DB, SAR_STD_DB, optical_input, sar_input,
)

gdal.UseExceptions()

DATASET_ROOT = Path("G:/Lunar_Optical_SAR_Registration_Dataset/Processed_Data")
OUT_DIR = Path(__file__).resolve().parent
SPLITS = ("Train", "Val", "Test")
EXCLUDED_ROIS = {"ROI_060"}
FLOOR = 10 ** (SAR_FLOOR_DB / 10)


def collect_roi(split: str, roi: str) -> dict:
    n = s = ss = 0.0
    floored = 0
    zmin, zmax = np.inf, -np.inf
    ohist = np.zeros(256, np.int64)
    ozmin, ozmax = np.inf, -np.inf
    for path in sorted((DATASET_ROOT / split / roi / "SAR").glob("patch_*.tif")):
        bands = gdal.Open(str(path)).ReadAsArray()
        s1 = bands[0].astype(np.float64) + bands[1]
        floored += int((s1 < FLOOR).sum())
        d = 10 * np.log10(np.maximum(s1, FLOOR)) - SAR_MEAN_DB
        n += d.size
        s += d.sum()
        ss += (d * d).sum()
        z = sar_input(bands)
        zmin, zmax = min(zmin, float(z.min())), max(zmax, float(z.max()))
        optical = gdal.Open(str(path.parent.parent / "Optical" / path.name)).ReadAsArray()
        ohist += np.bincount(optical.ravel(), minlength=256)
        oz = optical_input(optical)
        ozmin, ozmax = min(ozmin, float(oz.min())), max(ozmax, float(oz.max()))
    return {"split": split, "n": n, "s": s, "ss": ss, "floored": floored, "zmin": zmin, "zmax": zmax,
            "ohist": ohist, "ozmin": ozmin, "ozmax": ozmax}


def main() -> None:
    jobs = [
        (split, roi.name)
        for split in SPLITS
        for roi in sorted((DATASET_ROOT / split).iterdir())
        if roi.is_dir() and roi.name not in EXCLUDED_ROIS
    ]
    with ProcessPoolExecutor(6) as pool:
        results = list(pool.map(collect_roi, *zip(*jobs)))

    train = [r for r in results if r["split"] == "Train"]
    n = sum(r["n"] for r in train)
    m = sum(r["s"] for r in train) / n
    mu, sigma = SAR_MEAN_DB + m, float(np.sqrt(sum(r["ss"] for r in train) / n - m * m))
    h = sum(r["ohist"] for r in train)
    w = h / h.sum()
    levels = np.arange(256)
    omu = float((w * levels).sum())
    osigma = float(np.sqrt((w * (levels - omu) ** 2).sum()))

    lines = [
        "# 输入表示的常数：精确重算", "",
        "由 `recompute.py` 生成，勿手改。全部像素逐个统计，不抽样。", "",
        "## 训练集常数", "",
        "| 量 | 重算 | 模块常数 | 三位小数一致 |", "|---|---|---|---|",
    ]
    for name, got, const in (
        ("S1 dB 均值（夹下限）", mu, SAR_MEAN_DB), ("S1 dB 标准差（夹下限）", sigma, SAR_STD_DB),
        ("光学灰度均值", omu, OPTICAL_MEAN), ("光学灰度标准差", osigma, OPTICAL_STD),
    ):
        lines.append(f"| {name} | {got:.6f} | {const} | {'是' if round(got, 3) == const else '否'} |")
    lines += [
        "", "## 输出范围", "",
        "| 划分 | 像素 | 夹到下限的像素 | SAR z 最小 | SAR z 最大 | 光学 z 最小 | 光学 z 最大 |",
        "|---|---|---|---|---|---|---|",
    ]
    for split in SPLITS:
        part = [r for r in results if r["split"] == split]
        lines.append(
            f"| {split} | {sum(r['n'] for r in part):.4e} | {sum(r['floored'] for r in part)} "
            f"| {min(r['zmin'] for r in part):.3f} | {max(r['zmax'] for r in part):.3f} "
            f"| {min(r['ozmin'] for r in part):.3f} | {max(r['ozmax'] for r in part):.3f} |"
        )
    (OUT_DIR / "tables.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
