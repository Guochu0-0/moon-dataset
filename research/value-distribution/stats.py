"""光学与 SAR 各波段及派生量的数值分布（issue #36，地图 #34）。

两步：

    python research/value-distribution/stats.py collect   # 读全部 patch，缓存到 work/research/value-distribution/
    python research/value-distribution/stats.py report    # 由缓存出图与数字表，写到本目录

`collect` 读成品 patch（`Processed_Data/<划分>/<ROI>/{Optical,SAR}/patch_<n>.tif`），
按划分分别统计：

- 整幅计数：每个量的零值、负值、非有限值（含 Mini-RF 填充值 −3.4e38）个数；
  四个波段全为零的像素（SAR 的 nodata 是 0）；光学的零值（光学的 nodata 也是 0）。
- 位置：零值与负值像素在 patch 内的出现次数图（512 × 512），负值像素离 nodata 的距离。
- 抽样：每个 patch 固定随机抽 `SAMPLES_PER_PATCH` 个像素，记下全部量，分位数与直方图由它算。
- 逐 patch 统计量：光学与 S1 dB 的均值、标准差、分位数，用来看 ROI 之间的差异。

波段与派生量的定义见 docs/pages/data/imaging.md（SIS §4.3.2.2）。
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from osgeo import gdal

gdal.UseExceptions()

DATASET_ROOT = Path("G:/Lunar_Optical_SAR_Registration_Dataset/Processed_Data")
REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "work" / "research" / "value-distribution"
OUT_DIR = Path(__file__).resolve().parent

SPLITS = ("Train", "Val", "Test")
EXCLUDED_ROIS = {"ROI_060"}
SAMPLES_PER_PATCH = 2048
FILL_THRESHOLD = -1e30
NEAR_NODATA_PX = 3
SHADOW_LEVEL = 1
"""光学的阴影饱和值：阴影里 CE-2 灰度压到 1（0 是 nodata，本数据集里没有）。"""
SHADOW_PATCH_THRESHOLDS = (0.1, 0.5)

RAW = ("b1", "b2", "b3", "b4")
DERIVED = ("S1", "SC", "OC", "CPR", "m")
DECIBEL = ("b1_dB", "b2_dB", "S1_dB", "SC_dB", "OC_dB")
QUANTITIES = RAW + DERIVED + DECIBEL
PERCENTILES = (0.5, 1, 2, 50, 98, 99, 99.5)

PATCH_FIELDS = (
    "opt_mean", "opt_std", "opt_p1", "opt_p50", "opt_p99",
    "s1db_mean", "s1db_std", "s1db_p1", "s1db_p50", "s1db_p99",
    "nodata_frac", "b1_neg_frac", "b2_neg_frac", "s1_nonpos_frac",
)


# ---------------------------------------------------------------- collect


def quantities(bands: np.ndarray) -> dict[str, np.ndarray]:
    """四个波段 → 全部量。非有限与填充值记为 NaN；dB 与比值只在分母、真数为正处有定义。"""
    b = bands.astype(np.float64)
    b[~np.isfinite(b) | (b < FILL_THRESHOLD)] = np.nan
    b1, b2, b3, b4 = b
    s1 = b1 + b2
    s4 = -2 * b4
    sc = 0.5 * (s1 - s4)
    oc = 0.5 * (s1 + s4)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = {
            "b1": b1, "b2": b2, "b3": b3, "b4": b4,
            "S1": s1, "SC": sc, "OC": oc,
            "CPR": np.where(oc > 0, sc / oc, np.nan),
            "m": np.where(s1 > 0, np.sqrt((b1 - b2) ** 2 + (2 * b3) ** 2 + s4**2) / s1, np.nan),
        }
        for name in ("b1", "b2", "S1", "SC", "OC"):
            value = out[name]
            out[f"{name}_dB"] = np.where(value > 0, 10 * np.log10(np.where(value > 0, value, 1)), np.nan)
    return out


def dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    grown = mask.copy()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            grown |= np.roll(np.roll(mask, dy, axis=0), dx, axis=1)
    return grown


def patch_numbers(roi_dir: Path) -> list[int]:
    return sorted(int(p.stem.split("_")[1]) for p in (roi_dir / "SAR").glob("patch_*.tif"))


def collect_roi(split: str, roi: str) -> dict:
    roi_dir = DATASET_ROOT / split / roi
    numbers = patch_numbers(roi_dir)
    size = 512
    counts = {q: {"zero": 0, "neg": 0, "nonfinite": 0} for q in QUANTITIES}
    counts["optical"] = {"zero": 0}
    counts["nodata"] = 0
    counts["fill"] = 0
    counts["pixels"] = 0
    counts["neg_b12"] = 0
    counts["neg_b12_near_nodata"] = 0
    counts["nodata_patches"] = 0
    maps = {"zero_any": np.zeros((size, size), np.int32), "neg_b12": np.zeros((size, size), np.int32)}
    opt_hist = np.zeros(256, np.int64)
    samples = {q: [] for q in QUANTITIES + ("optical",)}
    rows = []

    for number in numbers:
        optical = gdal.Open(str(roi_dir / "Optical" / f"patch_{number}.tif")).ReadAsArray()
        bands = gdal.Open(str(roi_dir / "SAR" / f"patch_{number}.tif")).ReadAsArray()
        assert optical.shape == (size, size) and bands.shape == (4, size, size), (roi, number)
        q = quantities(bands)

        counts["pixels"] += size * size
        counts["fill"] += int((bands < FILL_THRESHOLD).sum())
        nodata = (bands == 0).all(axis=0)
        counts["nodata"] += int(nodata.sum())
        counts["nodata_patches"] += int(nodata.any())
        counts["optical"]["zero"] += int((optical == 0).sum())
        for name, value in q.items():
            finite = np.isfinite(value)
            counts[name]["nonfinite"] += int((~finite).sum())
            counts[name]["zero"] += int((value == 0).sum())
            counts[name]["neg"] += int((value < 0).sum())
        opt_hist += np.bincount(optical.ravel(), minlength=256)

        maps["zero_any"] += (bands == 0).any(axis=0)
        neg = (q["b1"] < 0) | (q["b2"] < 0)
        maps["neg_b12"] += neg
        counts["neg_b12"] += int(neg.sum())
        if nodata.any() and neg.any():
            counts["neg_b12_near_nodata"] += int((neg & dilate(nodata, NEAR_NODATA_PX)).sum())

        rng = np.random.default_rng([int(roi[4:]), number])
        pick = rng.choice(size * size, SAMPLES_PER_PATCH, replace=False)
        for name, value in q.items():
            samples[name].append(value.ravel()[pick].astype(np.float32))
        samples["optical"].append(optical.ravel()[pick].astype(np.float32))

        valid_opt = optical[optical > 0].astype(np.float64)
        s1db = q["S1_dB"][np.isfinite(q["S1_dB"])]
        rows.append([
            *_summary(valid_opt), *_summary(s1db),
            nodata.mean(), (q["b1"] < 0).mean(), (q["b2"] < 0).mean(), (~(q["S1"] > 0)).mean(),
        ])

    return {
        "split": split, "roi": roi, "numbers": numbers, "counts": counts, "maps": maps,
        "opt_hist": opt_hist,
        "samples": {k: np.concatenate(v) if v else np.empty(0, np.float32) for k, v in samples.items()},
        "rows": np.array(rows, np.float64).reshape(len(numbers), len(PATCH_FIELDS)),
    }


def _summary(values: np.ndarray) -> list[float]:
    if values.size == 0:
        return [np.nan] * 5
    p1, p50, p99 = np.percentile(values, (1, 50, 99))
    return [values.mean(), values.std(), p1, p50, p99]


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
        for done, result in enumerate(pool.map(collect_roi, *zip(*jobs)), 1):
            print(f"[{done}/{len(jobs)}] {result['split']}/{result['roi']}: {len(result['numbers'])} 对", flush=True)
            results.append(result)

    for split in SPLITS:
        part = [r for r in results if r["split"] == split]
        arrays = {
            "rois": np.array([r["roi"] for r in part for _ in r["numbers"]]),
            "numbers": np.array([n for r in part for n in r["numbers"]]),
            "rows": np.concatenate([r["rows"] for r in part]),
            "opt_hist": sum(r["opt_hist"] for r in part),
            **{f"map_{k}": sum(r["maps"][k] for r in part) for k in part[0]["maps"]},
            **{f"sample_{k}": np.concatenate([r["samples"][k] for r in part]) for k in part[0]["samples"]},
        }
        np.savez_compressed(CACHE_DIR / f"{split}.npz", **arrays)
        (CACHE_DIR / f"{split}_counts.json").write_text(
            json.dumps({r["roi"]: r["counts"] for r in part}, indent=1), encoding="utf-8"
        )


# ---------------------------------------------------------------- report


def load(split: str) -> tuple[dict, dict]:
    arrays = dict(np.load(CACHE_DIR / f"{split}.npz"))
    per_roi = json.loads((CACHE_DIR / f"{split}_counts.json").read_text(encoding="utf-8"))
    return arrays, per_roi


def total_counts(per_roi: dict) -> dict:
    total: dict = {}
    for counts in per_roi.values():
        for key, value in counts.items():
            if isinstance(value, dict):
                slot = total.setdefault(key, {})
                for k, v in value.items():
                    slot[k] = slot.get(k, 0) + v
            else:
                total[key] = total.get(key, 0) + value
    return total


def report() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    data = {split: load(split) for split in SPLITS}
    summary: dict = {}
    for split, (arrays, per_roi) in data.items():
        total = total_counts(per_roi)
        pixels = total["pixels"]
        entry = {
            "patches": int(arrays["rows"].shape[0]),
            "rois": len(per_roi),
            "pixels": pixels,
            "sar_nodata_frac": total["nodata"] / pixels,
            "sar_nodata_patches": total["nodata_patches"],
            "sar_fill": total["fill"],
            "optical_zero_frac": total["optical"]["zero"] / pixels,
            "neg_b12_frac": total["neg_b12"] / pixels,
            "neg_b12_near_nodata_frac_of_neg": total["neg_b12_near_nodata"] / max(total["neg_b12"], 1),
            "neg_b12_on_border_frac_of_neg": border_share(arrays["map_neg_b12"]),
            "optical_shadow_frac": float(arrays["opt_hist"][SHADOW_LEVEL] / pixels),
            "optical_saturated_frac": float(arrays["opt_hist"][255] / pixels),
            "shadow_patches": {str(t): int((shadow_fraction(arrays) > t).sum()) for t in SHADOW_PATCH_THRESHOLDS},
            "quantities": {},
        }
        for name in QUANTITIES + ("optical",):
            values = arrays[f"sample_{name}"]
            finite = values[np.isfinite(values)]
            if name == "optical":
                finite = finite[finite > 0]
            entry["quantities"][name] = {
                "zero_frac": total[name]["zero"] / pixels if name in total else None,
                "neg_frac": total[name].get("neg", 0) / pixels if name in total else None,
                "nonfinite_frac": total[name].get("nonfinite", 0) / pixels if name in total else None,
                "min": float(finite.min()),
                "max": float(finite.max()),
                "percentiles": dict(zip(map(str, PERCENTILES), map(float, np.percentile(finite, PERCENTILES)))),
            }
        summary[split] = entry
        summary[split]["between_roi"] = between_roi(arrays)
        summary[split]["per_roi"] = per_roi_rows(arrays)

    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT_DIR / "tables.md").write_text(tables(summary), encoding="utf-8")

    plot_histograms(plt, data)
    plot_maps(plt, data)
    plot_between_roi(plt, data)
    print(f"写出：{OUT_DIR}")


def shadow_fraction(arrays: dict) -> np.ndarray:
    """逐 patch 的光学阴影像素比，由抽样估计。"""
    return (arrays["sample_optical"].reshape(-1, SAMPLES_PER_PATCH) == SHADOW_LEVEL).mean(axis=1)


def border_share(count_map: np.ndarray) -> float:
    """出现次数图里落在 patch 四条边上的份额。"""
    inner = count_map[1:-1, 1:-1].sum()
    return float(1 - inner / max(count_map.sum(), 1))


def per_roi_rows(arrays: dict) -> list[dict]:
    rois = arrays["rois"]
    optical = arrays["sample_optical"].reshape(-1, SAMPLES_PER_PATCH)
    s1db = arrays["sample_S1_dB"].reshape(-1, SAMPLES_PER_PATCH)
    shadow = shadow_fraction(arrays)
    rows = []
    for roi in np.unique(rois):
        pick = rois == roi
        opt = optical[pick].ravel()
        lit = opt[opt > SHADOW_LEVEL]
        sar = s1db[pick].ravel()
        sar = sar[np.isfinite(sar)]
        o25, o50, o75 = np.percentile(lit, (25, 50, 75))
        s25, s50, s75 = np.percentile(sar, (25, 50, 75))
        rows.append({
            "roi": str(roi), "patches": int(pick.sum()),
            "opt_p50": float(o50), "opt_iqr": float(o75 - o25), "opt_levels": int(np.unique(lit).size),
            "shadow_frac": float(shadow[pick].mean()),
            **{f"shadow_patches_{t}": int((shadow[pick] > t).sum()) for t in SHADOW_PATCH_THRESHOLDS},
            "s1db_p50": float(s50), "s1db_iqr": float(s75 - s25),
        })
    return rows


def between_roi(arrays: dict) -> dict:
    """逐 patch 统计量的方差分成 ROI 间与 ROI 内两部分。"""
    out = {}
    rois = arrays["rois"]
    for field in ("opt_mean", "opt_std", "s1db_mean", "s1db_std", "s1db_p1", "s1db_p99"):
        values = arrays["rows"][:, PATCH_FIELDS.index(field)]
        ok = np.isfinite(values)
        values, groups = values[ok], rois[ok]
        means = {g: values[groups == g].mean() for g in np.unique(groups)}
        within = np.mean([values[groups == g].std() for g in means])
        out[field] = {
            "overall_mean": float(values.mean()),
            "overall_std": float(values.std()),
            "roi_mean_min": float(min(means.values())),
            "roi_mean_max": float(max(means.values())),
            "roi_mean_std": float(np.std(list(means.values()))),
            "within_roi_std_avg": float(within),
        }
    return out


def tables(summary: dict) -> str:
    lines = ["# 数值分布：数字表", "", "由 `stats.py report` 生成，勿手改。分位数由每 patch 抽样 "
             f"{SAMPLES_PER_PATCH} 像素算得；零值、负值、非有限比例为全部像素的精确计数。", ""]
    lines += ["## 概况", "", "| 划分 | ROI | patch 对 | SAR nodata 像素比 | 含 nodata 的 patch | 填充值像素 | 光学零值像素比 | b1 或 b2 为负的像素比 | 其中距 nodata ≤3 px |",
              "|---|---|---|---|---|---|---|---|---|"]
    for split, e in summary.items():
        lines.append(f"| {split} | {e['rois']} | {e['patches']} | {e['sar_nodata_frac']:.2e} | {e['sar_nodata_patches']} | "
                     f"{e['sar_fill']} | {e['optical_zero_frac']:.2e} | {e['neg_b12_frac']:.2e} | "
                     f"{e['neg_b12_near_nodata_frac_of_neg']:.1%} |")
    lines += ["", "b1 或 b2 为负的像素里落在 patch 四条边上的份额："
              + "，".join(f"{split} {e['neg_b12_on_border_frac_of_neg']:.0%}" for split, e in summary.items()) + "。"]
    lines += ["", "## 光学阴影与饱和", "",
              f"阴影 = 灰度 {SHADOW_LEVEL}（像素比为精确计数）；含阴影的 patch 数由抽样估计。", "",
              "| 划分 | 阴影像素比 | 灰度 255 像素比 | " + " | ".join(f"阴影 > {t:.0%} 的 patch" for t in SHADOW_PATCH_THRESHOLDS) + " |",
              "|---|---|---|" + "---|" * len(SHADOW_PATCH_THRESHOLDS)]
    for split, e in summary.items():
        lines.append(f"| {split} | {e['optical_shadow_frac']:.2%} | {e['optical_saturated_frac']:.1e} | "
                     + " | ".join(str(e["shadow_patches"][str(t)]) for t in SHADOW_PATCH_THRESHOLDS) + " |")
    header = "| 量 | 零值 | 负值 | 无定义 | 最小 | " + " | ".join(f"p{p}" for p in PERCENTILES) + " | 最大 |"
    for split, e in summary.items():
        lines += ["", f"## 各量分布：{split}", "", header, "|" + "---|" * (len(PERCENTILES) + 6)]
        for name, q in e["quantities"].items():
            frac = lambda v: "—" if v is None else f"{v:.2e}"
            pct = " | ".join(_fmt(v) for v in q["percentiles"].values())
            lines.append(f"| {name} | {frac(q['zero_frac'])} | {frac(q['neg_frac'])} | {frac(q['nonfinite_frac'])} | "
                         f"{_fmt(q['min'])} | {pct} | {_fmt(q['max'])} |")
    lines += ["", "## 逐 patch 统计量在 ROI 之间的差异", "",
              "| 划分 | 统计量 | 全体均值 | 全体标准差 | ROI 均值最小 | ROI 均值最大 | ROI 均值的标准差 | ROI 内标准差（平均） |",
              "|---|---|---|---|---|---|---|---|"]
    for split, e in summary.items():
        for field, v in e["between_roi"].items():
            lines.append(f"| {split} | {field} | {v['overall_mean']:.2f} | {v['overall_std']:.2f} | {v['roi_mean_min']:.2f} | "
                         f"{v['roi_mean_max']:.2f} | {v['roi_mean_std']:.2f} | {v['within_roi_std_avg']:.2f} |")
    lines += ["", "## 逐 ROI", "",
              "光学统计量不含阴影像素；灰度级数为抽样中出现的不同灰度个数。", "",
              "| 划分 | ROI | patch 对 | 光学中位 | 光学 IQR | 灰度级数 | 阴影像素比 | "
              + " | ".join(f"阴影 > {t:.0%} 的 patch" for t in SHADOW_PATCH_THRESHOLDS) + " | S1 dB 中位 | S1 dB IQR |",
              "|---|---|---|---|---|---|---|" + "---|" * len(SHADOW_PATCH_THRESHOLDS) + "---|---|"]
    for split, e in summary.items():
        for r in e["per_roi"]:
            lines.append(f"| {split} | {r['roi']} | {r['patches']} | {r['opt_p50']:.0f} | {r['opt_iqr']:.0f} | {r['opt_levels']} | "
                         f"{r['shadow_frac']:.1%} | " + " | ".join(str(r[f"shadow_patches_{t}"]) for t in SHADOW_PATCH_THRESHOLDS)
                         + f" | {r['s1db_p50']:.2f} | {r['s1db_iqr']:.2f} |")
    return "\n".join(lines) + "\n"


def _fmt(v: float) -> str:
    return f"{v:.3g}" if abs(v) >= 1e-2 or v == 0 else f"{v:.2e}"


def plot_histograms(plt, data: dict) -> None:
    names = ("optical", "b1_dB", "b2_dB", "S1_dB", "SC_dB", "OC_dB", "b3", "b4", "CPR", "m")
    fig, axes = plt.subplots(2, 5, figsize=(22, 8))
    for ax, name in zip(axes.ravel(), names):
        for split, (arrays, _) in data.items():
            values = arrays[f"sample_{name}"]
            values = values[np.isfinite(values)]
            if name == "optical":
                # 整数灰度按整数分桶，否则桶宽不整会画出假的梳齿；阴影单列在表里
                ax.hist(values[values > SHADOW_LEVEL], bins=np.arange(1.5, 256.5), density=True, histtype="step", label=split)
                continue
            low, high = np.percentile(np.concatenate([
                a[f"sample_{name}"][np.isfinite(a[f"sample_{name}"])] for a, _ in data.values()
            ]), (0.1, 99.9))
            ax.hist(values, bins=200, range=(low, high), density=True, histtype="step", label=split)
        ax.set_title(name)
    axes[0, 0].legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "histograms.png", dpi=110)
    plt.close(fig)


def plot_maps(plt, data: dict) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(15, 9))
    for col, (split, (arrays, _)) in enumerate(data.items()):
        n = arrays["rows"].shape[0]
        for row, key in enumerate(("zero_any", "neg_b12")):
            ax = axes[row, col]
            image = ax.imshow(arrays[f"map_{key}"] / n, cmap="magma", vmin=0)
            ax.set_title(f"{split}：{'任一波段为零' if key == 'zero_any' else 'b1 或 b2 为负'}（每像素出现率）")
            fig.colorbar(image, ax=ax, fraction=0.046)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "position_maps.png", dpi=110)
    plt.close(fig)


def plot_between_roi(plt, data: dict) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(22, 10))
    for ax, field in zip(axes, ("s1db_p50", "opt_p50")):
        groups, labels, colors = [], [], []
        for split, (arrays, _) in data.items():
            values = arrays["rows"][:, PATCH_FIELDS.index(field)]
            for roi in np.unique(arrays["rois"]):
                v = values[(arrays["rois"] == roi) & np.isfinite(values)]
                groups.append(v)
                labels.append(roi[4:])
                colors.append({"Train": "C0", "Val": "C1", "Test": "C2"}[split])
        parts = ax.boxplot(groups, tick_labels=labels, showfliers=False, patch_artist=True)
        for box, color in zip(parts["boxes"], colors):
            box.set_facecolor(color)
        ax.set_title(f"逐 patch {field}，按 ROI（蓝 Train / 橙 Val / 绿 Test）")
        ax.tick_params(axis="x", labelsize=7, rotation=90)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "between_roi.png", dpi=110)
    plt.close(fig)


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=("collect", "report"))
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)
    if args.step == "collect":
        collect(args.workers)
    else:
        report()


if __name__ == "__main__":
    main(sys.argv[1:])
