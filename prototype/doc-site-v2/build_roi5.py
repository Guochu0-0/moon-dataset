"""PROTOTYPE（一次性）：「原型：ROI 页内容与版式」第五轮——原始产品叠合图，逐图层开关。

在第四轮 A 的基础上：去掉「光学原图 / SAR 原图 / 叠合」三选一，改为每幅图像一个开关
（各 CE-2 分幅、Mini-RF 条带、重叠区白框）。只有光学与 SAR 同时显示时才画分幅虚线。

  out/roi5/rois/<ROI>.html   只做 ROI_054、ROI_066、ROI_003

先跑 prep_overlay.py、prep_originals.py、build.py。用法：python build_roi5.py
"""

from __future__ import annotations

import shutil

import build as b
import build_roi3 as r3
import build_roi4 as r4

OV = r4.OV
AS = r3.AS


def overlay(roi, height=460, width=640):
    o = OV[roi]
    h = min(height, round(width * o["h"] / o["w"]))
    w = round(h * o["w"] / o["h"])
    rect = lambda bx, cls, extra="": f'<rect class="{cls}" x="{bx[0]}" y="{bx[1]}" width="{bx[2]}" height="{bx[3]}"{extra}/>'
    imgs = "".join(f'<img class="ly" data-l="{f["tile"]}" src="{AS}overlay/{roi}/ce2_{f["tile"]}.png" alt="">' for f in o["frames"])
    imgs += f'<img class="ly sar" data-l="sar" src="{AS}overlay/{roi}/sar.png" alt="">'
    svg = "".join(rect(f["box"], "fr", f' data-l="{f["tile"]}"') for f in o["frames"]) + rect(o["overlap"], "ov", ' data-l="ov"')
    chip = lambda l, text, title, cls: (f'<button type="button" class="chip {cls}" data-l="{l}" aria-pressed="true" title="{title}">'
                                        f'<span class="box" aria-hidden="true"></span>{text}</button>')
    opt = "".join(chip(f["tile"], f["tile"], f["id"], "opt") for f in o["frames"])
    return f"""<figure class="ovl both">
  <div class="ovl-img" style="width:{w}px;height:{h}px" tabindex="0" role="button" aria-label="放大">{imgs}
    <svg viewBox="0 0 1 1" preserveAspectRatio="none">{svg}</svg>
  </div>
  <div class="layers">
    <span class="grp"><span class="gl">光学原图</span>{opt}</span>
    <span class="grp"><span class="gl">SAR 原图</span>{chip("sar", "Mini-RF", b.MINIRF[roi]["PRODUCT_ID"], "sar")}</span>
    <span class="grp">{chip("ov", "重叠区", "重叠区影像的范围", "ov")}</span>
  </div>
  <figcaption>重投影到重叠区影像的坐标系，图宽 {o['km'][0]} km。点击图像放大。</figcaption>
</figure>"""


OVL_JS = """
function bindOvl(f) {
  function sync() {
    var on = {};
    f.querySelectorAll('.chip').forEach(function (c) { on[c.dataset.l] = c.getAttribute('aria-pressed') === 'true'; });
    f.querySelectorAll('[data-l]:not(.chip)').forEach(function (el) { el.style.display = on[el.dataset.l] ? '' : 'none'; });
    var opt = Array.prototype.some.call(f.querySelectorAll('.chip.opt'), function (c) { return on[c.dataset.l]; });
    f.classList.toggle('both', opt && on.sar);
  }
  f.querySelectorAll('.chip').forEach(function (c) { c.addEventListener('click', function (e) {
    e.stopPropagation(); c.setAttribute('aria-pressed', c.getAttribute('aria-pressed') !== 'true'); sync();
  }); });
  sync();
}
document.querySelectorAll('.ovl').forEach(bindOvl);
if (location.hash.indexOf('#off=') === 0) location.hash.slice(5).split(',').forEach(function (l) {
  var c = document.querySelector('.ovl .chip[data-l="' + l + '"]'); if (c) c.click();
});
var lb = Site.h('div', 'lb', document.body); lb.hidden = true;
function openOvl(f) {
  var c = f.cloneNode(true), img = c.querySelector('.ovl-img');
  var ratio = parseFloat(img.style.width) / parseFloat(img.style.height);
  var hh = Math.min(window.innerHeight * 0.8, window.innerWidth * 0.9 / ratio);
  img.style.height = hh + 'px'; img.style.width = hh * ratio + 'px';
  c.querySelector('figcaption').textContent = 'Esc 或点击背景关闭。';
  lb.innerHTML = ''; lb.appendChild(c); lb.hidden = false; bindOvl(c);
}
document.querySelectorAll('.ovl .ovl-img').forEach(function (el) {
  el.addEventListener('click', function () { openOvl(el.closest('.ovl')); });
  el.addEventListener('keydown', function (e) { if (e.key === 'Enter') openOvl(el.closest('.ovl')); });
});
lb.addEventListener('click', function (e) { if (e.target === lb) lb.hidden = true; });
document.addEventListener('keydown', function (e) { if (e.key === 'Escape') lb.hidden = true; });"""


def page(r):
    roi = r["roi"]
    body = f"""<div class="wrap roi">{r3.head(r)}
<div class="roi-grid"><div class="roi-side"><div id="loc" class="locator"></div>{r4.info(r)}
<h2 class="imgh">原始产品</h2>{overlay(roi)}</div>
<div class="roi-main">{r4.strips(roi)}</div></div></div>"""
    return body, r3.LOC % roi + OVL_JS


CSS = r4.CSS + """
/* 第五轮 */
.ovl-img .ly { position: absolute; inset: 0; width: 100%; height: 100%; }
.ovl.both .ly.sar { opacity: .7; }
.ovl:not(.both) rect.fr { display: none; }
.layers { display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 10px; font-size: 13px; align-items: center; }
.grp { display: inline-flex; gap: 6px; align-items: center; }
.gl { color: var(--ink2); margin-right: 2px; }
.chip { font: inherit; font-size: 12.5px; display: inline-flex; align-items: center; gap: 6px; padding: 3px 9px 3px 7px;
  border: 1px solid var(--rule); border-radius: 3px; background: transparent; color: var(--ink2); cursor: pointer; }
.chip .box { width: 11px; height: 11px; border: 1.5px solid currentColor; border-radius: 2px; }
.chip[aria-pressed=true] { color: var(--ink); border-color: var(--ink); }
.chip[aria-pressed=true] .box { background: currentColor; box-shadow: inset 0 0 0 2px var(--paper); }
.chip.ov[aria-pressed=true] .box { background: transparent; border-color: var(--ink); box-shadow: none; outline: 1.5px solid var(--ink); outline-offset: -4px; }
.lb .ovl { background: var(--paper); padding: 14px; border-radius: 4px; }
.lb .ovl figcaption { color: var(--ink2); }
"""


def main():
    shutil.copytree(b.A / "overlay", b.OUT / "assets/overlay", dirs_exist_ok=True)
    site = b.OUT / "roi5"
    if site.exists():
        shutil.rmtree(site)
    (site / "rois").mkdir(parents=True)
    (site / "style.css").write_text((b.HERE / "a.css").read_text(encoding="utf-8") + CSS, encoding="utf-8")
    (site / "search-index.js").write_text("window.SEARCH=[];", encoding="utf-8")
    for roi in OV:
        r = next(x for x in b.ROIS if x["roi"] == roi)
        body, js = page(r)
        (site / f"rois/{roi}.html").write_text(b.shell("roi5", f"rois/{roi}.html", roi, body, js), encoding="utf-8")
    print("built", site / "rois/ROI_054.html")


if __name__ == "__main__":
    main()
