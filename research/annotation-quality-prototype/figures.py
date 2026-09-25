"""PROTOTYPE（「标注质量」页原型，用完即弃）：画草稿页用的三张 SVG。

    conda run -n moon-dataset python research/annotation-quality-prototype/figures.py

只读 `research/ground-truth-residuals/summary.json`（研究分支的产出）。
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "figs"
SUMMARY = HERE.parent / "ground-truth-residuals" / "summary.json"

INK, INK2, RULE, BLUE, ORANGE = "#1B2733", "#55616D", "#C9CFD4", "#1F5FAE", "#E39B1B"
plt.rcParams.update({
    "font.family": ["Microsoft YaHei", "SimHei", "sans-serif"], "font.size": 10,
    "svg.fonttype": "none", "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
    "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": "none", "axes.facecolor": "none",
})


def save(fig, name):
    fig.savefig(OUT / f"{name}.svg")
    fig.savefig(OUT / f"{name}.preview.png", dpi=90, facecolor="white")


def fit(h, n, g, hmax, power):
    m = h <= hmax
    w = np.sqrt(n[m]) / g[m]
    a = np.column_stack([np.ones(m.sum()), h[m] ** power])
    return np.linalg.lstsq(a * w[:, None], g[m] * w, rcond=None)[0]


def toy():
    """一维例子：平滑的错位场 f(s) 加上每个点独立的标注误差（σ = 1）。"""
    rng = np.random.default_rng(3)
    f = lambda s: 4 * np.sin(s / 18) + 2 * np.sin(s / 7 + 1)
    fig, (a, b) = plt.subplots(1, 2, figsize=(9.2, 3.2), gridspec_kw={"width_ratios": [1.35, 1]})
    s = np.sort(rng.uniform(0, 100, 26))
    s[8], s[9] = 31.0, 33.0
    r = f(s) + rng.normal(0, 1, s.size)
    ss = np.linspace(0, 100, 400)
    a.plot(ss, f(ss), color=RULE, lw=2.2, label="错位场 f(s)（看不到）")
    a.scatter(s, r, s=16, color=INK, zorder=3, label="标注得到的 r = f(s) + ε")
    for i, j, c, txt, dy in ((8, 9, BLUE, "近：差 ≈ 只有 ε", -1.9), (3, 20, ORANGE, "远：差里还有场的变化", 1.0)):
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
    b.scatter(hm, g, s=16, color=INK, zorder=3, label="γ(h)：各距离档 ½·(差)² 的平均")
    c = fit(hm, n, g, 12, 2)
    hh = np.linspace(0, 14, 50)
    b.plot(hh, c[0] + c[1] * hh**2, color=BLUE, lw=1.4, ls="--")
    b.axhline(1.0, color=BLUE, lw=0.8, ls=":")
    b.annotate("外推到 h = 0：截距 ≈ σ² = 1\n（nugget）", (0, 1.0), (6, 0.35), color=BLUE, fontsize=9,
               arrowprops={"arrowstyle": "->", "color": BLUE, "lw": 0.8})
    b.set_xlim(-1, 41)
    b.set_ylim(0, None)
    b.set_xlabel("点间距 h")
    b.set_ylabel("γ(h)")
    b.legend(frameon=False, fontsize=8.5, loc="upper left")
    fig.tight_layout()
    save(fig, "toy")
    plt.close(fig)


def moon(summary):
    p = summary["variogram"]["pooled"]
    h, n, gx, gy = (np.array(p[k]) for k in ("h", "n", "gx", "gy"))
    fig, (a, b) = plt.subplots(1, 2, figsize=(9.2, 3.4))
    m = h <= 320
    a.errorbar(h[m], gy[m], yerr=gy[m] * np.sqrt(2 / n[m]), fmt="o", ms=4, color=INK, ecolor=INK2, lw=0.8,
               capsize=2, zorder=3, label="y 分量，经验 γ（误差棒：约 1 倍标准误）")
    hh = np.linspace(0, 160, 50)
    lo, hi = [], []
    for power, ls in ((1, "--"), (2, ":")):
        for hmax in (60, 100, 150):
            c = fit(h, n, gy, hmax, power)
            lo.append(c[0]); hi.append(c[0])
            a.plot(hh[hh <= hmax], c[0] + c[1] * hh[hh <= hmax] ** power, color=BLUE, lw=1, ls=ls)
    a.plot([0, 0], [min(lo), max(hi)], color=BLUE, lw=5, solid_capstyle="butt", alpha=0.45)
    a.annotate(f"截距 {min(lo):.2f}–{max(hi):.2f} 像素²\n开方 {np.sqrt(min(lo)):.2f}–{np.sqrt(max(hi)):.2f} 像素",
               (0, 0.95), (35, 0.45), color=BLUE, fontsize=9, arrowprops={"arrowstyle": "->", "color": BLUE, "lw": 0.8})
    a.set_xlim(-8, 330)
    a.set_ylim(0, 2.2)
    a.set_xlabel("点间距 h（像素）")
    a.set_ylabel("γ（像素²）")
    a.legend(frameon=False, fontsize=8.5, loc="upper left")
    a.set_title("y：短距离外推（虚线线性、点线二次，h ≤ 60 / 100 / 150）", fontsize=9.5, color=INK)

    b.plot(h[m], gx[m], "o", ms=4, color=ORANGE, label="x 分量")
    b.plot(h[m], gy[m], "o", ms=4, color=INK, label="y 分量")
    b.set_xlim(-8, 330)
    b.set_ylim(0, None)
    b.set_xlabel("点间距 h（像素）")
    b.set_ylabel("γ（像素²）")
    b.legend(frameon=False, fontsize=8.5, loc="upper left")
    b.set_title("x：从最短距离起就陡升，截距定不下来", fontsize=9.5, color=INK)
    fig.tight_layout()
    save(fig, "moon-variogram")
    plt.close(fig)


def compare():
    """三种方法的数放在一根轴上：两个上界、一个直接测量。"""
    fig, ax = plt.subplots(figsize=(7.6, 2.1))
    rows = [("① 仿射拟合残差", 1.21, None, "上界"), ("② 变异函数", 0.95, (0.83, 1.10), "上界"),
            ("③ 无意重标", 1.04, (0.94, 1.14), "直接测量")]
    for k, (name, value, span, kind) in enumerate(rows):
        y = len(rows) - 1 - k
        if kind == "上界":
            ax.plot([0, value], [y, y], color=RULE, lw=7, solid_capstyle="butt")
            ax.plot([value], [y], marker="|", ms=16, mew=2.2, color=INK)
        else:
            ax.plot([value], [y], "o", ms=7, color=BLUE)
        if span:
            ax.plot(span, [y, y], color=BLUE if kind != "上界" else INK2, lw=1.4)
            ax.plot(span, [y, y], "|", ms=8, color=BLUE if kind != "上界" else INK2)
        ax.text(1.62, y, f"{value:.2f} 像素，{kind}", va="center", fontsize=9.5, color=INK)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows][::-1])
    ax.set_xlim(0, 1.6)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xlabel("一对点的标注误差 σ（像素，1 像素 = 7.5 m）")
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    fig.tight_layout()
    save(fig, "compare")
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    toy()
    moon(json.loads(SUMMARY.read_text(encoding="utf-8")))
    compare()
    print("已写出", sorted(q.name for q in OUT.iterdir()))
