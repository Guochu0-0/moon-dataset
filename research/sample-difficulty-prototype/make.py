"""PROTOTYPE（一次性，issue #47）：「样本难度」一节的粗稿，挂在真实文档站里看。

    PYTHONPATH=src conda run -n moon-dataset python research/sample-difficulty-prototype/make.py
    PYTHONPATH=src conda run -n moon-dataset python scripts/build_site.py

然后打开 `_site/data/difficulty.html`。第一轮的 A/B/C 三变体见提交 f85013d；作者认为三者
本质相同，第二轮合成一版：先讲度量（为什么、定义、怎么算 + 图示），再放全部图表。
只读仓库：`data/ground-truth/`、`data/metadata/minirf_metadata.csv`、`docs/assets/samples/`、
`patches_from_40.csv`（#40 研究分支上的逐 patch 表，只取 patch 在重叠区里的位置）。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).parent
REPO = HERE.parents[1]
OUT_ASSETS = REPO / "docs" / "assets" / "prototype-difficulty"
OUT_PAGE = REPO / "docs" / "pages" / "data" / "difficulty.md"
PIXEL_M = 7.5
C = {"Val": "#2E7BD6", "Test": "#E39B1B", "ink": "#1B2733", "ink2": "#55616D", "rule": "#C9CFD4"}
SPLIT_CN = {"Val": "验证集", "Test": "测试集"}

plt.rcParams.update({
    "font.family": ["Microsoft YaHei", "sans-serif"], "font.size": 9, "axes.edgecolor": C["ink2"],
    "axes.labelcolor": C["ink"], "xtick.color": C["ink2"], "ytick.color": C["ink2"],
    "axes.spines.top": False, "axes.spines.right": False, "savefig.dpi": 160, "savefig.transparent": True,
})


def load():
    rows = []
    for split in ("Val", "Test"):
        for roi_dir in sorted((REPO / "data" / "ground-truth" / split).iterdir()):
            for f in roi_dir.glob("patch_*.txt"):
                a = np.loadtxt(f, ndmin=2)
                # 每行：光学 x、光学 y、SAR x、SAR y；y 取负后是行号。d = SAR − 光学
                dx = a[:, 2] - a[:, 0]
                dy = -(a[:, 3] - a[:, 1])
                rows.append({
                    "split": split, "roi": roi_dir.name, "patch": int(f.stem.split("_")[1]), "n": len(a),
                    "rmse": float(np.sqrt(np.mean(dx**2 + dy**2))),
                    "rmse_x": float(np.sqrt(np.mean(dx**2))), "rmse_y": float(np.sqrt(np.mean(dy**2))),
                    "dx": float(dx.mean()), "dy": float(dy.mean()),
                })
    pos = {}
    with open(HERE / "patches_from_40.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            pos[(r["roi"], int(r["patch"]))] = (int(r["opt_col"]), int(r["opt_row"]))
    for r in rows:
        r["col"], r["row"] = pos[(r["roi"], r["patch"])]
    inc = {}
    with open(REPO / "data" / "metadata" / "minirf_metadata.csv", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            inc[f"ROI_{int(r['ROI'].split('_')[1]):03d}"] = float(r["入射角_deg"])
    return rows, inc


def q(values, p):
    return float(np.percentile(values, p))


def fig_cdf(rows):
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    for split in ("Val", "Test"):
        v = np.sort([r["rmse"] for r in rows if r["split"] == split])
        ax.step(v, np.arange(1, len(v) + 1) / len(v), where="post", color=C[split], lw=1.6,
                label=f"{SPLIT_CN[split]}（{len(v)} 个 patch）")
    ax.set_xscale("log")
    ax.set_xlabel("点上 RMSE（像素，对数轴；1 像素 = 7.5 m）")
    ax.set_ylabel("累计比例")
    ax.set_xticks([2, 5, 10, 20, 50, 100, 200, 500])
    ax.set_xticklabels(["2", "5", "10", "20", "50", "100", "200", "500"])
    ax.grid(axis="both", color=C["rule"], lw=.5)
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(OUT_ASSETS / "cdf.png")
    plt.close(fig)


def fig_box(rows, rois):
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    data = [[r["rmse"] for r in rows if r["roi"] == roi["roi"]] for roi in rois]
    b = ax.boxplot(data, orientation="vertical", widths=.6, whis=(5, 95), showfliers=False, patch_artist=True,
                   medianprops={"color": C["ink"], "lw": 1.4})
    for patch, roi in zip(b["boxes"], rois):
        patch.set_facecolor(C[roi["split"]])
        patch.set_alpha(.55)
        patch.set_edgecolor(C[roi["split"]])
    ax.set_yscale("log")
    ax.set_yticks([2, 5, 10, 20, 50, 100, 200, 500])
    ax.set_yticklabels(["2", "5", "10", "20", "50", "100", "200", "500"])
    ax.set_xticks(range(1, len(rois) + 1))
    ax.set_xticklabels([f"{r['roi'][4:]}\n{r['incidence']:.0f}°" for r in rois], fontsize=8)
    ax.set_xlabel("ROI 与入射角（按入射角从小到大）")
    ax.set_ylabel("点上 RMSE（像素）")
    ax.grid(axis="y", color=C["rule"], lw=.5)
    ax.text(1, 1.02, "箱：四分位；须：5–95 分位", transform=ax.transAxes, ha="right", fontsize=8, color=C["ink2"])
    fig.tight_layout()
    fig.savefig(OUT_ASSETS / "box-roi.png")
    plt.close(fig)


def fig_dxdy(rows):
    fig, ax = plt.subplots(figsize=(7.6, 1.9))
    for split in ("Val", "Test"):
        s = [r for r in rows if r["split"] == split]
        ax.scatter([r["dx"] for r in s], [r["dy"] for r in s], s=4, color=C[split], alpha=.45, lw=0,
                   label=SPLIT_CN[split])
    ax.set_xlim(-260, 280)
    ax.set_ylim(-20, 20)
    ax.set_aspect("equal")  # 等比例：y 向错位相对 x 向有多小，一眼可见
    ax.axhline(0, color=C["rule"], lw=.6)
    ax.axvline(0, color=C["rule"], lw=.6)
    ax.set_xlabel("patch 内平均错位 dx（像素，≈ 距离向）")
    ax.set_ylabel("dy（像素，≈ 方位向）")
    ax.set_ylabel("dy（像素）")
    ax.legend(frameon=False, markerscale=3, loc="lower left", bbox_to_anchor=(0, 1), ncol=2)
    fig.tight_layout()
    fig.savefig(OUT_ASSETS / "dxdy.png")
    plt.close(fig)


def fig_strip(rows, rois):
    n = len(rois)
    cols = 5
    fig, axes = plt.subplots((n + cols - 1) // cols, cols, figsize=(8.6, 5.0), sharey=True)
    for ax, roi in zip(axes.flat, rois):
        s = [r for r in rows if r["roi"] == roi["roi"]]
        ax.scatter([r["row"] / 512 for r in s], [r["rmse"] for r in s], s=4, color=C[roi["split"]], lw=0)
        ax.set_yscale("log")
        ax.set_title(f"{roi['roi']}  {roi['incidence']:.0f}°", fontsize=8, color=C["ink"])
        ax.tick_params(labelsize=7)
    for ax in list(axes.flat)[n:]:
        ax.axis("off")
    fig.supxlabel("沿条带位置（patch 行号，每格 512 像素）", fontsize=8)
    fig.supylabel("点上 RMSE（像素）", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT_ASSETS / "strip.png")
    plt.close(fig)


EXAMPLE = ("Test", "ROI_020", 39)
"""计算图示用的 patch：入库样例图里 RMSE 最接近全体中位的一个。"""


def fig_example():
    from PIL import Image

    split, roi, patch = EXAMPLE
    a = np.loadtxt(REPO / "data" / "ground-truth" / split / roi / f"patch_{patch}.txt", ndmin=2)
    p = np.c_[a[:, 0], -a[:, 1]]  # 光学点（列，行）
    qq = np.c_[a[:, 2], -a[:, 3]]  # SAR 点
    d = qq - p
    dist = np.hypot(d[:, 0], d[:, 1])
    rmse = float(np.sqrt(np.mean(dist**2)))
    opt = Image.open(REPO / "docs" / "assets" / "samples" / f"{roi}_p{patch}_opt.jpg").convert("L")
    sar = Image.open(REPO / "docs" / "assets" / "samples" / f"{roi}_p{patch}_sar.jpg").convert("L")

    fig, ax = plt.subplots(1, 4, figsize=(11.5, 3.2), gridspec_kw={"width_ratios": [1, 1, 1, 1.15]})
    red, cyan = "#E0402B", "#19B5C8"
    for k, (img, pts, col, title) in enumerate([(opt, p, red, "① 光学 patch：点 pᵢ"),
                                                (sar, qq, cyan, "② SAR patch：同名点 qᵢ")]):
        ax[k].imshow(img, cmap="gray")
        ax[k].scatter(pts[:, 0], pts[:, 1], s=46, facecolors="none", edgecolors=col, lw=1.6)
        for i, (x, y) in enumerate(pts):
            ax[k].text(x + 12, y - 10, str(i + 1), color=col, fontsize=8, weight="bold")
        ax[k].set_title(title, fontsize=9)
    ax[2].imshow(opt, cmap="gray", alpha=.35)
    ax[2].scatter(p[:, 0], p[:, 1], s=30, facecolors="none", edgecolors=red, lw=1.4)
    ax[2].scatter(qq[:, 0], qq[:, 1], s=30, facecolors="none", edgecolors=cyan, lw=1.4)
    for (x0, y0), (x1, y1) in zip(p, qq):
        ax[2].annotate("", (x1, y1), (x0, y0), arrowprops={"arrowstyle": "->", "color": C["ink"], "lw": 1.1})
    ax[2].set_title("③ 放进同一 patch 坐标：dᵢ = qᵢ − pᵢ", fontsize=9)
    for k in range(3):
        ax[k].set_xlim(0, 512)
        ax[k].set_ylim(512, 0)
        ax[k].set_xticks([])
        ax[k].set_yticks([])
    idx = np.arange(1, len(dist) + 1)
    ax[3].bar(idx, dist, color=C["ink2"], width=.6)
    ax[3].axhline(rmse, color=C["Test"], lw=1.6)
    ax[3].text(.4, rmse + 1, f"RMSE = {rmse:.1f}", color=C["Test"], ha="left", va="bottom", fontsize=9,
               bbox={"facecolor": "white", "edgecolor": "none", "pad": 1})
    ax[3].set_xlim(.4, len(dist) + .6)
    ax[3].set_xticks(idx)
    ax[3].set_xlabel("点 i")
    ax[3].set_ylabel("|dᵢ|（像素）")
    ax[3].set_title("④ 距离的均方根", fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT_ASSETS / "example.png")
    plt.close(fig)
    return {"roi": roi, "patch": patch, "split": split, "n": len(dist), "rmse": rmse,
            "dmin": float(dist.min()), "dmax": float(dist.max()), "dx": float(d[:, 0].mean()), "dy": float(d[:, 1].mean()),
            "dx_min": float(d[:, 0].min()), "dx_max": float(d[:, 0].max()), "dy_absmax": float(np.abs(d[:, 1]).max())}


def main():
    OUT_ASSETS.mkdir(parents=True, exist_ok=True)
    ex = fig_example()
    rows, inc = load()
    all_rmse = [r["rmse"] for r in rows]
    rois = []
    for roi in sorted({r["roi"] for r in rows}):
        s = [r["rmse"] for r in rows if r["roi"] == roi]
        rois.append({"roi": roi, "split": next(r["split"] for r in rows if r["roi"] == roi), "incidence": inc[roi],
                     "patches": len(s), "p10": q(s, 10), "p50": q(s, 50), "p90": q(s, 90)})
    rank = {r["roi"]: i + 1 for i, r in enumerate(sorted(rois, key=lambda r: -r["p50"]))}
    rois.sort(key=lambda r: r["incidence"])
    fig_cdf(rows)
    fig_box(rows, rois)
    fig_dxdy(rows)
    fig_strip(rows, rois)

    stats = {"n": len(rows), **{f"p{p}": q(all_rmse, p) for p in (10, 25, 50, 75, 90, 99)},
             "max": max(all_rmse), "min_n": min(r["n"] for r in rows), "med_n": float(np.median([r["n"] for r in rows]))}
    for split in ("Val", "Test"):
        s = [r["rmse"] for r in rows if r["split"] == split]
        stats[split] = {"n": len(s), "p50": q(s, 50), "p90": q(s, 90)}
    rx = np.array([r["rmse_x"] for r in rows])
    ry = np.array([r["rmse_y"] for r in rows])
    stats["x_share"] = float(np.median(rx**2 / (rx**2 + ry**2)))
    stats["ry50"], stats["ry90"] = q(ry, 50), q(ry, 90)
    stats["rho_inc"] = float(np.corrcoef(np.argsort(np.argsort([r["incidence"] for r in rois])),
                                         np.argsort(np.argsort([r["p50"] for r in rois])))[0, 1])

    roi_lines = {r["roi"]: {"patches": r["patches"], "p50": r["p50"], "p10": r["p10"], "p90": r["p90"],
                            "rank": rank[r["roi"]], "of": len(rois)} for r in rois}
    (OUT_ASSETS / "roi.json").write_text(json.dumps(roi_lines, ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "summary.json").write_text(json.dumps({"stats": stats, "rois": rois}, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    OUT_PAGE.write_text(page(stats, rois, ex), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))


def f(v):
    return f"{v:.1f}" if v < 100 else f"{v:.0f}"


def roi_table(rois):
    body = "".join(
        f"<tr><td><a href=\"../rois/{r['roi']}.html\">{r['roi']}</a></td><td>{SPLIT_CN[r['split']]}</td>"
        f"<td>{r['incidence']:.1f}°</td><td>{r['patches']}</td><td>{f(r['p10'])}</td><td>{f(r['p50'])}</td>"
        f"<td>{f(r['p90'])}</td></tr>" for r in rois)
    return ("<table><thead><tr><th>ROI</th><th>划分</th><th>入射角</th><th>patch</th><th>10 分位</th>"
            f"<th>中位</th><th>90 分位</th></tr></thead><tbody>{body}</tbody></table>")


def page(s, rois, ex):
    img = lambda name, alt: f'<figure><img src="../assets/prototype-difficulty/{name}" alt="{alt}" style="max-width:100%"></figure>'
    quant = ("<table><thead><tr><th></th><th>10 分位</th><th>25</th><th>中位</th><th>75</th><th>90</th><th>99</th>"
             f"<th>最大</th></tr></thead><tbody><tr><td>点上 RMSE（像素）</td><td>{f(s['p10'])}</td><td>{f(s['p25'])}</td>"
             f"<td>{f(s['p50'])}</td><td>{f(s['p75'])}</td><td>{f(s['p90'])}</td><td>{f(s['p99'])}</td><td>{f(s['max'])}</td>"
             f"</tr><tr><td>约合米</td><td>{s['p10']*PIXEL_M:.0f}</td><td>{s['p25']*PIXEL_M:.0f}</td><td>{s['p50']*PIXEL_M:.0f}</td>"
             f"<td>{s['p75']*PIXEL_M:.0f}</td><td>{s['p90']*PIXEL_M:.0f}</td><td>{s['p99']*PIXEL_M:.0f}</td>"
             f"<td>{s['max']*PIXEL_M:.0f}</td></tr></tbody></table>")
    return f"""# 样本难度

<p style="background:#FFF4D6;border:1px solid #E39B1B;padding:8px 12px;border-radius:4px;font-size:14px">
PROTOTYPE（issue #47，第二轮）：数字是真的，图是粗稿。</p>

一对 patch 有多难配准，这里只看几何：数据集交付时，光学与 SAR patch 之间还差多少。
验证集、测试集里有评测真值点的 {s['n']} 个 patch 对都给出一个值；训练集没有评测真值点，暂不给。

## 度量：点上 RMSE

### 为什么选它

- **只用真值点，不拟合，不外推。** 光学与 SAR patch 之间真实的坐标对应（真值变换）只在真值点上被观测到。
  在 patch 内，x 向（≈ 距离向）的错位随地形变化几十像素，用一个平移、仿射或单应去概括，都会与真值点自相矛盾；
  直接在点上量，就绕开了这个问题。
- **与评测一致。** 它就是「不做任何配准时的评测误差」：配准方法交出结果后，同样在这些点上算误差，两者可以直接比。
  医学影像配准的基准（ANHIR、DIR-Lab）用同样的办法报告配准前的难度。
- **换别的量，难易排序几乎不变。** 讨论过的六个位移类度量（包括 patch 中心的错位、四角的最大错位）
  给 patch 排序的秩相关都在 0.93 以上。选 RMSE 是因为它最好解释。

放弃的候选：

| 候选 | 放弃的原因 |
|---|---|
| 光学与 SAR 窗口的面积重合度 | 每个 patch 都在约 0.73 以上，基本只由平移决定，分不出难易 |
| 拟合仿射后分解成平移、旋转、缩放、剪切 | 会把 x 向的剪切误读成旋转；而且要拟合 |
| patch 中心或四角的错位 | 要先拟合一个变换，四角还要外推到没有点的地方 |

### 定义

一个 patch 有 N 个评测真值点。第 i 个点在光学 patch 里的位置是 pᵢ，在 SAR patch 里的位置是 qᵢ，
都用各自 patch 的像素坐标（原点在左上角，1 像素 = 7.5 m）。

<p style="text-align:center;font-size:18px">点上 RMSE = √( (1/N) · Σᵢ |qᵢ − pᵢ|² )</p>

数据集交付时两个 patch 已经按控制点的全局仿射对齐，完全对齐时每个 qᵢ = pᵢ，值为 0。值越大，
配准方法要纠正的错位越大。

### 怎么算

以 {ex['roi']} 的 patch {ex['patch']}（{SPLIT_CN[ex['split']]}，{ex['n']} 个点）为例，它的值 {ex['rmse']:.1f} 像素，接近全体中位。

{img("example.png", "点上 RMSE 的计算示例")}

1. 读 `data/ground-truth/<划分>/<ROI>/patch_<n>.txt`，每行一对点：光学 x、y，SAR x、y。y 存的是负的行号，取负。
2. 每对点求错位 dᵢ = qᵢ − pᵢ（图 ③ 里的箭头）。这个 patch 里的箭头都几乎是水平的
   （|dy| 不超过 {ex['dy_absmax']:.1f} 像素），但 dx 从 {ex['dx_min']:.1f} 到 {ex['dx_max']:.1f} 像素，有的朝左、有的朝右：
   x 向错位在一个 patch 内随位置变化，这正是不用一个平移去概括 patch 的原因。
3. 求每个箭头的长度 |dᵢ|（{ex['dmin']:.1f}–{ex['dmax']:.1f} 像素），平方后取平均，再开方（图 ④）。

每个 patch 至少 {s['min_n']} 个点、中位 {s['med_n']:.0f} 个；不剔除任何点。

### 测量误差

每个真值点带约 1 像素的标注抖动（见「标注质量」）。相对中位 {f(s['p50'])} 像素可以忽略，
只会把最小的一批值（10 分位 {f(s['p10'])} 像素）略微抬高。

## 分布

{img("cdf.png", "点上 RMSE 的累计分布")}

{quant}

测试集比验证集难：中位 {f(s['Test']['p50'])} 对 {f(s['Val']['p50'])} 像素，90 分位 {f(s['Test']['p90'])} 对 {f(s['Val']['p90'])} 像素。

## 各 ROI 与入射角

{img("box-roi.png", "各 ROI 的点上 RMSE 箱线图")}

难度主要由 ROI 决定：同一 ROI 内的 patch 相差几倍，ROI 之间的中位相差一个数量级。ROI 按入射角从小到大排。
入射角越小，地形引起的距离向位移越大（与 cot θ 成正比）；13 个 ROI 的中位 RMSE 与入射角的秩相关为 {s['rho_inc']:.2f}。
数据集的 SAR 窗口只按每个 ROI 的全局仿射放置，地形带来的这部分错位留在了 patch 对里。

{roi_table(rois)}

## 错位的方向

{img("dxdy.png", "patch 内平均错位 dx–dy 散点")}

每个点是一个 patch 的平均错位，两轴等比例。x（≈ 距离向）从 −250 到 +270 像素铺开，y（≈ 方位向）贴着 0：
RMSE² 里 x 分量的占比中位为 {s['x_share']*100:.1f}%，y 分量的 RMSE 中位只有 {s['ry50']:.1f} 像素。
y 向在 patch 内几乎是纯平移；x 向在一个 patch 内还会随地形变化几十像素。

## 沿条带的变化

{img("strip.png", "各 ROI 沿条带的点上 RMSE")}

每个小图是一条 ROI，横轴是 patch 在条带上的位置。难度成片连续变化，易段与难段交替，与地形起伏一致；
入射角小的条带整体更难。
"""


if __name__ == "__main__":
    main()
