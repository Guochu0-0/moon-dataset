"""PROTOTYPE（一次性）：「原型：ROI 页内容与版式」第四轮——原始产品怎么进 ROI 页。

信息栏：数据集一组 + 三列对照表（光学原图 | SAR 原图 | 重叠区影像）；右侧是重叠区影像缩略图。

  out/roi4-a/  A 叠合图：CE-2 分幅与 Mini-RF 条带重投影到同一坐标系叠在一起，白框是重叠区；
               可切换「光学原图 / SAR 原图 / 叠合」，点击放大
  out/roi4-b/  B 链接：页面不放原图；表中产品名是链接，点开单独看该原图（白框是重叠区）

只做 ROI_054、ROI_066、ROI_003。先跑 prep_overlay.py、prep_originals.py、build.py。
用法：python build_roi4.py
"""

from __future__ import annotations

import json
import shutil

import build as b
import build_roi3 as r3

OV = json.loads((b.A / "overlay.json").read_text(encoding="utf-8"))
PAGES = list(OV)
AS = r3.AS


def overlay(roi, height=460, width=640):
    o = OV[roi]
    h = min(height, round(width * o["h"] / o["w"]))
    w = round(h * o["w"] / o["h"])
    rect = lambda bx, cls: f'<rect class="{cls}" x="{bx[0]}" y="{bx[1]}" width="{bx[2]}" height="{bx[3]}"/>'
    svg = "".join(rect(f["box"], "fr") for f in o["frames"]) + rect(o["sar"], "sr") + rect(o["overlap"], "ov")
    return f"""<figure class="ovl" data-mode="both">
  <div class="ovl-ctl" role="group" aria-label="显示">
    <button type="button" data-m="ce2" aria-pressed="false">光学原图</button><button type="button" data-m="sar" aria-pressed="false">SAR 原图</button><button type="button" data-m="both" aria-pressed="true">叠合</button>
  </div>
  <div class="ovl-img" style="width:{w}px;height:{h}px" tabindex="0" role="button" aria-label="放大">
    <img class="l-ce2" src="{AS}overlay/{roi}/ce2.png" alt=""><img class="l-sar" src="{AS}overlay/{roi}/sar.png" alt="">
    <svg viewBox="0 0 1 1" preserveAspectRatio="none">{svg}</svg>
  </div>
  <figcaption>CE-2 分幅（{len(o['frames'])} 幅）与 Mini-RF 条带，重投影到重叠区影像的坐标系；
  白框是重叠区，虚线是各分幅的范围。图宽 {o['km'][0]} km。点击放大。</figcaption>
</figure>"""


OVL_JS = """
document.querySelectorAll('.ovl').forEach(function (f) {
  f.querySelectorAll('.ovl-ctl button').forEach(function (bt) { bt.addEventListener('click', function () {
    f.dataset.mode = bt.dataset.m;
    f.querySelectorAll('.ovl-ctl button').forEach(function (x) { x.setAttribute('aria-pressed', x === bt); });
  }); });
});
var lb = Site.h('div', 'lb', document.body); lb.hidden = true;
function openOvl(f) {
  var c = f.cloneNode(true), img = c.querySelector('.ovl-img');
  var ratio = parseFloat(img.style.width) / parseFloat(img.style.height);
  var hh = Math.min(window.innerHeight * 0.82, window.innerWidth * 0.9 / ratio);
  img.style.height = hh + 'px'; img.style.width = hh * ratio + 'px';
  c.querySelector('figcaption').textContent = '白框是重叠区，虚线是各分幅的范围。Esc 或点击背景关闭。';
  lb.innerHTML = ''; lb.appendChild(c); lb.hidden = false;
  c.querySelectorAll('.ovl-ctl button').forEach(function (bt) { bt.addEventListener('click', function (e) {
    e.stopPropagation(); c.dataset.mode = bt.dataset.m;
    c.querySelectorAll('.ovl-ctl button').forEach(function (x) { x.setAttribute('aria-pressed', x === bt); });
  }); });
}
document.querySelectorAll('.ovl .ovl-img').forEach(function (el) {
  el.addEventListener('click', function () { openOvl(el.closest('.ovl')); });
  el.addEventListener('keydown', function (e) { if (e.key === 'Enter') openOvl(el.closest('.ovl')); });
});
lb.addEventListener('click', function (e) { if (e.target === lb) lb.hidden = true; });
document.addEventListener('keydown', function (e) { if (e.key === 'Escape') lb.hidden = true; });"""


def info(r, links=False):
    f, m, o = b.FACTS[r["roi"]], b.MINIRF[r["roi"]], r3.ORIG[r["roi"]]
    w, s, e, nn = r["bbox"]
    ds = [("划分", f'<span class="sw {r["split"]}"></span>{r["split_zh"]}'), ("patch 对", str(r["patches"]))]
    if r["truth_patches"]:
        ds.append(("带评测真值点的 patch", f"{r['truth_patches']}，共 {f['truth_points']} 对点"))
    ds += [("中心", f"{b.lat(r['center'][1])}，{b.lon(r['center'][0])}"),
           ("范围", f"{b.lat(s)}–{b.lat(nn)}，{b.lon(w)}–{b.lon(e)}"),
           ("控制点", f'{f["tie_points"]} 对（<a href="#">标注规程</a>）')]
    fr, al = o["frames"], o["aligned"]
    one = len({(x["w"], x["h"]) for x in fr}) == 1 and len({x["proj"] for x in fr}) == 1
    if links:
        opt_id = "<br>".join(f'<a href="#" class="pl" data-k="ce2"><code>{x["id"]}</code></a>' for x in fr)
        sar_id = f'<a href="#" class="pl" data-k="sar"><code>{m["PRODUCT_ID"]}</code></a>'
        al_id = '<a href="#" class="pl" data-k="al">查看</a>'
    else:
        opt_id = "<br>".join(f"<code>{x['id']}</code>" for x in fr)
        sar_id = f"<code>{m['PRODUCT_ID']}</code>"
        al_id = "—"
    per = lambda fmt: fmt(fr[0]) + ("（每幅）" if len(fr) > 1 else "") if one else "<br>".join(f"{x['tile']}：{fmt(x)}" for x in fr)
    rows = [("产品", opt_id, sar_id, al_id),
            ("成像时刻（UTC）", "—", m["成像时刻UTC"].replace("T", " "), "—"),
            ("投影", per(lambda x: x["proj"]).replace("（每幅）", ""), "等距圆柱，中心经度 180°", al["proj"]),
            ("像元", "7 m", f"{float(m['原生采样_m']):.4f} m", f"{al['res']:g} m"),
            ("图像尺寸", per(lambda x: f"{x['w']:,} × {x['h']:,} 像素"), f"{o['sar']['w']:,} × {o['sar']['h']:,} 像素",
             f"{al['w']:,} × {al['h']:,} 像素"),
            ("入射角", "—", f"{float(m['入射角_deg']):.2f}°", "—"),
            ("视向", "—", {"LEFT": "左视", "RIGHT": "右视"}[m["视向"]], "—")]
    cmp = "".join(f'<tr><th scope="row">{k}</th><td>{a}</td><td>{c}</td><td class="alc">{d}</td></tr>' for k, a, c, d in rows)
    return ('<dl class="facts">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in ds) + "</dl>"
            '<table class="cmp"><thead><tr><th></th><th>光学原图<br><small>CE-2 DOM</small></th><th>SAR 原图<br><small>Mini-RF</small></th>'
            f'<th class="alc">重叠区影像<br><small>光学、SAR 各一幅</small></th></tr></thead><tbody>{cmp}</tbody></table>'
            '<p class="note">重叠区影像：光学与 SAR 公共覆盖区外扩 1.2 倍，两者重采样到 7.5 m 的同一网格；patch 从这两幅上切出。</p>')


def strips(roi):
    return ('<h2 class="imgh">重叠区影像</h2>' + r3.aligned_strips(roi) +
            '<p class="note">每 114 × 114 像素取均值，黑色是没有数据的区域。</p>')


def page_a(r):
    roi = r["roi"]
    body = f"""<div class="wrap roi">{r3.head(r)}
<div class="roi-grid"><div class="roi-side"><div id="loc" class="locator"></div>{info(r)}
<h2 class="imgh">原始产品</h2>{overlay(roi)}</div>
<div class="roi-main">{strips(roi)}</div></div></div>"""
    return body, r3.LOC % roi + OVL_JS


def page_b(r):
    roi = r["roi"]
    ce2 = r3.mosaic(roi)
    sar = r3.sar_orig(roi)
    al = r3.aligned_strips(roi)
    tpl = "".join(f'<template id="t-{k}"><figure>{html}<figcaption>{cap}</figcaption></figure></template>' for k, html, cap in [
        ("ce2", ce2, "光学原图：CE-2 DOM 分幅，按经纬排开。白框是重叠区。Esc 或点击任意处关闭。"),
        ("sar", sar, "SAR 原图：Mini-RF 条带。白框是重叠区。Esc 或点击任意处关闭。"),
        ("al", al, "重叠区影像。Esc 或点击任意处关闭。")])
    body = f"""<div class="wrap roi">{r3.head(r)}
<div class="roi-grid"><div class="roi-side"><div id="loc" class="locator"></div>{info(r, links=True)}</div>
<div class="roi-main">{strips(roi)}</div></div></div>{tpl}"""
    js = r3.LOC % roi + """
var lb = Site.h('div', 'lb', document.body); lb.hidden = true;
document.querySelectorAll('a.pl').forEach(function (a) { a.addEventListener('click', function (e) {
  e.preventDefault(); lb.innerHTML = document.getElementById('t-' + a.dataset.k).innerHTML; lb.hidden = false;
}); });
lb.addEventListener('click', function () { lb.hidden = true; });
document.addEventListener('keydown', function (e) { if (e.key === 'Escape') lb.hidden = true; });"""
    return body, js


CSS = r3.CSS + """
/* 第四轮 */
.ovl { margin: 0; }
.ovl-ctl { display: flex; gap: 0; margin-bottom: 8px; }
.ovl-ctl button { font: inherit; font-size: 13px; padding: 4px 12px; border: 1px solid var(--rule); background: transparent; color: var(--ink2); cursor: pointer; }
.ovl-ctl button + button { border-left: 0; }
.ovl-ctl button[aria-pressed=true] { background: var(--ink); color: var(--paper); border-color: var(--ink); }
.ovl-img { position: relative; background: #0d1319; cursor: zoom-in; max-width: 100%; }
.ovl-img img { position: absolute; inset: 0; width: 100%; height: 100%; }
.ovl-img svg { position: absolute; inset: 0; width: 100%; height: 100%; }
.ovl[data-mode=ce2] .l-sar, .ovl[data-mode=sar] .l-ce2 { display: none; }
.ovl[data-mode=both] .l-sar { opacity: .7; }
.ovl rect { fill: none; vector-effect: non-scaling-stroke; }
.ovl rect.fr { stroke: rgba(255,255,255,.55); stroke-width: 1px; stroke-dasharray: 4 3; }
.ovl rect.sr { stroke: none; }
.ovl rect.ov { stroke: #fff; stroke-width: 2px; }
.ovl figcaption { font-size: 13px; color: var(--ink2); margin-top: 6px; }
.lb .ovl { cursor: default; } .lb .ovl-img { max-width: none; cursor: default; }
.lb .ovl figcaption, .lb .ovl-ctl button { color: #dde; }
.lb .ovl-ctl button[aria-pressed=true] { background: #fff; color: #000; }
.lb .al img { height: 86vh; }
.roi-side .imgh { margin-top: 30px; }
.roi-main .al figure { flex: 0 1 auto; min-width: 0; }
.roi-main .al img { height: auto; max-height: 72vh; max-width: 100%; min-height: 0; }
"""

VARIANTS = [("roi4-a", "A 叠合图", page_a), ("roi4-b", "B 链接", page_b)]


def main():
    shutil.copytree(b.A / "overlay", b.OUT / "assets/overlay", dirs_exist_ok=True)
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
            other = VARIANTS[1 - i][0]
            bar = r3.SWITCH.format(links=links, prev=f"../../{other}/{rel}", next=f"../../{other}/{rel}")
            (site / rel).write_text(doc.replace("</body>", bar + "</body>"), encoding="utf-8")
    print("built", b.OUT / "roi4-a/rois/ROI_054.html")


if __name__ == "__main__":
    main()
