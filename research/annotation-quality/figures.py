"""「标注质量」页上的 6 张图，写到 `docs/assets/annotation-quality/`。

    PYTHONPATH=src python research/annotation-quality/figures.py [数据根]

数字读 `estimate.py` 写出的 `results.json`。两张例子图要读影像：「最小二乘拟合残差」的
例子读一个光学 patch，「重复测量」的例子读重叠区影像上的一小块；数据根默认取
`config.toml`，本机路径不同时作为参数给出。SVG 里的文字保留为文字，随页面字体显示；
固定了 hashsalt、去掉了日期，重跑逐字节不变。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from moondata.config import REPO_ROOT, load_config
from moondata.preprocess import SAR_FLOOR_DB
from moondata.raster import read_rows
from moondata.sources import dataset_overlap_images, dataset_patch_dir, ground_truth_file, load_tie_points

HERE = Path(__file__).resolve().parent
OUT = REPO_ROOT / "docs" / "assets" / "annotation-quality"

AFFINE_EXAMPLE = ("Val", "ROI_035", 3)
"""8 个点、错位接近仿射的一个 patch。"""
REPEAT_EXAMPLE = ("ROI_037", 441, 13)
"""(ROI, 评测真值点序号, 控制点序号)：两次都点在同一个小撞击坑上。"""

INK, INK2, RULE, BLUE, ORANGE = "#1B2733", "#55616D", "#C9CFD4", "#1F5FAE", "#E39B1B"
plt.rcParams.update({
    "font.family": ["Microsoft YaHei", "SimHei", "sans-serif"], "font.size": 10,
    "svg.fonttype": "none", "svg.hashsalt": "annotation-quality",
    "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.unicode_minus": False,
    "figure.facecolor": "none", "axes.facecolor": "none",
})


def save(fig: plt.Figure, name: str) -> None:
    fig.savefig(OUT / f"{name}.svg", metadata={"Date": None})
    plt.close(fig)


def stretch(a: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(a, [1, 99])
    return np.clip((a - lo) / (hi - lo), 0, 1)


def affine_example(data_root: Path) -> None:
    """左，错位箭头与拟合的仿射；右，扣掉仿射后的残差，放大 20 倍画。"""
    split, roi, patch = AFFINE_EXAMPLE
    a = np.loadtxt(ground_truth_file(REPO_ROOT, split, roi, patch), ndmin=2)
    a[:, [1, 3]] *= -1
    p, d = a[:, :2], a[:, 2:4] - a[:, :2]
    x = np.column_stack([p, np.ones(len(p))])
    coef, *_ = np.linalg.lstsq(x, d, rcond=None)
    fit, resid = x @ coef, d - x @ coef
    image = read_rows(dataset_patch_dir(data_root, split, roi) / "Optical" / f"patch_{patch}.tif", 0, 512)[0]
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 4.3))
    for ax, title in zip(axes, ("错位 d = q − p（橙）与拟合的仿射（蓝）", "残差 d − 仿射，放大 20 倍")):
        ax.imshow(stretch(image), cmap="gray", extent=(0, 512, 512, 0))
        ax.scatter(*p.T, s=18, color=ORANGE, zorder=3)
        ax.set_title(title, fontsize=9.5, color=INK)
        ax.set_xticks([]), ax.set_yticks([])
    left, right = axes
    left.quiver(*p.T, *d.T, angles="xy", scale_units="xy", scale=1, color=ORANGE, width=0.006)
    left.quiver(*p.T, *fit.T, angles="xy", scale_units="xy", scale=1, color=BLUE, width=0.003, alpha=0.9)
    right.quiver(*p.T, *(20 * resid).T, angles="xy", scale_units="xy", scale=1, color=BLUE, width=0.006)
    fig.tight_layout()
    save(fig, "affine-example")


def roi_incidence(ls: dict) -> None:
    inc = [r["incidence"] for r in ls["rois"]]
    fig, ax = plt.subplots(figsize=(6.4, 3.3))
    (rx, px), (ry, py) = ls["spearman_x"], ls["spearman_y"]
    ax.plot(inc, [r["sigma_x"] for r in ls["rois"]], "o", color=ORANGE, label=f"σ̂x（Spearman {rx:.2f}，p = {px:.2f}）")
    ax.plot(inc, [r["sigma_y"] for r in ls["rois"]], "o", color=INK, label=f"σ̂y（Spearman {ry:.2f}，p = {py:.2f}）")
    ax.set_xlabel("SAR 入射角（°）")
    ax.set_ylabel("拟合残差 σ̂（像素）")
    ax.set_ylim(0, 4.6)
    ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    fig.tight_layout()
    save(fig, "roi-incidence")


def fit_line(h: np.ndarray, g: np.ndarray, n: np.ndarray, power: int, hmax: float) -> tuple[float, float]:
    m = h <= hmax
    w = np.sqrt(n[m]) / g[m]
    a = np.column_stack([np.ones(m.sum()), h[m] ** power]) * w[:, None]
    c0, b = np.linalg.lstsq(a, g[m] * w, rcond=None)[0]
    return float(c0), float(b)


def variogram_example() -> None:
    """一维的例子：平滑的错位 f(s) 加上每个点独立的标注误差（σ = 1）。"""
    rng = np.random.default_rng(3)

    def f(s: np.ndarray) -> np.ndarray:
        return 4 * np.sin(s / 18) + 2 * np.sin(s / 7 + 1)

    fig, (a, b) = plt.subplots(1, 2, figsize=(9.2, 3.2), gridspec_kw={"width_ratios": [1.35, 1]})
    s = np.sort(rng.uniform(0, 100, 26))
    s[8], s[9] = 31.0, 33.0
    r = f(s) + rng.normal(0, 1, s.size)
    ss = np.linspace(0, 100, 400)
    a.plot(ss, f(ss), color=RULE, lw=2.2, label="真实错位 f(s)")
    a.scatter(s, r, s=16, color=INK, zorder=3, label="读数 r = f(s) + e")
    for i, j, color, text, dy in ((8, 9, BLUE, "近：差里几乎只有 e", -1.9), (3, 20, ORANGE, "远：差里还有 f 的变化", 1.0)):
        a.plot([s[i], s[j]], [r[i], r[j]], color=color, lw=1.4, zorder=2)
        y = (min if dy < 0 else max)(r[i], r[j]) + dy
        a.annotate(text, ((s[i] + s[j]) / 2 + (0 if dy < 0 else 12), y), color=color, ha="center", fontsize=9)
    a.set_xlabel("位置 s")
    a.set_ylabel("错位")
    a.legend(frameon=False, fontsize=8.5, loc="lower left")

    s2 = rng.uniform(0, 3000, 1500)
    r2 = f(s2) + rng.normal(0, 1, s2.size)
    i, j = np.triu_indices(s2.size, 1)
    h = np.abs(s2[i] - s2[j])
    half_sq = 0.5 * (r2[i] - r2[j]) ** 2
    edges = np.arange(0, 42, 3.0)
    k = np.digitize(h, edges) - 1
    ok = k < edges.size - 1
    n = np.bincount(k[ok], minlength=edges.size - 1)
    hm = np.bincount(k[ok], weights=h[ok], minlength=edges.size - 1) / n
    g = np.bincount(k[ok], weights=half_sq[ok], minlength=edges.size - 1) / n
    b.scatter(hm, g, s=16, color=INK, zorder=3, label="γ(h)")
    c0, slope = fit_line(hm, g, n, 2, 12)
    hh = np.linspace(0, 14, 50)
    b.plot(hh, c0 + slope * hh**2, color=BLUE, lw=1.4, ls="--")
    b.axhline(1.0, color=BLUE, lw=0.8, ls=":")
    b.annotate("外推到 h = 0：截距 = σ² = 1", (0, 1.0), (6, 0.35), color=BLUE, fontsize=9,
               arrowprops={"arrowstyle": "->", "color": BLUE, "lw": 0.8})
    b.set_xlim(-1, 41)
    b.set_ylim(0, None)
    b.set_xlabel("点间距 h")
    b.set_ylabel("γ(h)")
    b.legend(frameon=False, fontsize=8.5, loc="upper left")
    fig.tight_layout()
    save(fig, "variogram-example")


def moon_variogram(vg: dict) -> None:
    bins = vg["bins"]
    h, n, gx, gy = (np.array(bins[k]) for k in ("h", "n", "gx", "gy"))
    fig, (a, b) = plt.subplots(1, 2, figsize=(9.2, 3.4))
    m = h <= 320
    a.errorbar(h[m], gy[m], yerr=gy[m] * np.sqrt(2 / n[m]), fmt="o", ms=4, color=INK, ecolor=INK2, lw=0.8,
               capsize=2, zorder=3, label="y 分量")
    hh = np.linspace(0, 160, 50)
    for fit in vg["fits_y"]:
        part = hh <= fit["hmax"]
        a.plot(hh[part], fit["c0"] + fit["b"] * hh[part] ** fit["power"], color=BLUE, lw=1,
               ls="--" if fit["power"] == 1 else ":")
    ends = [fit["c0"] for fit in vg["fits_y"]]
    a.plot([0, 0], [min(ends), max(ends)], color=BLUE, lw=5, solid_capstyle="butt", alpha=0.45)
    a.annotate(f"块金值 {min(ends):.2f}–{max(ends):.2f} 像素²", (0, 0.95), (35, 0.45), color=BLUE, fontsize=9,
               arrowprops={"arrowstyle": "->", "color": BLUE, "lw": 0.8})
    a.set_xlim(-8, 330)
    a.set_ylim(0, 2.2)
    a.set_xlabel("点间距 h（像素）")
    a.set_ylabel("γ（像素²）")
    a.legend(frameon=False, fontsize=8.5, loc="upper left")
    a.set_title("y：6 条短距离外推（虚线线性、点线二次）", fontsize=9.5, color=INK)
    b.plot(h[m], gx[m], "o", ms=4, color=ORANGE, label="x 分量")
    b.plot(h[m], gy[m], "o", ms=4, color=INK, label="y 分量")
    b.set_xlim(-8, 330)
    b.set_ylim(0, None)
    b.set_xlabel("点间距 h（像素）")
    b.set_ylabel("γ（像素²）")
    b.legend(frameon=False, fontsize=8.5, loc="upper left")
    b.set_title("x：随距离陡升，截距定不下来", fontsize=9.5, color=INK)
    fig.tight_layout()
    save(fig, "moon-variogram")


def repeat_example(rp: dict, data_root: Path) -> None:
    """同一处地物上的两次点击：控制点（整数像素）与评测真值点，光学、SAR 各一小块。"""
    roi, gt_index, tie_index = REPEAT_EXAMPLE
    pair = next(p for p in rp["pairs"]
                if (p["roi"], p["gt_index"], p["tie_index"]) == REPEAT_EXAMPLE)
    offset, delta = np.array(pair["optical_offset"]), np.array(pair["delta"])
    optical_tie, sar_tie = load_tie_points(REPO_ROOT, roi)
    clicks = {"光学": (optical_tie[tie_index], optical_tie[tie_index] + offset),
              "SAR": (sar_tie[tie_index], sar_tie[tie_index] + offset + delta)}
    optical_image, sar_image = dataset_overlap_images(data_root, roi)
    half = 24
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.8))
    for ax, (side, path) in zip(axes, (("光学", optical_image), ("SAR", sar_image))):
        tie, gt = clicks[side]
        c0, r0 = (np.round(tie) - half).astype(int)
        bands = (1, 2) if side == "SAR" else (1,)
        block = read_rows(path, r0, r0 + 2 * half, bands)[:, :, c0:c0 + 2 * half].astype(float)
        if side == "SAR":
            block = 10 * np.log10(np.maximum(block.sum(axis=0), 10 ** (SAR_FLOOR_DB / 10)))
        else:
            block = block[0]
        ax.imshow(stretch(block), cmap="gray",
                  extent=(c0 - 0.5, c0 + 2 * half - 0.5, r0 + 2 * half - 0.5, r0 - 0.5))
        ax.plot(*tie, "+", ms=14, mew=2, color=BLUE, label="控制点（ENVI，整数像素）")
        ax.plot(*gt, "x", ms=11, mew=2, color=ORANGE, label="评测真值点（ArcGIS）")
        ax.set_title(f"{side}（{2 * half}×{2 * half} 像素）", fontsize=9.5, color=INK)
        ax.set_xticks([]), ax.set_yticks([])
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.legend(*axes[0].get_legend_handles_labels(), frameon=False, fontsize=8.5, loc="lower center", ncol=2)
    save(fig, "repeat-example")


def summary_axis(results: dict) -> None:
    """估计结果画在 x、y 两根轴上：上界画成从 0 起的灰条，重复测量画成点加标准误。"""
    ls, vg, rp = results["least_squares"], results["variogram"], results["repeat"]
    sigma_y = ls["after"]["sigma"][1]
    nugget = np.sqrt([f["c0"] for f in vg["fits_y"]])
    row = rp["rows"][0]
    fig, (ax, ay) = plt.subplots(1, 2, figsize=(8.6, 2.2), sharey=True)
    names = ["最小二乘拟合残差", "变异函数", "重复测量"]
    for axis, rows, title in (
        (ax, [None, None, (row["sigma"][0], row["se"][0])], "x（距离向）"),
        (ay, [(sigma_y, ls["after"]["ci_y"]), (nugget.max(), (nugget.min(), nugget.max())),
              (row["sigma"][1], row["se"][1])], "y（方位向）"),
    ):
        for k, entry in enumerate(rows):
            y = 2 - k
            if entry is None:
                axis.text(0.05, y, "—", va="center", color=INK2)
            elif k < 2:
                value, (lo, hi) = entry
                axis.plot([0, value], [y, y], color=RULE, lw=7, solid_capstyle="butt")
                axis.plot([lo, hi], [y, y], color=INK, lw=2)
                axis.plot([lo, hi], [y, y], "|", ms=10, color=INK)
            else:
                value, se = entry
                axis.errorbar(value, y, xerr=se, fmt="o", color=BLUE, capsize=3)
        axis.set_xlim(0, 1.6)
        axis.set_title(title, fontsize=9.5, color=INK)
        axis.set_xlabel("σ̂（像素）")
        axis.spines["left"].set_visible(False)
        axis.tick_params(axis="y", length=0)
    ax.set_yticks([2, 1, 0], names)
    ax.set_ylim(-0.6, 2.6)
    fig.tight_layout()
    save(fig, "summary-axis")


def main() -> None:
    data_root = Path(sys.argv[1]) if len(sys.argv) > 1 else load_config().require_data_root()
    results = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    affine_example(data_root)
    roi_incidence(results["least_squares"])
    variogram_example()
    moon_variogram(results["variogram"])
    repeat_example(results["repeat"], data_root)
    summary_axis(results)
    print("已写出", sorted(p.name for p in OUT.glob("*.svg")))


if __name__ == "__main__":
    main()
