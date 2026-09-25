"""PROTOTYPE（「标注质量」页 UI 原型，用完即弃）：画页面上的 6 张图。

    PYTHONPATH=src conda run -n moon-dataset python research/annotation-quality-ui/figures.py

数字读本目录的 `summary.json`（研究分支 `research/ground-truth-residuals`）与 `pairs.csv`
（研究分支 `research/annotation-repeat`）；逐 ROI 的 σ 与入射角抄自前者的 `tables.md`。
影像读数据盘（config.toml 的 data_root 不对时用环境变量 MOON_DATA 覆盖）。
"""

import csv
import json
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from osgeo import gdal

from moondata.config import REPO_ROOT
from moondata.sources import dataset_overlap_images, load_tie_points

HERE = Path(__file__).resolve().parent
OUT = HERE / "figs"
DATA = Path(os.environ.get("MOON_DATA", "G:/Lunar_Optical_SAR_Registration_Dataset"))

INK, INK2, RULE, BLUE, ORANGE = "#1B2733", "#55616D", "#C9CFD4", "#1F5FAE", "#E39B1B"
plt.rcParams.update({
    "font.family": ["Microsoft YaHei", "SimHei", "sans-serif"], "font.size": 10,
    "svg.fonttype": "none", "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
    "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": "none", "axes.facecolor": "none",
})

# tables.md「逐 ROI」：入射角、σx、σy
ROIS = {
    "ROI_006": (49.5, 4.22, 1.23), "ROI_007": (50.7, 3.91, 1.24), "ROI_011": (51.4, 3.52, 1.31),
    "ROI_020": (49.4, 3.34, 1.14), "ROI_035": (51.0, 3.87, 1.20), "ROI_037": (53.0, 2.94, 1.28),
    "ROI_049": (52.5, 2.61, 1.25), "ROI_054": (47.5, 3.83, 1.13), "ROI_059": (53.7, 1.69, 1.22),
    "ROI_070": (52.7, 3.21, 1.20), "ROI_071": (52.6, 2.60, 1.24), "ROI_075": (51.8, 3.81, 1.19),
    "ROI_080": (53.7, 3.49, 1.03),
}


def save(fig, name):
    fig.savefig(OUT / f"{name}.svg")
    fig.savefig(OUT / f"{name}.preview.png", dpi=90, facecolor="white")
    plt.close(fig)


def stretch(a):
    lo, hi = np.percentile(a, [1, 99])
    return np.clip((a - lo) / (hi - lo), 0, 1)


def affine_example():
    """一个 8 点 patch：左，错位箭头；右，扣掉拟合的仿射后剩下的残差（放大画）。"""
    split, roi, patch = "Val", "ROI_035", 3
    pts = np.loadtxt(REPO_ROOT / "data" / "ground-truth" / split / roi / f"patch_{patch}.txt")[:, :4]
    pts[:, [1, 3]] *= -1
    p, d = pts[:, :2], pts[:, 2:] - pts[:, :2]
    X = np.column_stack([p, np.ones(len(p))])
    coef, *_ = np.linalg.lstsq(X, d, rcond=None)
    fit, res = X @ coef, d - X @ coef
    img = gdal.Open(str(DATA / "Processed_Data" / split / roi / "Optical" / f"patch_{patch}.tif")).ReadAsArray()
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 4.3))
    for ax, title in zip(axes, ("错位 d = q − p（实线）与拟合的仿射（虚线）", "残差 d − 仿射，放大 20 倍")):
        ax.imshow(stretch(img.astype(float)), cmap="gray", extent=(0, 512, 512, 0))
        ax.scatter(*p.T, s=18, color=ORANGE, zorder=3)
        ax.set_title(title, fontsize=9.5, color=INK)
        ax.set_xticks([]), ax.set_yticks([])
    a, b = axes
    a.quiver(*p.T, *d.T, angles="xy", scale_units="xy", scale=1, color=ORANGE, width=0.006)
    a.quiver(*p.T, *fit.T, angles="xy", scale_units="xy", scale=1, color=BLUE, width=0.003, alpha=0.9)
    b.quiver(*p.T, *(20 * res).T, angles="xy", scale_units="xy", scale=1, color=BLUE, width=0.006)
    fig.tight_layout()
    save(fig, "affine-example")


def roi_incidence():
    inc, sx, sy = (np.array(v) for v in zip(*ROIS.values()))
    fig, ax = plt.subplots(figsize=(6.4, 3.3))
    ax.plot(inc, sx, "o", color=ORANGE, label="σ̂x（Spearman −0.68，p = 0.01）")
    ax.plot(inc, sy, "o", color=INK, label="σ̂y（Spearman 0.10，p = 0.73）")
    ax.set_xlabel("SAR 入射角（°）")
    ax.set_ylabel("拟合残差 σ̂（像素）")
    ax.set_ylim(0, 4.6)
    ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    fig.tight_layout()
    save(fig, "roi-incidence")


def repeat_example():
    """ROI_037：第 441 个评测真值点与第 13 个控制点落在同一撞击坑上。"""
    roi, gi, ti = "ROI_037", 441, 13
    row = next(r for r in csv.DictReader((HERE / "pairs.csv").open()) if r["roi"] == roi
               and int(r["gt_index"]) == gi and int(r["tie_index"]) == ti)
    dp = np.array([float(row["dp_x"]), float(row["dp_y"])])
    e = np.array([float(row["e_x"]), float(row["e_y"])])
    opt_tie, sar_tie = load_tie_points(REPO_ROOT, roi)
    P, Q = opt_tie[ti], sar_tie[ti]
    clicks = {"光学": (P, P + dp), "SAR": (Q, Q + dp + e)}
    opt, sar = dataset_overlap_images(DATA, roi)
    half = 24
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.8))
    for ax, (side, path) in zip(axes, (("光学", opt), ("SAR", sar))):
        tie, gt = clicks[side]
        c0, r0 = (np.round(tie) - half).astype(int)
        ds = gdal.Open(str(path))
        a = ds.GetRasterBand(1).ReadAsArray(int(c0), int(r0), 2 * half, 2 * half).astype(float)
        if side == "SAR":
            a = 10 * np.log10(np.maximum(a, 1e-6))
        ax.imshow(stretch(a), cmap="gray", extent=(c0 - 0.5, c0 + 2 * half - 0.5, r0 + 2 * half - 0.5, r0 - 0.5))
        ax.plot(*tie, "+", ms=14, mew=2, color=BLUE, label="控制点（ENVI，整数像素）")
        ax.plot(*gt, "x", ms=11, mew=2, color=ORANGE, label="评测真值点（ArcGIS）")
        ax.set_title(f"{side}（{2 * half}×{2 * half} 像素）", fontsize=9.5, color=INK)
        ax.set_xticks([]), ax.set_yticks([])
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.legend(*axes[0].get_legend_handles_labels(), frameon=False, fontsize=8.5, loc="lower center", ncol=2)
    save(fig, "repeat-example")


def summary_axis():
    """估计结果画在两根轴上：上界画成从 0 起的灰条，重复测量画成点加标准误。"""
    fig, (ax, ay) = plt.subplots(1, 2, figsize=(8.6, 2.2), sharey=True)
    names = ["最小二乘拟合残差", "变异函数", "重复测量"]
    for axis, rows, title in (
        (ax, [None, None, (1.14, 0.15)], "x（距离向）"),
        (ay, [(1.21, (1.19, 1.23)), (1.16, (0.83, 1.16)), (0.93, 0.12)], "y（方位向）"),
    ):
        for k, r in enumerate(rows):
            y = 2 - k
            if r is None:
                axis.text(0.05, y, "—", va="center", color=INK2)
            elif k < 2:
                value, (lo, hi) = r
                axis.plot([0, value], [y, y], color=RULE, lw=7, solid_capstyle="butt")
                axis.plot([lo, hi], [y, y], color=INK, lw=2)
                axis.plot([lo, hi], [y, y], "|", ms=10, color=INK)
            else:
                value, se = r
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


def fit(h, n, g, hmax, power):
    m = h <= hmax
    w = np.sqrt(n[m]) / g[m]
    a = np.column_stack([np.ones(m.sum()), h[m] ** power])
    return np.linalg.lstsq(a * w[:, None], g[m] * w, rcond=None)[0]


def toy():
    """一维例子：平滑的错位 f(s) 加上每个点独立的标注误差（σ = 1）。"""
    rng = np.random.default_rng(3)
    f = lambda s: 4 * np.sin(s / 18) + 2 * np.sin(s / 7 + 1)
    fig, (a, b) = plt.subplots(1, 2, figsize=(9.2, 3.2), gridspec_kw={"width_ratios": [1.35, 1]})
    s = np.sort(rng.uniform(0, 100, 26))
    s[8], s[9] = 31.0, 33.0
    r = f(s) + rng.normal(0, 1, s.size)
    ss = np.linspace(0, 100, 400)
    a.plot(ss, f(ss), color=RULE, lw=2.2, label="真实错位 f(s)")
    a.scatter(s, r, s=16, color=INK, zorder=3, label="读数 r = f(s) + e")
    for i, j, c, txt, dy in ((8, 9, BLUE, "近：差里几乎只有 e", -1.9), (3, 20, ORANGE, "远：差里还有 f 的变化", 1.0)):
        a.plot([s[i], s[j]], [r[i], r[j]], color=c, lw=1.4, zorder=2)
        y = (min if dy < 0 else max)(r[i], r[j]) + dy
        a.annotate(txt, ((s[i] + s[j]) / 2 + (0 if dy < 0 else 12), y), color=c, ha="center", fontsize=9)
    a.set_xlabel("位置 s")
    a.set_ylabel("错位")
    a.legend(frameon=False, fontsize=8.5, loc="lower left")

    s2 = rng.uniform(0, 3000, 1500)
    r2 = f(s2) + rng.normal(0, 1, s2.size)
    i, j = np.triu_indices(s2.size, 1)
    h = np.abs(s2[i] - s2[j])
    d = 0.5 * (r2[i] - r2[j]) ** 2
    edges = np.arange(0, 42, 3.0)
    k = np.digitize(h, edges) - 1
    ok = (k >= 0) & (k < edges.size - 1)
    n = np.bincount(k[ok], minlength=edges.size - 1)
    hm = np.bincount(k[ok], weights=h[ok], minlength=edges.size - 1) / n
    g = np.bincount(k[ok], weights=d[ok], minlength=edges.size - 1) / n
    b.scatter(hm, g, s=16, color=INK, zorder=3, label="γ(h)")
    c = fit(hm, n, g, 12, 2)
    hh = np.linspace(0, 14, 50)
    b.plot(hh, c[0] + c[1] * hh**2, color=BLUE, lw=1.4, ls="--")
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


def moon_variogram(summary):
    p = summary["variogram"]["pooled"]
    h, n, gx, gy = (np.array(p[k]) for k in ("h", "n", "gx", "gy"))
    fig, (a, b) = plt.subplots(1, 2, figsize=(9.2, 3.4))
    m = h <= 320
    a.errorbar(h[m], gy[m], yerr=gy[m] * np.sqrt(2 / n[m]), fmt="o", ms=4, color=INK, ecolor=INK2, lw=0.8,
               capsize=2, zorder=3, label="y 分量")
    hh = np.linspace(0, 160, 50)
    ends = []
    for power, ls in ((1, "--"), (2, ":")):
        for hmax in (60, 100, 150):
            c = fit(h, n, gy, hmax, power)
            ends.append(c[0])
            a.plot(hh[hh <= hmax], c[0] + c[1] * hh[hh <= hmax] ** power, color=BLUE, lw=1, ls=ls)
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


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    affine_example()
    roi_incidence()
    toy()
    moon_variogram(json.loads((HERE / "summary.json").read_text(encoding="utf-8")))
    repeat_example()
    summary_axis()
    print("已写出", sorted(q.name for q in OUT.glob("*.svg")))
