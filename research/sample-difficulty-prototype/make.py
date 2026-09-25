"""PROTOTYPE（一次性，issue #47）：「样本难度」一节的三种写法，挂在真实文档站里对比。

    PYTHONPATH=src conda run -n moon-dataset python research/sample-difficulty-prototype/make.py
    PYTHONPATH=src conda run -n moon-dataset python scripts/build_site.py

然后打开 `_site/data/difficulty.html?variant=A`（B、C），底部浮条或 ←/→ 切换。
只读仓库：`data/ground-truth/`、`data/metadata/minirf_metadata.csv`、
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


def main():
    OUT_ASSETS.mkdir(parents=True, exist_ok=True)
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
    OUT_PAGE.write_text(page(stats, rois), encoding="utf-8")
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


def page(s, rois):
    img = lambda name, alt: f'<figure><img src="../assets/prototype-difficulty/{name}" alt="{alt}" style="max-width:100%"></figure>'
    quant = ("<table><thead><tr><th></th><th>10 分位</th><th>25</th><th>中位</th><th>75</th><th>90</th><th>99</th>"
             f"<th>最大</th></tr></thead><tbody><tr><td>点上 RMSE（像素）</td><td>{f(s['p10'])}</td><td>{f(s['p25'])}</td>"
             f"<td>{f(s['p50'])}</td><td>{f(s['p75'])}</td><td>{f(s['p90'])}</td><td>{f(s['p99'])}</td><td>{f(s['max'])}</td>"
             f"</tr><tr><td>约合米</td><td>{s['p10']*PIXEL_M:.0f}</td><td>{s['p25']*PIXEL_M:.0f}</td><td>{s['p50']*PIXEL_M:.0f}</td>"
             f"<td>{s['p75']*PIXEL_M:.0f}</td><td>{s['p90']*PIXEL_M:.0f}</td><td>{s['p99']*PIXEL_M:.0f}</td>"
             f"<td>{s['max']*PIXEL_M:.0f}</td></tr></tbody></table>")
    define = ("<p><b>点上 RMSE</b>：一个 patch 里所有评测真值点上，光学点与 SAR 点在 patch 坐标下的距离的均方根，"
              "也就是不做任何配准时的评测误差。不拟合模型，不外推。</p>")

    a = f"""<div data-variant="A" data-name="极简：一张 CDF + 分位表">
<p class="note">PROTOTYPE 变体 A——文字只到「是什么、多大」；逐 ROI 的数放到各 ROI 页的一行摘要里。</p>
{define}
<p>验证集、测试集共 {s['n']} 个 patch 对有评测真值点，每个都给值。中位 {f(s['p50'])} 像素（约 {s['p50']*PIXEL_M:.0f} m），
90 分位 {f(s['p90'])} 像素；测试集比验证集难（中位 {f(s['Test']['p50'])} 对 {f(s['Val']['p50'])} 像素）。</p>
{img("cdf.png", "点上 RMSE 的累计分布")}
{quant}
<p class="note">每个 ROI 的中位与 10–90 分位写在对应的 ROI 页上。</p>
</div>"""

    b = f"""<div data-variant="B" data-name="按 ROI 展开：箱线图 + ROI 表">
<p class="note">PROTOTYPE 变体 B——主角是 ROI 之间的差别；文字多一段「为什么」。</p>
{define}
<p>全体 {s['n']} 个 patch：中位 {f(s['p50'])} 像素，10–90 分位 {f(s['p10'])}–{f(s['p90'])} 像素。
难度主要由 ROI 决定：同一 ROI 内的 patch 相差几倍，ROI 之间的中位相差一个数量级以上。</p>
{img("box-roi.png", "各 ROI 的点上 RMSE 箱线图")}
<p>ROI 按入射角从小到大排。入射角越小，地形引起的距离向位移越大（与 cot θ 成正比），
ROI 中位 RMSE 与入射角的秩相关为 {s['rho_inc']:.2f}。数据集的 SAR 窗口只按每个 ROI 的全局仿射放置，
地形带来的这部分错位留在了 patch 对里。</p>
{roi_table(rois)}
</div>"""

    c = f"""<div data-variant="C" data-name="分量与沿条带：散点 + 小多图 + 全部说明">
<p class="note">PROTOTYPE 变体 C——把「错位长什么样」讲透：分量、沿条带的变化、测量误差都写出来。</p>
<h2>度量</h2>
{define}
<p>所有有评测真值点的 patch 都给值，每个 patch 至少 {s['min_n']} 个点、中位 {s['med_n']:.0f} 个。沿用医学配准（ANHIR、DIR-Lab）报告配准前真值点误差的做法。</p>
<h2>分布</h2>
{img("cdf.png", "点上 RMSE 的累计分布")}
{quant}
<h2>错位几乎全在距离向</h2>
{img("dxdy.png", "patch 内平均错位 dx–dy 散点")}
<p>每个点是一个 patch 的平均错位。x（≈ 距离向）从 −200 到 +200 像素铺开，y（≈ 方位向）几乎贴着 0：
RMSE² 里 x 分量的占比中位为 {s['x_share']*100:.0f}%，y 分量的 RMSE 中位只有 {s['ry50']:.1f} 像素。
y 向在 patch 内几乎是纯平移；x 向在一个 patch 内还会随地形变化几十像素，所以一个平移或一个单应概括不了一个 patch。</p>
<h2>沿条带的变化</h2>
{img("strip.png", "各 ROI 沿条带的点上 RMSE")}
<p>同一条带上，难度成片连续变化，易段与难段交替，与地形起伏一致；入射角小的条带整体更难。</p>
<h2>测量误差</h2>
<p>难度量的测量误差：每个真值点带约 1 像素的标注抖动（见「标注质量」），相对中位 {f(s['p50'])} 像素可以忽略，
只会把最小的一批值（10 分位 {f(s['p10'])} 像素）略微抬高。</p>
<h2>各 ROI</h2>
{roi_table(rois)}
</div>"""

    return f"""# 样本难度

<div class="prototype-banner" style="background:#FFF4D6;border:1px solid #E39B1B;padding:8px 12px;border-radius:4px;font-size:14px">
PROTOTYPE（issue #47）：同一节的三种写法，用底部浮条或 ←/→ 切换。数字是真的，图是粗稿。</div>

{a}

{b}

{c}

<div id="proto-bar" style="position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:99;display:flex;gap:10px;align-items:center;background:#111;color:#fff;padding:8px 14px;border-radius:999px;box-shadow:0 6px 20px rgba(0,0,0,.35);font:14px sans-serif">
<button id="proto-prev" style="all:unset;cursor:pointer;padding:0 6px">◀</button><span id="proto-label"></span><button id="proto-next" style="all:unset;cursor:pointer;padding:0 6px">▶</button></div>
<script>
(function () {{
  var keys = ["A", "B", "C"];
  function show(k) {{
    document.querySelectorAll("[data-variant]").forEach(function (el) {{ el.hidden = el.dataset.variant !== k; }});
    var el = document.querySelector('[data-variant="' + k + '"]');
    document.getElementById("proto-label").textContent = k + "（" + el.dataset.name + "）";
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
  }});
  step(0);
}})();
</script>
"""


if __name__ == "__main__":
    main()
