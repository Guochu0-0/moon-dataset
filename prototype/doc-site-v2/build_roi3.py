"""PROTOTYPE（一次性）：「原型：ROI 页内容与版式」第三轮——原始产品与对齐影像怎么同时放进 ROI 页。

信息栏在三个方案里相同：数据集一组 + 三列对照表（光学原图 | SAR 原图 | 对齐影像）。差别只在影像：

  out/roi3-a/  A 页签：右侧在「对齐影像」「原始产品」之间切换
  out/roi3-b/  B 对齐影像为主：右侧只放对齐影像，表中产品格里放原图小图，点开看大图
  out/roi3-c/  C 并排：影像通栏放在上方，原图 → 对齐影像依次排开，信息在下方

原图上的白框是对齐影像的范围。只做 ROI_054、ROI_066、ROI_003。
先跑 prep_originals.py、build.py，再跑本脚本。用法：python build_roi3.py
"""

from __future__ import annotations

import json
import shutil

import build as b

ORIG = json.loads((b.A / "orig.json").read_text(encoding="utf-8"))
PAGES = list(ORIG)
AS = "../../assets/"


def framed(src, outline, cls="ob", big=None, cap=""):
    pts = " ".join(f"{x},{y}" for x, y in outline)
    attr = f' data-big="{big}" data-cap="{cap}" tabindex="0" role="button"' if big else ""
    return (f'<div class="{cls}"{attr}><img src="{src}" alt=""><svg viewBox="0 0 1 1" preserveAspectRatio="none">'
            f'<polygon points="{pts}"/></svg></div>')


def mosaic(roi, big=False):
    o = ORIG[roi]
    lats = sorted({f["lat"] for f in o["frames"]}, reverse=True)
    lons = sorted({f["lon"] for f in o["frames"]})
    cells = ""
    for f in o["frames"]:
        src = f"{AS}orig/{roi}/ce2_{f['tile']}.jpg"
        cells += (f'<div style="grid-row:{lats.index(f["lat"]) + 1};grid-column:{lons.index(f["lon"]) + 1}">'
                  + framed(src, f["outline"], big=src if big else None, cap=f["id"]) + "</div>")
    f0 = o["frames"][0]
    aspect = len(lons) * f0["w"] / (len(lats) * f0["h"])
    return f'<div class="mosaic" style="grid-template-columns:repeat({len(lons)},1fr);--asp:{aspect:.3f}">{cells}</div>'


def sar_orig(roi, big=False):
    src = f"{AS}orig/{roi}/minirf.jpg"
    return framed(src, ORIG[roi]["sar"]["outline"], "ob sar", big=src if big else None, cap=b.MINIRF[roi]["PRODUCT_ID"])


def aligned_strips(roi):
    return (f'<div class="al"><figure><img src="{AS}thumbs/{roi}_optical.png" alt=""><figcaption>光学</figcaption></figure>'
            f'<figure><img src="{AS}thumbs/{roi}_sar.png" alt=""><figcaption>SAR</figcaption></figure></div>')


def info(r, product_thumbs=False):
    f, m, o = b.FACTS[r["roi"]], b.MINIRF[r["roi"]], ORIG[r["roi"]]
    w, s, e, nn = r["bbox"]
    ds = [("划分", f'<span class="sw {r["split"]}"></span>{r["split_zh"]}'), ("patch 对", str(r["patches"]))]
    if r["truth_patches"]:
        ds.append(("带评测真值点的 patch", f"{r['truth_patches']}，共 {f['truth_points']} 对点"))
    ds += [("中心", f"{b.lat(r['center'][1])}，{b.lon(r['center'][0])}"),
           ("范围", f"{b.lat(s)}–{b.lat(nn)}，{b.lon(w)}–{b.lon(e)}"),
           ("对齐控制点", f'{f["tie_points"]} 对（<a href="#">标注规程</a>）')]
    fr, al = o["frames"], o["aligned"]
    one = len({(x["w"], x["h"]) for x in fr}) == 1 and len({x["proj"] for x in fr}) == 1
    opt_id = "<br>".join(f"<code>{x['id']}</code>" for x in fr)
    if product_thumbs:
        opt_id = mosaic(r["roi"], big=True) + opt_id
        sar_id = sar_orig(r["roi"], big=True) + f"<code>{m['PRODUCT_ID']}</code>"
    else:
        sar_id = f"<code>{m['PRODUCT_ID']}</code>"
    per = lambda key, fmt: fmt(fr[0]) if one else "<br>".join(f"{x['tile']}：{fmt(x)}" for x in fr)
    rows = [("产品", opt_id, sar_id, "两边重合区域，同一网格"),
            ("成像时刻（UTC）", "—", m["成像时刻UTC"].replace("T", " "), "—"),
            ("投影", per("proj", lambda x: x["proj"]), "等距圆柱，中心经度 180°", al["proj"]),
            ("像元", "7 m", f"{float(m['原生采样_m']):.4f} m", f"{al['res']:g} m"),
            ("图像尺寸", per("w", lambda x: f"{x['w']:,} × {x['h']:,} 像素") + ("（每幅）" if one and len(fr) > 1 else ""),
             f"{o['sar']['w']:,} × {o['sar']['h']:,} 像素", f"{al['w']:,} × {al['h']:,} 像素"),
            ("入射角", "—", f"{float(m['入射角_deg']):.2f}°", "—"),
            ("视向", "—", {"LEFT": "左视", "RIGHT": "右视"}[m["视向"]], "—")]
    cmp = "".join(f'<tr><th scope="row">{k}</th><td>{a}</td><td>{c}</td><td class="alc">{d}</td></tr>' for k, a, c, d in rows)
    return ('<dl class="facts">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in ds) + "</dl>"
            '<table class="cmp"><thead><tr><th></th><th>光学原图<br><small>CE-2 DOM</small></th><th>SAR 原图<br><small>Mini-RF</small></th>'
            f'<th class="alc">对齐影像<br><small>光学、SAR 各一幅</small></th></tr></thead><tbody>{cmp}</tbody></table>')


def head(r):
    i = PAGES.index(r["roi"])
    prev, nxt = PAGES[i - 1], PAGES[(i + 1) % len(PAGES)]
    return f"""<header class="roi-head"><h1>{r['roi']}</h1>
    <p class="split-tag"><span class="sw {r['split']}"></span>{r['split_zh']}</p>
    <nav class="stepper" aria-label="相邻 ROI"><a href="{prev}.html">上一个 {prev}</a><a href="{nxt}.html">下一个 {nxt}</a></nav></header>"""


LOC = "Site.moonMap(document.getElementById('loc'), {mode:'dots', focus:'%s'});"
CAP_AL = '<p class="note">对齐影像：光学与 SAR 重合区域，裁剪后重采样到同一网格，patch 从这两幅上切出。缩略图每 114 × 114 像素取均值，黑色是没有数据的区域。</p>'
CAP_OR = '<p class="note">原始产品：CE-2 DOM 分幅（按经纬排开）与 Mini-RF 条带。白框是对齐影像的范围。</p>'


def page_a(r):
    roi = r["roi"]
    body = f"""<div class="wrap roi">{head(r)}
<div class="roi-grid"><div class="roi-side"><div id="loc" class="locator"></div>{info(r)}</div>
<div class="roi-main">
  <div class="tabs" role="tablist"><button role="tab" aria-selected="true" data-t="al">对齐影像</button><button role="tab" aria-selected="false" data-t="or">原始产品</button></div>
  <div class="tp" data-t="al">{aligned_strips(roi)}{CAP_AL}</div>
  <div class="tp" data-t="or" hidden><div class="origs">{mosaic(roi)}{sar_orig(roi)}</div>{CAP_OR}</div>
</div></div></div>"""
    js = LOC % roi + """
document.querySelectorAll('.tabs button').forEach(function (bt) { bt.addEventListener('click', function () {
  document.querySelectorAll('.tabs button').forEach(function (x) { x.setAttribute('aria-selected', x === bt); });
  document.querySelectorAll('.tp').forEach(function (p) { p.hidden = p.dataset.t !== bt.dataset.t; });
}); });
if (location.hash === '#or') document.querySelector('.tabs button[data-t=or]').click();"""
    return body, js


LIGHTBOX = """
var lb = Site.h('div', 'lb', document.body); lb.hidden = true;
function openLb(el) {
  lb.innerHTML = '<figure>' + el.outerHTML.replace(/ data-big="[^"]*"/, '') + '<figcaption>' + el.dataset.cap + '。白框是对齐影像的范围。点击任意处关闭。</figcaption></figure>';
  lb.hidden = false;
}
document.querySelectorAll('[data-big]').forEach(function (el) {
  el.addEventListener('click', function () { openLb(el); });
  el.addEventListener('keydown', function (e) { if (e.key === 'Enter') openLb(el); });
});
lb.addEventListener('click', function () { lb.hidden = true; });
document.addEventListener('keydown', function (e) { if (e.key === 'Escape') lb.hidden = true; });"""


def page_b(r):
    roi = r["roi"]
    body = f"""<div class="wrap roi">{head(r)}
<div class="roi-grid"><div class="roi-side"><div id="loc" class="locator"></div>{info(r, product_thumbs=True)}
<p class="note">表中小图是原始产品，白框是对齐影像的范围，点击看大图。</p></div>
<div class="roi-main"><h2 class="imgh">对齐影像</h2>{aligned_strips(roi)}{CAP_AL}</div></div></div>"""
    return body, LOC % roi + LIGHTBOX


def page_c(r):
    roi = r["roi"]
    body = f"""<div class="wrap roi">{head(r)}
<div class="chain">
  <figure class="c-orig"><div class="c-img">{mosaic(roi, big=True)}</div><figcaption>光学原图 · CE-2 DOM</figcaption></figure>
  <figure class="c-orig"><div class="c-img">{sar_orig(roi, big=True)}</div><figcaption>SAR 原图 · Mini-RF</figcaption></figure>
  <div class="arrow" aria-hidden="true">→<small>裁剪白框内的<br>重合区域，<br>重采样到<br>同一网格</small></div>
  <figure class="c-al"><div class="c-img">{aligned_strips(roi)}</div></figure>
</div>
<p class="note">白框是对齐影像的范围。点击原图看大图。对齐影像缩略图每 114 × 114 像素取均值，黑色是没有数据的区域。</p>
<div class="c-info"><div>{info(r)}</div><div id="loc" class="locator"></div></div>
</div>"""
    return body, LOC % roi + LIGHTBOX


CSS = """
/* 第三轮 */
.roi-grid { grid-template-columns: 640px minmax(0, 1fr); gap: 40px; }
.cmp small { font-weight: 400; color: var(--ink2); }
.cmp .alc { background: rgba(46,123,214,.06); padding-left: 8px; min-width: 10em; }
.cmp code { font-size: 11px; }
.cmp td .mosaic, .cmp td .ob.sar { margin-bottom: 6px; }
.cmp td .mosaic { width: 120px; } .cmp td .ob.sar { height: 150px; }
.ob { position: relative; display: inline-block; line-height: 0; overflow: hidden; background: #000; }
.ob img { display: block; width: 100%; height: auto; }
.ob.sar img { height: 100%; width: auto; }
.ob svg { position: absolute; inset: 0; width: 100%; height: 100%; }
.ob polygon { fill: none; stroke: #fff; stroke-width: 2px; vector-effect: non-scaling-stroke; }
.ob[data-big] { cursor: zoom-in; }
.mosaic { display: grid; gap: 2px; }
.mosaic .ob { width: 100%; }
.al { display: flex; gap: 14px; }
.al figure { margin: 0; } .al img { display: block; height: 72vh; min-height: 420px; width: auto; background: #000; image-rendering: pixelated; }
.al figcaption, .c-orig figcaption, .c-al figcaption { font-size: 13px; color: var(--ink2); margin-top: 6px; }
.tabs { display: flex; gap: 0; margin-bottom: 14px; border-bottom: 1px solid var(--rule); }
.tabs button { font: inherit; font-size: 14px; background: none; border: 0; padding: 8px 14px; cursor: pointer; color: var(--ink2); border-bottom: 2px solid transparent; }
.tabs button[aria-selected=true] { color: var(--ink); border-color: var(--ink); font-weight: 600; }
.origs { display: flex; gap: 14px; align-items: flex-start; }
.origs .mosaic { width: 360px; } .origs .ob.sar { height: 72vh; }
.imgh { font-size: 15px; margin: 0 0 10px; }
.lb { position: fixed; inset: 0; z-index: 900; background: rgba(10,14,18,.88); display: flex; align-items: center; justify-content: center; cursor: zoom-out; }
.lb[hidden] { display: none; }
.lb figure { margin: 0; color: #dde; font-size: 13px; text-align: center; }
.lb .mosaic, .lb .ob:not(.sar) { width: min(80vw, 86vh); }
.lb .ob.sar { height: 86vh; }
.lb figcaption { margin-top: 8px; }
.chain { display: flex; align-items: flex-start; gap: 18px; margin-top: 24px; }
.chain .c-img { height: 520px; display: flex; align-items: flex-start; }
.chain .c-orig .mosaic { width: calc(500px * var(--asp)); max-width: 520px; }
.chain .c-orig .ob.sar { height: 520px; }
.chain .al img { height: 520px; min-height: 0; }
.chain figure { margin: 0; }
.arrow { align-self: center; font-size: 34px; color: var(--ink2); text-align: center; line-height: 1; }
.arrow small { display: block; font-size: 12px; line-height: 1.5; margin-top: 8px; }
.c-info { display: grid; grid-template-columns: minmax(0, 720px) 1fr; gap: 48px; margin-top: 28px; }
"""


VARIANTS = [("roi3-a", "A 页签", page_a), ("roi3-b", "B 表中小图", page_b), ("roi3-c", "C 并排", page_c)]

SWITCH = """<div id="proto-bar"><span>原型</span>{links}</div>
<style>#proto-bar{{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);z-index:999;display:flex;gap:6px;align-items:center;
background:#000;color:#fff;border-radius:999px;padding:5px 8px 5px 14px;font:13px/1.2 system-ui,"Microsoft YaHei";box-shadow:0 6px 20px rgba(0,0,0,.35)}}
#proto-bar span{{opacity:.6;margin-right:4px}}#proto-bar a{{color:#fff;text-decoration:none;padding:4px 10px;border-radius:999px}}
#proto-bar a[aria-current]{{background:#fff;color:#000}}</style>
<script>document.addEventListener('keydown',function(e){{var t=document.activeElement;if(t&&(t.tagName==='INPUT'||t.isContentEditable))return;
if(e.key==='ArrowLeft')location.href='{prev}';if(e.key==='ArrowRight')location.href='{next}';}});</script>"""


def main():
    shutil.copytree(b.A / "orig", b.OUT / "assets/orig", dirs_exist_ok=True)
    for i, (key, label, fn) in enumerate(VARIANTS):
        site = b.OUT / key
        if site.exists():
            shutil.rmtree(site)
        (site / "rois").mkdir(parents=True)
        (site / "style.css").write_text((b.HERE / "a.css").read_text(encoding="utf-8") + CSS, encoding="utf-8")
        (site / "search-index.js").write_text("window.SEARCH=[];", encoding="utf-8")
        for roi in PAGES:
            r = next(x for x in b.ROIS if x["roi"] == roi)
            body, js = fn(r)
            rel = f"rois/{roi}.html"
            doc = b.shell(key, rel, roi, body, js)
            links = "".join(f'<a href="../../{k}/{rel}"{" aria-current=page" if k == key else ""}>{lb}</a>' for k, lb, _ in VARIANTS)
            bar = SWITCH.format(links=links, prev=f"../../{VARIANTS[i - 1][0]}/{rel}", next=f"../../{VARIANTS[(i + 1) % 3][0]}/{rel}")
            (site / rel).write_text(doc.replace("</body>", bar + "</body>"), encoding="utf-8")
    print("built", b.OUT / "roi3-a/rois/ROI_054.html")


if __name__ == "__main__":
    main()
