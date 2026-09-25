"""S1 dB 全局标准化、不截断时的数值范围（issue #38，地图 #34）。

    python research/sar-normalization/s1db_range.py collect   # 逐像素读全部 patch，缓存到 work/research/sar-normalization/
    python research/sar-normalization/s1db_range.py report    # 由缓存写 tables.md 与图

不抽样：尾部要看到 1e-7 量级。每个 patch 记下 S1 dB 的精细直方图（0.01 dB，全局累加）、
1 dB 直方图（逐 patch 保留）、非正值个数、正值的最小与最大 dB。

- 训练集的 μ、σ 由精细直方图算（分箱误差 < 0.005 dB）。
- 标准化 z = (S1_dB − μ) / σ 的尾部比例、各 patch 的 z 极值。
- 非正值夹到什么下限：看正值 S1 dB 的最小值分布。
- 对照：全局截断 [−17.1, −2.0] 与固定宽窗 [−25, 0] 各截掉多少像素、多少 patch 受影响。
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from osgeo import gdal

gdal.UseExceptions()

DATASET_ROOT = Path("G:/Lunar_Optical_SAR_Registration_Dataset/Processed_Data")
REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "work" / "research" / "sar-normalization"
OUT_DIR = Path(__file__).resolve().parent

SPLITS = ("Train", "Val", "Test")
EXCLUDED_ROIS = {"ROI_060"}
FINE_LO, FINE_HI, FINE_STEP = -60.0, 20.0, 0.01
FINE_EDGES = np.linspace(FINE_LO, FINE_HI, round((FINE_HI - FINE_LO) / FINE_STEP) + 1)
COARSE_EDGES = np.arange(-60.0, 21.0, 1.0)
CLIPS = {"全局截断 [−17.1, −2.0]": (-17.1, -2.0), "固定宽窗 [−25, 0]": (-25.0, 0.0)}


def collect_roi(split: str, roi: str) -> dict:
    roi_dir = DATASET_ROOT / split / roi
    numbers = sorted(int(p.stem.split("_")[1]) for p in (roi_dir / "SAR").glob("patch_*.tif"))
    fine = np.zeros(len(FINE_EDGES) - 1, np.int64)
    coarse, nonpos, dbmin, dbmax = [], [], [], []
    for number in numbers:
        b = gdal.Open(str(roi_dir / "SAR" / f"patch_{number}.tif")).ReadAsArray().astype(np.float64)
        s1 = b[0] + b[1]
        pos = s1 > 0
        value = 10 * np.log10(s1[pos])
        assert FINE_LO < value.min() and value.max() < FINE_HI, (roi, number, value.min(), value.max())
        fine += np.histogram(value, FINE_EDGES)[0]
        coarse.append(np.histogram(value, COARSE_EDGES)[0])
        nonpos.append(int((~pos).sum()))
        dbmin.append(float(value.min()))
        dbmax.append(float(value.max()))
    return {
        "split": split, "roi": roi, "numbers": numbers, "fine": fine,
        "coarse": np.array(coarse, np.int32), "nonpos": np.array(nonpos),
        "dbmin": np.array(dbmin), "dbmax": np.array(dbmax),
    }


def collect(workers: int) -> None:
    jobs = [
        (split, roi.name)
        for split in SPLITS
        for roi in sorted((DATASET_ROOT / split).iterdir())
        if roi.is_dir() and roi.name not in EXCLUDED_ROIS
    ]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    with ProcessPoolExecutor(workers) as pool:
        for done, r in enumerate(pool.map(collect_roi, *zip(*jobs)), 1):
            print(f"[{done}/{len(jobs)}] {r['split']}/{r['roi']}: {len(r['numbers'])} 个 patch", flush=True)
            results.append(r)
    for split in SPLITS:
        part = [r for r in results if r["split"] == split]
        np.savez_compressed(
            CACHE_DIR / f"{split}.npz",
            rois=np.array([r["roi"] for r in part for _ in r["numbers"]]),
            numbers=np.concatenate([r["numbers"] for r in part]),
            fine=sum(r["fine"] for r in part),
            **{k: np.concatenate([r[k] for r in part]) for k in ("coarse", "nonpos", "dbmin", "dbmax")},
        )


# ---------------------------------------------------------------- report

Z_LEVELS = (3, 4, 5, 6, 8, 10)


def moments(fine: np.ndarray) -> tuple[float, float]:
    centers = (FINE_EDGES[:-1] + FINE_EDGES[1:]) / 2
    w = fine / fine.sum()
    mu = float((w * centers).sum())
    return mu, float(np.sqrt((w * (centers - mu) ** 2).sum()))


def tail(fine: np.ndarray, lo_db: float | None, hi_db: float | None) -> float:
    """dB 低于 lo_db 或高于 hi_db 的像素比例（按精细分箱，边界误差 0.01 dB）。"""
    centers = (FINE_EDGES[:-1] + FINE_EDGES[1:]) / 2
    mask = np.zeros_like(centers, bool)
    if lo_db is not None:
        mask |= centers < lo_db
    if hi_db is not None:
        mask |= centers > hi_db
    return float(fine[mask].sum() / fine.sum())


def patches_beyond(data, lo_db: float | None, hi_db: float | None) -> int:
    hit = np.zeros(len(data["dbmax"]), bool)
    if lo_db is not None:
        hit |= data["dbmin"] < lo_db
    if hi_db is not None:
        hit |= data["dbmax"] > hi_db
    return int(hit.sum())


def report() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data = {s: dict(np.load(CACHE_DIR / f"{s}.npz")) for s in SPLITS}
    mu, sigma = moments(data["Train"]["fine"])
    lines = [
        "# S1 dB 全局标准化的数值范围：数字表",
        "",
        "由 `s1db_range.py report` 生成，勿手改。全部像素逐个统计，不抽样。",
        "",
        f"训练集 S1 dB：**μ = {mu:.3f} dB，σ = {sigma:.3f} dB**（只取自 Train；非正值不计入）。",
        "z = (S1_dB − μ) / σ。",
        "",
        "## 概况",
        "",
        "| 划分 | patch | 像素 | 非正值像素 | 含非正值的 patch | 正值最小 dB | 最大 dB | z 最小 | z 最大 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in SPLITS:
        d = data[s]
        n = int(d["fine"].sum() + d["nonpos"].sum())
        lines.append(
            f"| {s} | {len(d['numbers'])} | {n:.3e} | {int(d['nonpos'].sum())} | {int((d['nonpos'] > 0).sum())} "
            f"| {d['dbmin'].min():.2f} | {d['dbmax'].max():.2f} "
            f"| {(d['dbmin'].min() - mu) / sigma:.2f} | {(d['dbmax'].max() - mu) / sigma:.2f} |"
        )

    lines += ["", "## z 的尾部", "", "像素比例；括号里是至少有一个这种像素的 patch 数。", ""]
    head = " | ".join(f"\\|z\\| > {k}" for k in Z_LEVELS)
    lines += [f"| 划分 | 方向 | {head} |", "|---|---|" + "---|" * len(Z_LEVELS)]
    for s in SPLITS:
        d = data[s]
        for side, sign in (("低端 z < −k", -1), ("高端 z > k", 1)):
            cells = []
            for k in Z_LEVELS:
                edge = mu + sign * k * sigma
                lo, hi = (edge, None) if sign < 0 else (None, edge)
                cells.append(f"{tail(d['fine'], lo, hi):.2e} ({patches_beyond(d, lo, hi)})")
            lines.append(f"| {s} | {side} | " + " | ".join(cells) + " |")

    lines += ["", "## 对照：截断方案截掉多少", "", "| 划分 | 方案 | 截到下限 | 截到上限 | 受影响的 patch | 单个 patch 截掉的最大比例 |", "|---|---|---|---|---|---|"]
    centers = (COARSE_EDGES[:-1] + COARSE_EDGES[1:]) / 2
    for s in SPLITS:
        d = data[s]
        for name, (lo, hi) in CLIPS.items():
            # 逐 patch 比例按 1 dB 分箱估计（边界处取整到整 dB），整体比例按精细分箱精确
            per_patch = d["coarse"][:, (centers < lo) | (centers > hi)].sum(1) / d["coarse"].sum(1)
            lines.append(
                f"| {s} | {name} | {tail(d['fine'], lo, None):.2e} | {tail(d['fine'], None, hi):.2e} "
                f"| {patches_beyond(d, lo, hi)} | {per_patch.max():.1%} |"
            )

    lines += ["", "## z 最大的 patch（Train + Val + Test）", "", "| 划分 | ROI | patch | 最大 dB | z 最大 | z > 6 的像素（1 dB 分箱估计） |", "|---|---|---|---|---|---|"]
    rows = []
    for s in SPLITS:
        d = data[s]
        over6 = d["coarse"][:, centers > mu + 6 * sigma].sum(1)
        for i in range(len(d["numbers"])):
            rows.append((d["dbmax"][i], s, str(d["rois"][i]), int(d["numbers"][i]), int(over6[i])))
    for dbmax, s, roi, number, over6 in sorted(rows, reverse=True)[:15]:
        lines.append(f"| {s} | {roi} | {number} | {dbmax:.2f} | {(dbmax - mu) / sigma:.2f} | {over6} |")

    (OUT_DIR / "tables.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    fig, ax = plt.subplots(figsize=(8, 4))
    fc = (FINE_EDGES[:-1] + FINE_EDGES[1:]) / 2
    for s in SPLITS:
        f = data[s]["fine"].reshape(-1, 20).sum(1)  # 0.2 dB
        c = fc.reshape(-1, 20).mean(1)
        ax.semilogy((c - mu) / sigma, f / f.sum(), label=s)
    for k in (-6, -4, 4, 6, 8):
        ax.axvline(k, color="gray", lw=0.5, ls=":")
    ax.set_xlabel(f"z = (S1_dB − {mu:.2f}) / {sigma:.2f}")
    ax.set_ylabel("像素比例（0.2 dB 分箱）")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "z_hist.png", dpi=120)
    print("\n".join(lines))


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=("collect", "report"))
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)
    collect(args.workers) if args.step == "collect" else report()


if __name__ == "__main__":
    main(sys.argv[1:])
