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

    for shape, size, name in (((1, 4), (11.5, 3.2), "example.png"), ((2, 2), (6.0, 6.2), "example-grid.png")):
        fig, ax = plt.subplots(*shape, figsize=size)
        draw_example(ax.ravel(), opt, sar, p, qq, dist, rmse)
        fig.tight_layout()
        fig.savefig(OUT_ASSETS / name)
        plt.close(fig)
    return {"roi": roi, "patch": patch, "split": split, "n": len(dist), "rmse": rmse,
            "dx_min": float(d[:, 0].min()), "dx_max": float(d[:, 0].max())}


def draw_example(ax, opt, sar, p, qq, dist, rmse):
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


def fig_sparklines(rows, rois):
    """每个 ROI 一条沿条带的迷你曲线，给「以 ROI 表为主轴」的变体用。"""
    for roi in rois:
        s = sorted((r for r in rows if r["roi"] == roi["roi"]), key=lambda r: r["row"])
        fig, ax = plt.subplots(figsize=(1.9, .42))
        ax.scatter([r["row"] for r in s], [r["rmse"] for r in s], s=1.5, color=C[roi["split"]], lw=0)
        ax.set_yscale("log")
        ax.set_ylim(2, 300)
        ax.axis("off")
        fig.subplots_adjust(0, 0, 1, 1)
        fig.savefig(OUT_ASSETS / f"spark-{roi['roi']}.png")
        plt.close(fig)


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
    fig_sparklines(rows, rois)

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


LOG_LO, LOG_HI = 2, 300
"""范围条的对数刻度（像素）。"""


def _x(v, width):
    return width * (np.log(v) - np.log(LOG_LO)) / (np.log(LOG_HI) - np.log(LOG_LO))


def range_bar(r, width=200):
    lo, mid, hi = _x(r["p10"], width), _x(r["p50"], width), _x(r["p90"], width)
    col = C[r["split"]]
    return (f'<svg width="{width}" height="14" class="rbar"><rect x="0" y="6" width="{width}" height="2" fill="#E3E7EA"/>'
            f'<rect x="{lo:.1f}" y="3" width="{hi - lo:.1f}" height="8" rx="2" fill="{col}" opacity=".55"/>'
            f'<rect x="{mid - 1:.1f}" y="1" width="2" height="12" fill="{C["ink"]}"/></svg>')


def range_axis(width=200):
    ticks = "".join(f'<span style="left:{_x(v, width):.0f}px">{v}</span>' for v in (2, 5, 10, 20, 50, 100, 200))
    return f'<div class="raxis" style="width:{width}px">{ticks}</div>'


def page(s, rois, ex):
    easiest = min(rois, key=lambda r: r["p50"])
    hardest = max(rois, key=lambda r: r["p50"])
    img = lambda name, alt, cls="": f'<img src="../assets/prototype-difficulty/{name}" alt="{alt}" class="{cls}">'

    # ---- 正文：四个变体共用 ----
    define = (
        "<p>样本难度用<b>点上 RMSE</b> 衡量：一个 patch 对上，每对评测真值点的光学位置 p<sub>i</sub> 与 SAR 位置 "
        "q<sub>i</sub> 之间距离的均方根。单位是像素，1 像素 = 7.5 m。</p>"
        '<p class="formula">点上 RMSE = √( (1/N) · Σ<sub>i</sub> |q<sub>i</sub> − p<sub>i</sub>|² )</p>'
        "<p>p<sub>i</sub>、q<sub>i</sub> 是各自 patch 内的像素坐标，N 是这个 patch 对上的点数。它等于不做配准时"
        "在评测真值点上的误差，两个 patch 完全对齐时为 0。真值点的文件格式见"
        '<a href="organization.html#标签文件">组织</a>。</p>')
    caption = (f"{ex['roi']} 的 patch {ex['patch']}，{ex['n']} 对点，点上 RMSE {ex['rmse']:.1f} 像素。"
               "① ② 两个 patch 上的同名点；③ 放进同一坐标，箭头从 p<sub>i</sub> 指向 q<sub>i</sub>；"
               "④ 各对点的距离，横线是它们的均方根。")
    t_dist = (f"验证集、测试集里有评测真值点的 {s['n']} 个 patch 对都有值。中位 {f(s['p50'])} 像素（约 "
              f"{s['p50'] * PIXEL_M:.0f} m），90% 在 {f(s['p90'])} 像素以内。验证集、测试集的中位分别为 "
              f"{f(s['Val']['p50'])} 与 {f(s['Test']['p50'])} 像素。")
    t_roi = (f"中位最小的是 {easiest['roi']}（{f(easiest['p50'])} 像素），最大的是 "
             f"{hardest['roi']}（{f(hardest['p50'])} 像素）。入射角越小的 ROI 越难。")
    t_dir = (f"x 方向接近 SAR 的距离向。只算 y 方向时，RMSE 的中位是 {s['ry50']:.1f} 像素。"
             f"同一个 patch 里各对点的 x 错位也不相同，示例 patch 里从 {ex['dx_min']:.1f} 到 +{ex['dx_max']:.1f} 像素。")
    t_strip = "相邻 patch 的值相近，易段与难段交替。"
    t_err = "评测真值点本身有约 1 像素的标注误差，对 10 像素以上的值影响可以忽略。"
    h = {"dist": f"中位 {s['p50']:.0f} 像素，测试集更难", "roi": "ROI 之间相差一个数量级",
         "dir": "错位几乎都在 x 方向", "strip": "沿条带成段起伏"}
    quant = ("<table><thead><tr><th>分位</th><th>10</th><th>25</th><th>50</th><th>75</th><th>90</th><th>99</th>"
             f"<th>最大</th></tr></thead><tbody><tr><td>像素</td>"
             + "".join(f"<td>{f(s[k])}</td>" for k in ("p10", "p25", "p50", "p75", "p90", "p99", "max"))
             + "</tr><tr><td>米</td>"
             + "".join(f"<td>{s[k] * PIXEL_M:.0f}</td>" for k in ("p10", "p25", "p50", "p75", "p90", "p99", "max"))
             + "</tr></tbody></table>")
    roi_rows = "".join(
        f"<tr><td><a href=\"../rois/{r['roi']}.html\">{r['roi']}</a></td><td>{SPLIT_CN[r['split']]}</td>"
        f"<td>{r['incidence']:.1f}°</td><td>{r['patches']}</td><td>{f(r['p10'])}</td><td>{f(r['p50'])}</td>"
        f"<td>{f(r['p90'])}</td></tr>" for r in rois)
    roi_table = ("<table><thead><tr><th>ROI</th><th>划分</th><th>入射角</th><th>patch 对</th><th>10 分位</th>"
                 f"<th>中位</th><th>90 分位</th></tr></thead><tbody>{roi_rows}</tbody></table>")
    fig = lambda name, alt, cap: f"<figure>{img(name, alt)}<figcaption>{cap}</figcaption></figure>"
    example = fig("example.png", "点上 RMSE 的计算示例", caption)

    # ---- A：数字卡 + 图墙 ----
    cards = "".join(f'<div class="card"><b>{v}</b><span>{k}</span></div>' for v, k in (
        (f"{s['n']}", "个 patch 对有值"), (f"{f(s['p50'])}", f"中位（像素，约 {s['p50'] * PIXEL_M:.0f} m）"),
        (f"{f(s['p90'])}", "90 分位（像素）"), (f"{f(s['Val']['p50'])} / {f(s['Test']['p50'])}", "验证集 / 测试集中位")))
    tiles = "".join(f'<figure class="tile">{img(n, a, "zoom")}<figcaption><b>{h[k]}</b>{t}</figcaption></figure>'
                    for n, a, k, t in (("cdf.png", "累计分布", "dist", t_dist), ("box-roi.png", "各 ROI", "roi", t_roi),
                                       ("dxdy.png", "错位方向", "dir", t_dir), ("strip.png", "沿条带", "strip", t_strip)))
    var_a = f"""<div data-variant="A" data-name="数字卡 + 图墙">
<div class="cards">{cards}</div>
<details class="box"><summary>点上 RMSE 是什么、怎么算</summary>{define}{example}</details>
<div class="tiles">{tiles}</div>
<details class="box"><summary>分位数与各 ROI 的数值</summary>{quant}{roi_table}</details>
<p class="note">{t_err}</p>
</div>"""

    # ---- B：以 ROI 表为主轴 ----
    b_rows = "".join(
        f'<tr data-roi="{r["roi"]}" data-inc="{r["incidence"]}" data-med="{r["p50"]}">'
        f'<td><a href="../rois/{r["roi"]}.html">{r["roi"]}</a></td><td><span class="sw {r["split"]}"></span>{SPLIT_CN[r["split"]]}</td>'
        f'<td>{r["incidence"]:.1f}°</td><td>{r["patches"]}</td><td><b>{f(r["p50"])}</b></td>'
        f'<td>{range_bar(r)}</td><td>{img("spark-" + r["roi"] + ".png", r["roi"] + " 沿条带", "spark")}</td></tr>'
        for r in rois)
    var_b = f"""<div data-variant="B" data-name="以 ROI 表为主轴">
<div class="split2">
<div>{define}<details class="box"><summary>计算示例</summary>{example}</details></div>
<figure>{img("cdf.png", "累计分布")}<figcaption>{t_dist}</figcaption></figure>
</div>
<h2>{h["roi"]}</h2>
<p>{t_roi} {t_strip}</p>
<table class="spine"><thead><tr><th data-key="roi">ROI</th><th>划分</th><th data-key="inc">入射角 ↕</th><th>patch 对</th>
<th data-key="med">中位 ↕</th><th>10–90 分位（像素，对数）{range_axis()}</th><th>沿条带</th></tr></thead><tbody>{b_rows}</tbody></table>
<h2>{h["dir"]}</h2>
<figure>{img("dxdy.png", "错位方向")}<figcaption>{t_dir}</figcaption></figure>
<details class="box"><summary>全部分位数</summary>{quant}</details>
<p class="note">{t_err}</p>
</div>"""

    # ---- C：定义在上，图区用标签切换 ----
    panels = [("dist", "分布", img("cdf.png", "累计分布"), t_dist, quant),
              ("roi", "各 ROI", img("box-roi.png", "各 ROI"), t_roi, roi_table),
              ("dir", "方向", img("dxdy.png", "错位方向"), t_dir, ""),
              ("strip", "沿条带", img("strip.png", "沿条带"), t_strip, "")]
    tabs = "".join(f'<button data-tab="{k}">{label}</button>' for k, label, *_ in panels)
    tab_panels = "".join(f'<section data-panel="{k}"><h3>{h[k]}</h3>{im}<p>{t}</p>{tb}</section>'
                         for k, _, im, t, tb in panels)
    var_c = f"""<div data-variant="C" data-name="定义在上 + 标签页">
{define}
{example}
<div class="tabs">{tabs}</div>
<div class="panels">{tab_panels}</div>
<p class="note">{t_err}</p>
</div>"""

    # ---- D：左侧定义固定，右侧滚动 ----
    var_d = f"""<div data-variant="D" data-name="固定侧栏 + 滚动">
<div class="sticky2">
<aside>{define}<figure>{img("example-grid.png", "点上 RMSE 的计算示例")}<figcaption>{caption}</figcaption></figure>
<p class="note">{t_err}</p></aside>
<div>
<h2>{h["dist"]}</h2><figure>{img("cdf.png", "累计分布")}</figure><p>{t_dist}</p>{quant}
<h2>{h["roi"]}</h2><figure>{img("box-roi.png", "各 ROI")}</figure><p>{t_roi}</p>{roi_table}
<h2>{h["dir"]}</h2><figure>{img("dxdy.png", "错位方向")}</figure><p>{t_dir}</p>
<h2>{h["strip"]}</h2><figure>{img("strip.png", "沿条带")}</figure><p>{t_strip}</p>
</div>
</div>
</div>"""

    return f"""# 样本难度

<style>
[data-variant] img {{ max-width: 100%; }}
[data-variant] figure {{ margin: 12px 0 20px; }}
[data-variant] figcaption {{ font-size: 13px; color: var(--ink2); }}
.formula {{ font-size: 18px; text-align: center; margin: 14px 0; }}
.box {{ border: 1px solid var(--rule); border-radius: 4px; padding: 6px 14px; margin: 14px 0; background: #fff; }}
.box summary {{ cursor: pointer; font-weight: 600; }}
.cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 8px 0 16px; }}
.card {{ background: #fff; border: 1px solid var(--rule); border-radius: 4px; padding: 12px 14px; }}
.card b {{ display: block; font-size: 28px; line-height: 1.2; }}
.card span {{ font-size: 13px; color: var(--ink2); }}
.tiles {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
.tile {{ background: #fff; border: 1px solid var(--rule); border-radius: 4px; padding: 10px; margin: 0 !important; }}
.tile figcaption b {{ display: block; color: var(--ink); font-size: 14px; }}
.zoom {{ cursor: zoom-in; }}
#lightbox {{ position: fixed; inset: 0; background: rgba(27,39,51,.85); display: none; align-items: center; justify-content: center; z-index: 98; cursor: zoom-out; }}
#lightbox img {{ max-width: 92vw; max-height: 88vh; background: #fff; padding: 12px; border-radius: 4px; }}
.split2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 28px; align-items: start; }}
.spine td {{ vertical-align: middle; }}
.spine th[data-key] {{ cursor: pointer; }}
.spark {{ width: 190px; height: 42px; display: block; }}
.raxis {{ position: relative; height: 14px; font-size: 10px; font-weight: 400; color: var(--ink2); }}
.raxis span {{ position: absolute; transform: translateX(-50%); }}
.tabs {{ display: flex; gap: 4px; border-bottom: 1px solid var(--rule); margin-top: 20px; }}
.tabs button {{ font: 14px var(--sans); background: none; border: 1px solid transparent; border-bottom: 0; padding: 6px 16px; cursor: pointer; color: var(--ink2); border-radius: 4px 4px 0 0; }}
.tabs button[aria-selected=true] {{ border-color: var(--rule); background: #fff; color: var(--ink); font-weight: 600; margin-bottom: -1px; }}
.panels img {{ max-width: 820px; display: block; }}
.panels section {{ background: #fff; border: 1px solid var(--rule); border-top: 0; padding: 4px 18px 12px; }}
.sticky2 {{ display: grid; grid-template-columns: 360px minmax(0, 1fr); gap: 36px; align-items: start; }}
.sticky2 aside {{ position: sticky; top: 16px; max-height: calc(100vh - 32px); overflow: auto; font-size: 14px; }}
.sticky2 h2:first-child {{ margin-top: 0; }}
</style>

{var_a}

{var_b}

{var_c}

{var_d}

<div id="lightbox"><img alt=""></div>
<div id="proto-bar" style="position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:99;display:flex;gap:10px;align-items:center;background:#111;color:#fff;padding:8px 14px;border-radius:999px;box-shadow:0 6px 20px rgba(0,0,0,.35);font:14px sans-serif">
<button id="proto-prev" style="all:unset;cursor:pointer;padding:0 6px">◀</button><span id="proto-label"></span><button id="proto-next" style="all:unset;cursor:pointer;padding:0 6px">▶</button></div>
<script>
(function () {{
  var keys = ["A", "B", "C", "D"];
  function show(k) {{
    document.querySelectorAll("[data-variant]").forEach(function (el) {{ el.hidden = el.dataset.variant !== k; }});
    var el = document.querySelector('[data-variant="' + k + '"]');
    document.getElementById("proto-label").textContent = "原型 " + k + "：" + el.dataset.name;
    var u = new URL(location.href); u.searchParams.set("variant", k); history.replaceState(null, "", u);
  }}
  function step(d) {{
    var k = new URL(location.href).searchParams.get("variant") || "A";
    show(keys[(keys.indexOf(k) + d + keys.length) % keys.length]);
  }}
  document.getElementById("proto-prev").onclick = function () {{ step(-1); }};
  document.getElementById("proto-next").onclick = function () {{ step(1); }};
  document.addEventListener("keydown", function (e) {{
    if (e.target.closest("input,textarea,[contenteditable]")) return;
    if (e.key === "ArrowLeft") step(-1); else if (e.key === "ArrowRight") step(1);
    if (e.key === "Escape") lb.style.display = "none";
  }});
  // A：点图放大
  var lb = document.getElementById("lightbox");
  document.querySelectorAll("img.zoom").forEach(function (im) {{
    im.onclick = function () {{ lb.querySelector("img").src = im.src; lb.style.display = "flex"; }};
  }});
  lb.onclick = function () {{ lb.style.display = "none"; }};
  // B：表头排序
  var tbody = document.querySelector(".spine tbody");
  document.querySelectorAll(".spine th[data-key]").forEach(function (th) {{
    var asc = true;
    th.onclick = function () {{
      var key = th.dataset.key, rows = Array.prototype.slice.call(tbody.rows);
      rows.sort(function (a, b) {{
        var x = a.dataset[key], y = b.dataset[key];
        var c = key === "roi" ? x.localeCompare(y) : parseFloat(x) - parseFloat(y);
        return asc ? c : -c;
      }});
      asc = !asc;
      rows.forEach(function (r) {{ tbody.appendChild(r); }});
    }};
  }});
  // C：标签页
  var tabs = document.querySelectorAll(".tabs button");
  function tab(k) {{
    tabs.forEach(function (b) {{ b.setAttribute("aria-selected", b.dataset.tab === k); }});
    document.querySelectorAll("[data-panel]").forEach(function (p) {{ p.hidden = p.dataset.panel !== k; }});
  }}
  tabs.forEach(function (b) {{ b.onclick = function () {{ tab(b.dataset.tab); }}; }});
  tab("dist");
  step(0);
}})();
</script>
"""


if __name__ == "__main__":
    main()
