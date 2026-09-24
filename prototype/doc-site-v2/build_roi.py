"""PROTOTYPE（一次性）：「原型：ROI 页内容与版式」——ROI 页放什么、ROI 总表列哪些字段。

三个内容方案，版式与视觉都按「原型：文档站的视觉设计」的结论（A 月面图集 + B 的 ROI 页版式）：

  out/roi-a/  A 精简：只写这个 ROI 在数据集里的事实
  out/roi-b/  B 带来源：A + Mini-RF 条带参数、CE-2 分幅、对齐控制点、路径
  out/roi-c/  C 按 patch 浏览：A 的事实 + 点网格格子看该对 patch 与真值点

只做 ROI_027（训练集）与 ROI_054（测试集）两页；总表列全部 67 个。
先跑 build.py（生成 out/assets），再跑本脚本。用法：python build_roi.py
"""

from __future__ import annotations

import csv
import html
import json
import shutil

import build as b

EXTRA = json.loads((b.A / "roi-extra.json").read_text(encoding="utf-8"))
PAGES = ("ROI_027", "ROI_054")
MINIRF = {}
with open(b.REPO / "data/metadata/minirf_metadata.csv", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        MINIRF[f"ROI_{int(row['ROI'].split('_')[1]):03d}"] = row

# 备注：只收读者用数据时要知道的事实。待复核的（局部错位）不进文档；
# 处理过程中的细节（lat_ts、两个 SAR 文件、遗留控制点、ROI_073 重排、ROI_060 删除）写代码注释。
NOTES = {
    "ROI_027": ["patch 编号缺 95、98、99：这三块基本全黑，已丢弃。"],
    "ROI_054": ["与训练集 <a>ROI_017</a> 的范围重叠 57%；patch 级只有 17 个 patch 有重叠，重叠面积都不超过 16%。"],
    "ROI_017": ["与测试集 <a>ROI_054</a> 的范围重叠 57%；patch 级只有 17 个 patch 有重叠，重叠面积都不超过 16%。"],
    "ROI_038": ["与验证集 <a>ROI_071</a> 的范围重叠 17.5%，patch 不重叠。"],
    "ROI_071": ["与训练集 <a>ROI_038</a> 的范围重叠 17.5%，patch 不重叠。"],
}
SHORT = {"ROI_027": "编号缺 95、98、99", "ROI_054": "与 ROI_017 部分重叠", "ROI_017": "与 ROI_054 部分重叠",
         "ROI_038": "与 ROI_071 部分重叠", "ROI_071": "与 ROI_038 部分重叠"}
SPLIT_ZH = dict(b.SPLITS)


def notes(roi):
    out = []
    for t in NOTES.get(roi, []):
        if "<a>" not in t:
            out.append(t)
            continue
        other = t[t.index("<a>") + 3:t.index("</a>")]
        href = f"{other}.html" if other in PAGES else f"../../a-atlas/rois/{other}.html"
        out.append(t.replace("<a>", f'<a href="{href}">'))
    return out


def roi_link(roi):
    return f'<a href="{roi}.html">{roi}</a>' if roi in PAGES else roi


def dataset_facts(r):
    e = EXTRA.get(r["roi"], {})
    w, s, ee, nn = r["bbox"]
    rows = [("划分", f'<span class="sw {r["split"]}"></span>{r["split_zh"]}'),
            ("patch 对", str(r["patches"]))]
    if r["truth_patches"]:
        rows.append(("带评测真值点的 patch", f'{r["truth_patches"]}（{e.get("truth_points", "—")} 对点）'))
    rows += [("中心", f"{b.lat(r['center'][1])}，{b.lon(r['center'][0])}"),
             ("范围", f"{b.lat(s)}–{b.lat(nn)}，{b.lon(w)}–{b.lon(ee)}")]
    return rows


def source_facts(r):
    m, e = MINIRF[r["roi"]], EXTRA[r["roi"]]
    return [
        ("Mini-RF 产品", f"<code>{m['PRODUCT_ID']}</code>"),
        ("成像时刻（UTC）", m["成像时刻UTC"].replace("T", " ")),
        ("入射角", f"{float(m['入射角_deg']):.2f}°"),
        ("视向", {"LEFT": "左视", "RIGHT": "右视"}[m["视向"]] + f"，视方位角 {float(m['视方位角_deg']):.2f}°"),
        ("条带尺寸", f"{int(m['条带宽_px']):,} × {int(m['条带长_px']):,} 像素，采样 {float(m['原生采样_m']):.2f} m"),
        ("有效分辨率", f"距离向 {m['实测有效分辨率_距离向_m']} m，方位向 {m['实测有效分辨率_方位向_m']} m"),
        ("CE-2 分幅", "<br>".join(f"<code>{x}</code>" for x in e["ce2_frames"])),
        ("对齐控制点", f"{e['tie_points']} 对，<code>data/tie-points/{r['raw']}/{e['tie_gen']}/opt_tie.pts</code>"),
        ("产物目录", f"<code>Processed_Data/{r['split']}/{r['roi']}/</code>"),
    ]


def dl(rows):
    return '<dl class="facts">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"


def notes_block(r):
    ns = notes(r["roi"])
    return "<h2>备注</h2><ul class=\"issues\">" + "".join(f"<li>{x}</li>" for x in ns) + "</ul>" if ns else ""


def grid_caption(r):
    t = f'；<span class="sw-t {r["split"]}"></span>着色的格子带评测真值点' if r["truth_patches"] else ""
    return f'<p class="note">对齐影像的缩略图，黑色是没有数据的区域。网格是各 patch 的范围{t}。</p>'


def page(r, right, script=""):
    other = PAGES[1 - PAGES.index(r["roi"])]
    body = f"""
<div class="wrap roi rp">
  <header class="roi-head">
    <p class="crumbs"><a href="index.html">ROI 总表</a></p>
    <h1>{r['roi']}</h1>
    <nav class="stepper" aria-label="相邻 ROI"><a href="{other}.html">{other}</a></nav>
  </header>
  <div class="rp-grid">
    <div class="rp-strips {r['split']}"><div id="strips"></div>{grid_caption(r)}</div>
    <div class="rp-info">{right}</div>
  </div>
</div>"""
    js = f"Site.stripFigure(document.getElementById('strips'), '{r['roi']}', ['optical','sar']);\n" + script
    return r["roi"], body, js


def locator(r):
    return f'<div id="loc" class="locator"></div>', f"Site.moonMap(document.getElementById('loc'), {{mode:'dots', focus:'{r['roi']}'}});\n"


# ---------------- 三个方案的 ROI 页 ----------------

def roi_a(r):
    loc, js = locator(r)
    return page(r, dl(dataset_facts(r)) + notes_block(r) + loc, js)


def roi_b(r):
    loc, js = locator(r)
    right = (dl(dataset_facts(r)) + notes_block(r) + "<h2>来源</h2>" + dl(source_facts(r)) + loc)
    return page(r, right, js)


def roi_c(r):
    e = EXTRA[r["roi"]]
    right = (dl(dataset_facts(r)) + notes_block(r) +
             '<h2 id="ph">patch</h2><div id="pv" class="pv"></div>'
             '<p class="note">点击左侧网格里的格子换一对 patch。左为光学，右为 SAR 总功率（dB）。</p>')
    first = next(iter(e["points"]), "0")
    js = f"""
var ROI = '{r['roi']}', PTS = {json.dumps(e['points'])}, TRUTH = {json.dumps(bool(r['truth_patches']))};
var pv = document.getElementById('pv'), ph = document.getElementById('ph');
function showPatch(k) {{
  var pts = PTS[k] || [];
  ph.textContent = 'patch_' + k + (TRUTH ? (pts.length ? '，' + pts.length + ' 对评测真值点' : '，无评测真值点') : '');
  var base = document.body.dataset.root + '../assets/patches/' + ROI + '/p' + k;
  var svg = '<svg viewBox="0 0 1034 512" class="pair-svg"><image href="' + base + '_opt.jpg" width="512" height="512"/>' +
    '<image href="' + base + '_sar.jpg" x="522" width="512" height="512"/>';
  pts.forEach(function (p) {{ svg += '<circle cx="' + p[0] + '" cy="' + p[1] + '" r="9"/><circle cx="' + (p[2] + 522) + '" cy="' + p[3] + '" r="9"/>'; }});
  pv.innerHTML = svg + '</svg>';
  document.querySelectorAll('.grid rect').forEach(function (c) {{ c.classList.toggle('sel', c.dataset.i === String(k)); }});
}}
document.querySelectorAll('.grid rect').forEach(function (c, j) {{
  c.dataset.i = c.querySelector('title').textContent.match(/\\d+/)[0];
  c.addEventListener('click', function () {{ showPatch(c.dataset.i); }});
}});
showPatch('{first}');"""
    return page(r, right, js)


# ---------------- 三个方案的 ROI 总表 ----------------

def table(cols, rows_fn, extra=""):
    head = "".join(f"<th>{c}</th>" for c in cols)
    trs = "".join(f'<tr data-roi="{r["roi"]}" data-split="{r["split"]}">{rows_fn(r)}</tr>' for r in b.ROIS)
    return f"""
<div class="wrap"><h1>ROI 总表</h1>{extra}</div>
<div class="wrap"><div id="map" class="map-mid"></div></div>
<div class="wrap"><table class="roitable"><thead><tr>{head}</tr></thead><tbody>{trs}</tbody></table></div>"""


TABLE_JS = """
var rows = {}; document.querySelectorAll('tr[data-roi]').forEach(function (tr) { rows[tr.dataset.roi] = tr; });
var m = Site.moonMap(document.getElementById('map'), {mode:'strips', graticule:true, onHover: function (id) {
  for (var k in rows) rows[k].classList.toggle('hl', k === id);
}});
Object.keys(rows).forEach(function (k) {
  rows[k].addEventListener('mouseenter', function () { m.highlight(k); });
  rows[k].addEventListener('mouseleave', function () { m.highlight(null); });
});"""


def base_cells(r):
    return (f'<th scope="row">{roi_link(r["roi"])}</th><td><span class="sw {r["split"]}"></span>{r["split_zh"]}</td>'
            f'<td class="num">{r["patches"]}</td><td class="num">{b.n(r["truth_patches"])}</td>'
            f'<td>{b.lat(r["center"][1])}，{b.lon(r["center"][0])}</td>')


def table_a():
    return table(["ROI", "划分", "patch 对", "带真值点", "中心", "备注"],
                 lambda r: base_cells(r) + f'<td class="issues">{SHORT.get(r["roi"], "")}</td>')


def table_b():
    def row(r):
        m = MINIRF[r["roi"]]
        return (base_cells(r) + f'<td><code class="pid">{m["PRODUCT_ID"]}</code></td><td>{m["成像时刻UTC"][:10]}</td>'
                f'<td class="num">{float(m["入射角_deg"]):.1f}°</td><td>{"左" if m["视向"] == "LEFT" else "右"}</td>'
                f'<td class="issues">{SHORT.get(r["roi"], "")}</td>')
    return table(["ROI", "划分", "patch 对", "带真值点", "中心", "Mini-RF 产品", "成像日期", "入射角", "视向", "备注"], row)


def table_c():
    def row(r):
        return (f'<td class="th"><img src="../../assets/thumbs/{r["roi"]}_optical.png" alt="" loading="lazy">'
                f'<img src="../../assets/thumbs/{r["roi"]}_sar.png" alt="" loading="lazy"></td>' + base_cells(r))
    return table(["", "ROI", "划分", "patch 对", "带真值点", "中心"], row)


VARIANTS = [("roi-a", "A 精简", roi_a, table_a), ("roi-b", "B 带来源", roi_b, table_b), ("roi-c", "C 按 patch 浏览", roi_c, table_c)]

CSS = """
.rp .roi-head { align-items: center; }
.rp .crumbs { margin: 0; font-size: 14px; width: 100%; }
.rp-grid { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 48px; margin-top: 24px; }
.rp-strips { position: sticky; top: 72px; align-self: start; }
.rp-strips .note { width: 0; min-width: 100%; }
.rp-info { max-width: 44em; }
.rp-info h2 { font-size: 17px; margin: 30px 0 8px; }
.rp-info .facts { margin-top: 0; }
.rp-info .locator { margin-top: 28px; max-width: 520px; }
.rp-info code { font-size: 13px; }
.grid rect.sel { fill: rgba(255,255,255,.35) !important; stroke: #fff !important; stroke-width: 3 !important; }
.pv svg { width: 100%; height: auto; display: block; background: #000; }
.pv circle { fill: none; stroke: #ffd24a; stroke-width: 3; }
.roi-c .grid rect { cursor: pointer; pointer-events: all; }
.roitable td.th { padding: 3px 6px; white-space: nowrap; }
.roitable td.th img { height: 64px; width: auto; margin-right: 2px; background: #000; }
.roitable code.pid { font-size: 12px; }
"""


def main():
    for key, label, page_fn, table_fn in VARIANTS:
        site = b.OUT / key
        if site.exists():
            shutil.rmtree(site)
        (site / "rois").mkdir(parents=True)
        shutil.copy(b.HERE / "a.css", site / "style.css")
        with open(site / "style.css", "a", encoding="utf-8") as f:
            f.write(CSS)
        pages = {"rois/index.html": ("ROI 总表", table_fn(), TABLE_JS)}
        for roi in PAGES:
            title, body, js = page_fn(next(r for r in b.ROIS if r["roi"] == roi))
            pages[f"rois/{roi}.html"] = (title, body, js)
        # 首页、数据来源沿用 a-atlas
        for rel, (title, body, js) in pages.items():
            doc = b.shell(key, rel, title, body, js, body_class=key)
            doc = doc.replace(f'href="../index.html"', 'href="../../a-atlas/index.html"').replace(
                'href="../sources.html"', 'href="../../a-atlas/sources.html"')
            up = "../" * (rel.count("/") + 1)
            links = "".join(f'<a href="{up}{k}/{rel}"{" aria-current=page" if k == key else ""}>{lb}</a>' for k, lb, _, _ in VARIANTS)
            i = [v[0] for v in VARIANTS].index(key)
            prev, nxt = VARIANTS[i - 1][0], VARIANTS[(i + 1) % len(VARIANTS)][0]
            bar = SWITCH.format(links=links, prev=f"{up}{prev}/{rel}", next=f"{up}{nxt}/{rel}")
            (site / rel).write_text(doc.replace("</body>", bar + "</body>"), encoding="utf-8")
        (site / "search-index.js").write_text("window.SEARCH=[];", encoding="utf-8")
    shutil.copytree(b.A / "patches", b.OUT / "assets/patches", dirs_exist_ok=True)
    (b.OUT / "roi-page.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>原型：ROI 页内容与版式</title>'
        '<body style="font:16px/1.8 system-ui,\'Microsoft YaHei\';max-width:44em;margin:3em auto;padding:0 1em">'
        '<h1>原型：ROI 页内容与版式</h1><p>三个内容方案，版式相同。页面底部的切换条在三者的同一页之间跳转，键盘 ← → 亦可。'
        '只做了 ROI_027（训练集）与 ROI_054（测试集）两页。</p><ul>'
        + "".join(f'<li>{lb}：<a href="{k}/rois/index.html">ROI 总表</a> · <a href="{k}/rois/ROI_054.html">ROI_054</a> · '
                  f'<a href="{k}/rois/ROI_027.html">ROI_027</a></li>' for k, lb, _, _ in VARIANTS) + "</ul>",
        encoding="utf-8")
    print("built", b.OUT / "roi-page.html")


SWITCH = """<div id="proto-bar"><span>原型</span>{links}</div>
<style>#proto-bar{{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);z-index:999;display:flex;gap:6px;align-items:center;
background:#000;color:#fff;border-radius:999px;padding:5px 8px 5px 14px;font:13px/1.2 system-ui,"Microsoft YaHei";box-shadow:0 6px 20px rgba(0,0,0,.35)}}
#proto-bar span{{opacity:.6;margin-right:4px}}#proto-bar a{{color:#fff;text-decoration:none;padding:4px 10px;border-radius:999px}}
#proto-bar a[aria-current]{{background:#fff;color:#000}}</style>
<script>document.addEventListener('keydown',function(e){{var t=document.activeElement;if(t&&(t.tagName==='INPUT'||t.isContentEditable))return;
if(e.key==='ArrowLeft')location.href='{prev}';if(e.key==='ArrowRight')location.href='{next}';}});</script>"""


if __name__ == "__main__":
    main()
