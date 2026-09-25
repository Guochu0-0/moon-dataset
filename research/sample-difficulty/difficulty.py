"""「样本难度」一节的数字与图：逐 patch 对的点上 RMSE 及其分布、各 ROI、方向、沿条带。

    PYTHONPATH=src conda run -n moon-dataset python research/sample-difficulty/difficulty.py

只读仓库：`data/ground-truth/` 的评测真值点、`data/metadata/minirf_metadata.csv` 的入射角、
`docs/assets/samples/` 的示例 patch 对，以及同目录的 `patch-positions.csv`。输出：

- `tables.md`：页面上每个数的出处；
- `docs/assets/difficulty/`：页面用的图与公式（公式预渲染成 SVG，因为站点没有公式引擎，
  而根号要盖住整个式子）。

`patch-positions.csv` 是各 patch 对光学窗口左上角在重叠区影像上的位置，取自研究分支
`research/ground-truth-residuals` 的 `patches.csv`（那里由输出根的 `windows.json` 收集）。
只有「沿条带」一节要用它：相邻 patch 对按位置判定，图的横轴是行号。

随机量（标注误差的模拟、置换检验）用固定种子，重跑结果不变。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).parent
REPO = HERE.parents[1]
OUT = REPO / "docs" / "assets" / "difficulty"
PATCH = 512
PIXEL_M = 7.5
SIGMA = 1.0
"""标注误差，每个坐标轴，像素。取「标注质量」的结论：三种估计都在 0.9–1.2 之间。"""
SIMULATIONS = 200
PERMUTATIONS = 100_000
EXAMPLE = ("Test", "ROI_020", 39)
"""计算示例：入库样例里点上 RMSE 最接近全体中位数的 patch 对。"""

SPLIT_CN = {"Val": "验证集", "Test": "测试集"}
COLOR = {"Val": "#2E7BD6", "Test": "#E39B1B", "ink": "#1B2733", "ink2": "#55616D", "rule": "#C9CFD4"}
LOG_TICKS = [2, 5, 10, 20, 50, 100, 200, 500]

plt.rcParams.update({
    "font.family": ["Microsoft YaHei", "sans-serif"], "font.size": 9, "axes.edgecolor": COLOR["ink2"],
    "axes.labelcolor": COLOR["ink"], "xtick.color": COLOR["ink2"], "ytick.color": COLOR["ink2"],
    "axes.spines.top": False, "axes.spines.right": False, "savefig.dpi": 160, "savefig.transparent": True,
    "mathtext.fontset": "cm", "svg.hashsalt": "moon-dataset", "axes.unicode_minus": False,
})


@dataclass
class PatchPair:
    split: str
    roi: str
    patch: int
    d: np.ndarray
    """(N, 2)：逐点 q − p，patch 像素坐标，x 向右、y 向下。"""
    col: int
    row: int

    @property
    def rmse(self) -> float:
        return float(np.sqrt((self.d**2).sum(axis=1).mean()))

    @property
    def rmse_xy(self) -> np.ndarray:
        return np.sqrt((self.d**2).mean(axis=0))


def load() -> tuple[list[PatchPair], dict[str, float]]:
    positions = {}
    with open(HERE / "patch-positions.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            positions[(r["roi"], int(r["patch"]))] = (int(r["opt_col"]), int(r["opt_row"]))
    pairs = []
    for split in SPLIT_CN:
        for roi_dir in sorted((REPO / "data" / "ground-truth" / split).iterdir()):
            for path in sorted(roi_dir.glob("patch_*.txt"), key=lambda p: int(p.stem[6:])):
                a = np.loadtxt(path, ndmin=2)
                # 每行：光学 x、光学 y、SAR x、SAR y；文件里 y 取负存储
                d = np.column_stack([a[:, 2] - a[:, 0], -(a[:, 3] - a[:, 1])])
                patch = int(path.stem[6:])
                pairs.append(PatchPair(split, roi_dir.name, patch, d, *positions[(roi_dir.name, patch)]))
    incidence = {}
    with open(REPO / "data" / "metadata" / "minirf_metadata.csv", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            incidence[f"ROI_{int(r['ROI'].split('_')[1]):03d}"] = float(r["入射角_deg"])
    return pairs, incidence


def ranks(values) -> np.ndarray:
    return np.argsort(np.argsort(values)).astype(float)


def pct(values, ps) -> list[float]:
    return [float(np.percentile(values, p)) for p in ps]


# ---------------------------------------------------------------------------
# 数字


def tables(pairs: list[PatchPair], incidence: dict[str, float]) -> str:
    rng = np.random.default_rng(0)
    rmse = np.array([p.rmse for p in pairs])
    split = np.array([p.split for p in pairs])
    roi = np.array([p.roi for p in pairs])
    rois = sorted(set(roi), key=lambda k: incidence[k])
    out = ["# 样本难度：数字", "", "由 `difficulty.py` 生成，页面上的数都出自这里。单位为像素。", ""]

    def table(head: list[str], rows: list[list[str]]) -> None:
        out.extend(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)])
        out.extend("| " + " | ".join(r) + " |" for r in rows)
        out.append("")

    ps = [10, 25, 50, 75, 90, 99]
    out += ["## 数据", ""]
    npts = np.array([len(p.d) for p in pairs])
    table(["", "patch 对", "ROI", "点对", "每对点数"], [
        [SPLIT_CN.get(s, s), str((split == s).sum() if s != "全部" else len(pairs)),
         str(len(set(roi[split == s])) if s != "全部" else len(rois)),
         str(npts[split == s].sum() if s != "全部" else npts.sum()),
         f"{npts.min()}–{npts.max()}"]
        for s in ("Val", "Test", "全部")])

    out += ["## 分位数", ""]
    rows = [["全部（像素）", *[f"{v:.1f}" for v in pct(rmse, ps)], f"{rmse.max():.1f}"],
            ["全部（米）", *[f"{v * PIXEL_M:.0f}" for v in pct(rmse, ps)], f"{rmse.max() * PIXEL_M:.0f}"]]
    for s in SPLIT_CN:
        v = rmse[split == s]
        rows.append([f"{SPLIT_CN[s]}（像素）", *[f"{x:.1f}" for x in pct(v, ps)], f"{v.max():.1f}"])
    table(["", *map(str, ps), "最大"], rows)
    out += [f"最小值 {rmse.min():.1f}。低于 10：{(rmse < 10).mean():.1%}；低于 50：{(rmse < 50).mean():.1%}；"
            f"高于 100：{(rmse > 100).mean():.1%}。低于 5 的 patch 对：{(rmse < 5).sum()} 个。", ""]
    v90 = {s: pct(rmse[split == s], [90])[0] for s in SPLIT_CN}
    out += [f"90 分位 测试集 / 验证集 = {v90['Test'] / v90['Val']:.2f}。", ""]

    out += ["## 各 ROI（按入射角）", ""]
    med = {}
    rows = []
    for k in rois:
        v = rmse[roi == k]
        med[k] = float(np.median(v))
        p10, p50, p90 = pct(v, [10, 50, 90])
        rows.append([k, SPLIT_CN[split[roi == k][0]], f"{incidence[k]:.2f}", str(len(v)), f"{p10:.1f}", f"{p50:.1f}", f"{p90:.1f}"])
    table(["ROI", "划分", "入射角", "patch 对", "10", "50", "90"], rows)
    inc = np.array([incidence[k] for k in rois])
    m = np.array([med[k] for k in rois])
    rho = np.corrcoef(ranks(inc), ranks(m))[0, 1]
    perm = np.array([np.corrcoef(ranks(inc), rng.permutation(ranks(m)))[0, 1] for _ in range(PERMUTATIONS)])
    p = float((np.abs(perm) >= abs(rho) - 1e-12).mean())
    out += [f"ROI 中位数与入射角的 Spearman 秩相关 {rho:.2f}（n = {len(rois)}，双侧置换检验 {PERMUTATIONS} 次，p = {p:.3f}）。", ""]

    out += ["## 方向", ""]
    rxy = np.array([p.rmse_xy for p in pairs])
    table(["", *map(str, ps)], [["RMSE_x", *[f"{v:.1f}" for v in pct(rxy[:, 0], ps)]],
                                ["RMSE_y", *[f"{v:.1f}" for v in pct(rxy[:, 1], ps)]]])
    mean_dx = np.array([p.d[:, 0].mean() for p in pairs])
    out += [f"RMSE_x > RMSE_y 的 patch 对：{(rxy[:, 0] > rxy[:, 1]).sum()} / {len(pairs)}。"
            f"RMSE_y < 3：{(rxy[:, 1] < 3).mean():.1%}。",
            f"patch 对内平均 dx > 0（SAR 点在光学点右侧）：{(mean_dx > 0).mean():.1%}；< 0：{(mean_dx < 0).mean():.1%}。", ""]
    ex = next(p for p in pairs if (p.split, p.roi, p.patch) == EXAMPLE)
    out += [f"示例 {EXAMPLE[1]} patch {EXAMPLE[2]}：{len(ex.d)} 对点，点上 RMSE {ex.rmse:.1f}，"
            f"最长 {np.hypot(*ex.d.T).max():.1f}；x 分量 {ex.d[:, 0].min():.1f} 到 {ex.d[:, 0].max():.1f}，"
            f"|y 分量| 最大 {np.abs(ex.d[:, 1]).max():.1f}。", ""]

    out += ["## 沿条带", ""]
    at = {(p.roi, p.col, p.row): p.rmse for p in pairs}
    adjacent = np.array([(v, at[(k, c + dc, r + dr)]) for (k, c, r), v in at.items()
                         for dc, dr in ((PATCH, 0), (0, PATCH)) if (k, c + dc, r + dr) in at])
    ratio = np.exp(np.abs(np.log(adjacent[:, 1] / adjacent[:, 0])))
    r_log = np.corrcoef(np.log(adjacent[:, 0]), np.log(adjacent[:, 1]))[0, 1]
    out += [f"上下或左右相邻的 patch 对：{len(adjacent)} 组。两者之比（大比小）中位数 {np.median(ratio):.2f}，"
            f"90 分位 {np.percentile(ratio, 90):.2f}。取对数后的相关系数 {r_log:.2f}。", ""]
    rows = []
    for k in rois:
        members = sorted((p for p in pairs if p.roi == k), key=lambda p: p.row)
        rs = sorted({p.row for p in members})
        thirds = np.array_split(np.array(rs), 3)
        rows.append([k, *[f"{np.median([p.rmse for p in members if p.row in set(t)]):.1f}" for t in thirds],
                     f"{min(p.rmse for p in members):.1f}", f"{max(p.rmse for p in members):.1f}"])
    table(["ROI", "前三分之一中位", "中三分之一中位", "后三分之一中位", "最小", "最大"], rows)

    out += ["## 测量误差", ""]
    sims = np.array([[np.sqrt(((p.d + rng.normal(0, SIGMA, p.d.shape))**2).sum(axis=1).mean()) for p in pairs]
                     for _ in range(SIMULATIONS)])
    sd = sims.std(axis=0)
    bias = sims.mean(axis=0) - rmse
    rel = sd / rmse
    medians = np.median(sims, axis=1)
    out += [f"每对点每轴加 N(0, {SIGMA:g}²) 的误差，重算点上 RMSE，重复 {SIMULATIONS} 次。", ""]
    table(["量", "结果"], [
        ["单个 patch 对的标准差（10–90 分位 / 最大）", f"{np.percentile(sd, 10):.2f}–{np.percentile(sd, 90):.2f} / {sd.max():.2f}"],
        ["单个 patch 对的偏高（90 分位）", f"{np.percentile(bias, 90):.2f}"],
        ["点上 RMSE ≥ 10 时标准差与值之比的最大", f"{rel[rmse >= 10].max():.3f}"],
        ["全体中位数（2.5–97.5 分位）", f"{np.percentile(medians, 2.5):.1f}–{np.percentile(medians, 97.5):.1f}"],
    ])
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 图


def _log_axis(axis) -> None:
    axis.set_ticks(LOG_TICKS)
    axis.set_ticklabels([str(t) for t in LOG_TICKS])
    axis.set_minor_formatter(matplotlib.ticker.NullFormatter())


def _save(fig, name: str) -> None:
    fig.savefig(OUT / name, metadata={"Software": None})
    plt.close(fig)


def fig_cdf(pairs: list[PatchPair]) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    for s in SPLIT_CN:
        v = np.sort([p.rmse for p in pairs if p.split == s])
        ax.step(v, np.arange(1, len(v) + 1) / len(v), where="post", color=COLOR[s], lw=1.6,
                label=f"{SPLIT_CN[s]}（{len(v)} 个 patch 对）")
    ax.set_xscale("log")
    _log_axis(ax.xaxis)
    ax.set_xlim(2, 300)
    ax.set_xlabel("点上 RMSE（像素，对数刻度）")
    ax.set_ylabel("累计比例")
    ax.grid(color=COLOR["rule"], lw=.5)
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    _save(fig, "cdf.png")


def fig_box(pairs: list[PatchPair], rois: list[str], incidence: dict[str, float]) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    data = [[p.rmse for p in pairs if p.roi == k] for k in rois]
    split = {p.roi: p.split for p in pairs}
    b = ax.boxplot(data, widths=.6, whis=(5, 95), showfliers=False, patch_artist=True,
                   medianprops={"color": COLOR["ink"], "lw": 1.4})
    for box, k in zip(b["boxes"], rois):
        box.set_facecolor(COLOR[split[k]])
        box.set_alpha(.55)
        box.set_edgecolor(COLOR[split[k]])
    ax.set_yscale("log")
    _log_axis(ax.yaxis)
    ax.set_xticks(range(1, len(rois) + 1))
    ax.set_xticklabels([f"{k[4:]}\n{incidence[k]:.1f}°" for k in rois], fontsize=8)
    ax.set_xlabel("ROI 与入射角")
    ax.set_ylabel("点上 RMSE（像素）")
    ax.grid(axis="y", color=COLOR["rule"], lw=.5)
    fig.tight_layout()
    _save(fig, "box-roi.png")


def fig_dxdy(pairs: list[PatchPair]) -> None:
    fig, ax = plt.subplots(figsize=(7.6, 2.0))
    for s in SPLIT_CN:
        d = np.array([p.d.mean(axis=0) for p in pairs if p.split == s])
        ax.scatter(d[:, 0], d[:, 1], s=4, color=COLOR[s], alpha=.45, lw=0, label=SPLIT_CN[s])
    ax.set_xlim(-260, 280)
    ax.set_ylim(-20, 20)
    ax.set_aspect("equal")  # 两轴同比例，y 分量相对 x 有多小才看得出来
    ax.axhline(0, color=COLOR["rule"], lw=.6)
    ax.axvline(0, color=COLOR["rule"], lw=.6)
    ax.set_xlabel("x（像素）")
    ax.set_ylabel("y（像素）")
    ax.legend(frameon=False, markerscale=3, loc="lower left", bbox_to_anchor=(0, 1), ncol=2)
    fig.tight_layout()
    _save(fig, "dxdy.png")


def fig_strip(pairs: list[PatchPair], rois: list[str], incidence: dict[str, float]) -> None:
    cols = 5
    fig, axes = plt.subplots((len(rois) + cols - 1) // cols, cols, figsize=(8.6, 5.0), sharey=True)
    for ax, k in zip(axes.flat, rois):
        members = [p for p in pairs if p.roi == k]
        ax.scatter([p.row / PATCH for p in members], [p.rmse for p in members], s=4, color=COLOR[members[0].split], lw=0)
        ax.set_yscale("log")
        _log_axis(ax.yaxis)
        ax.set_title(f"{k}  {incidence[k]:.1f}°", fontsize=8, color=COLOR["ink"])
        ax.tick_params(labelsize=7)
    for ax in list(axes.flat)[len(rois):]:
        ax.axis("off")
    fig.supxlabel("patch 行号", fontsize=8)
    fig.supylabel("点上 RMSE（像素）", fontsize=8)
    fig.tight_layout()
    _save(fig, "strip.png")


def fig_example(pairs: list[PatchPair]) -> None:
    from PIL import Image

    split, roi, patch = EXAMPLE
    a = np.loadtxt(REPO / "data" / "ground-truth" / split / roi / f"patch_{patch}.txt", ndmin=2)
    p = np.column_stack([a[:, 0], -a[:, 1]])
    q = np.column_stack([a[:, 2], -a[:, 3]])
    dist = np.hypot(*(q - p).T)
    rmse = float(np.sqrt(np.mean(dist**2)))
    images = [Image.open(REPO / "docs" / "assets" / "samples" / f"{roi}_p{patch}_{side}.jpg").convert("L")
              for side in ("opt", "sar")]
    red, cyan = "#E0402B", "#19B5C8"
    fig, ax = plt.subplots(1, 4, figsize=(11.5, 3.2))
    for k, (img, pts, color, title) in enumerate([(images[0], p, red, "① 光学 patch 上的点 $p_i$"),
                                                  (images[1], q, cyan, "② SAR patch 上的同名点 $q_i$")]):
        ax[k].imshow(img, cmap="gray")
        ax[k].scatter(pts[:, 0], pts[:, 1], s=46, facecolors="none", edgecolors=color, lw=1.6)
        for i, (x, y) in enumerate(pts):
            ax[k].text(x + 12, y - 10, str(i + 1), color=color, fontsize=8, weight="bold")
        ax[k].set_title(title, fontsize=9)
    ax[2].imshow(images[0], cmap="gray", alpha=.35)
    ax[2].scatter(p[:, 0], p[:, 1], s=30, facecolors="none", edgecolors=red, lw=1.4)
    ax[2].scatter(q[:, 0], q[:, 1], s=30, facecolors="none", edgecolors=cyan, lw=1.4)
    for (x0, y0), (x1, y1) in zip(p, q):
        ax[2].annotate("", (x1, y1), (x0, y0), arrowprops={"arrowstyle": "->", "color": COLOR["ink"], "lw": 1.1})
    ax[2].set_title("③ 同一坐标里的 $d_i = q_i - p_i$", fontsize=9)
    for k in range(3):
        ax[k].set_xlim(0, PATCH)
        ax[k].set_ylim(PATCH, 0)
        ax[k].set_xticks([])
        ax[k].set_yticks([])
    idx = np.arange(1, len(dist) + 1)
    ax[3].bar(idx, dist, color=COLOR["ink2"], width=.6)
    ax[3].axhline(rmse, color=COLOR["Test"], lw=1.6)
    ax[3].text(.5, rmse + 1, f"RMSE = {rmse:.1f}", color=COLOR["Test"], va="bottom", fontsize=9,
               bbox={"facecolor": "white", "edgecolor": "none", "pad": 1})
    ax[3].set_xlim(.4, len(dist) + .6)
    ax[3].set_xticks(idx)
    ax[3].set_xlabel("点对 $i$")
    ax[3].set_ylabel(r"$\Vert d_i \Vert$（像素）")
    ax[3].set_title("④ 各对点的距离与均方根", fontsize=9)
    fig.tight_layout()
    _save(fig, "example.png")


def formula(tex: str, name: str, width: float) -> None:
    fig = plt.figure(figsize=(width, .72))
    fig.text(.5, .5, tex, ha="center", va="center", fontsize=15, color=COLOR["ink"])
    fig.savefig(OUT / name, metadata={"Date": None, "Creator": None}, transparent=True)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pairs, incidence = load()
    rois = sorted({p.roi for p in pairs}, key=lambda k: incidence[k])
    (HERE / "tables.md").write_text(tables(pairs, incidence) + "\n", encoding="utf-8")
    fig_cdf(pairs)
    fig_box(pairs, rois, incidence)
    fig_dxdy(pairs)
    fig_strip(pairs, rois, incidence)
    fig_example(pairs)
    formula(r"$\mathrm{RMSE} = \sqrt{\dfrac{1}{N}\sum_{i=1}^{N} \Vert d_i \Vert^{2}}$", "formula-rmse.svg", 3.6)
    formula(r"$\mathrm{RMSE}_x = \sqrt{\dfrac{1}{N}\sum_{i=1}^{N} d_{i,x}^{2}}, \qquad"
            r"\mathrm{RMSE}_y = \sqrt{\dfrac{1}{N}\sum_{i=1}^{N} d_{i,y}^{2}}$", "formula-xy.svg", 6.4)


if __name__ == "__main__":
    main()
