"""PROTOTYPE（一次性）：「原型：文档站的视觉设计」的两个设计方向。

  out/a-atlas/   A 月面图集：地图优先
  out/b-plates/  B 配对图版：图优先
  out/assets/    两者共用的图、字体、数据、交互脚本

素材先由 prep_assets.py 生成（要读数据盘）。本脚本只读仓库，需要 markdown 库。
用法：python build.py
"""

from __future__ import annotations

import csv
import html
import json
import re
import shutil
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
A = HERE / "assets"
OUT = HERE / "out"
TITLE = "月球光学–SAR 配准数据集"

ROIS = json.loads((A / "rois.json").read_text(encoding="utf-8"))
SAMPLES = json.loads((A / "samples.json").read_text(encoding="utf-8"))
GRIDS = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (A / "grids").glob("*.json")}
BANDS = json.loads((A / "bands/bands.json").read_text(encoding="utf-8"))
SPLITS = [("Train", "训练集"), ("Val", "验证集"), ("Test", "测试集")]
TRUTH_POINTS = {"Val": 5289, "Test": 7742}


def split_totals():
    out = []
    for key, zh in SPLITS:
        rs = [r for r in ROIS if r["split"] == key]
        out.append(dict(key=key, zh=zh, rois=len(rs), patches=sum(r["patches"] for r in rs),
                        truth=sum(r["truth_patches"] or 0 for r in rs) or None, points=TRUTH_POINTS.get(key)))
    return out


def n(x):
    return "—" if x is None else f"{x:,}".replace(",", " ") if x >= 10000 else str(x)


def lat(y):
    return f"{abs(y):.1f}°{'S' if y < 0 else 'N'}"


def lon(x):
    return f"{abs(x):.1f}°{'W' if x < 0 else 'E'}"


# ---------------- 共用内容 ----------------

INTRO = ("嫦娥二号 CCD 相机 7 m 正射影像与 LRO Mini-RF S 波段 SAR 的配准数据集。"
         "67 个 ROI 分布在月球正面与背面，切成 9862 对 512 × 512 的 patch，按 ROI 分为训练集、验证集、测试集；"
         "验证集与测试集的 patch 带评测真值点。")

BANDS_FIG = """<figure class="bands">
<div class="band-row">
<div><img src="{a}bands/b1.png" alt=""><p>波段 1<br>H 接收功率</p></div>
<div><img src="{a}bands/b2.png" alt=""><p>波段 2<br>V 接收功率</p></div>
<div><img src="{a}bands/b3.png" alt=""><p>波段 3<br>交叉功率实部</p></div>
<div><img src="{a}bands/b4.png" alt=""><p>波段 4<br>交叉功率虚部</p></div>
<div class="derived"><img src="{a}bands/s1.png" alt=""><p>S1 总功率<br>（dB）</p></div>
<div class="derived"><img src="{a}bands/cpr.png" alt=""><p>CPR<br>圆极化比</p></div>
</div>
<figcaption>{cap}</figcaption>
</figure>"""


def bands_caption(prefix=""):
    s = BANDS["stats"]
    return (f"{prefix}{BANDS['roi']} 第 {BANDS['patch']} 对 patch 的 SAR。各图按 2%–98% 分位拉伸。"
            f"波段 3 的取值范围 {s['b3'][0]:.3f} 至 {s['b3'][1]:.3f}，波段 4 为 {s['b4'][0]:.3f} 至 {s['b4'][1]:.3f}；"
            f"CPR 为 {s['cpr'][0]:.2f} 至 {s['cpr'][1]:.2f}。")


def sources_html(assets, caption_prefix=""):
    text = (HERE / "sources.md").read_text(encoding="utf-8")
    conv = markdown.Markdown(extensions=["tables", "fenced_code", "toc"], extension_configs={"toc": {"toc_depth": "2-3"}})
    body = conv.convert(text)
    body = re.sub(r'href="([^":]+)\.md(#[^"]*)?"', r'href="\1.html\2"', body)
    body = re.sub(r"<h1[^>]*>.*?</h1>\n?", "", body, count=1)
    fig = BANDS_FIG.format(a=assets, cap=html.escape(bands_caption(caption_prefix)))
    body = body.replace("<p>波段 3、4 可为负值。</p>", "<p>波段 3、4 可为负值。</p>\n" + fig)
    toc = []

    def walk(tokens):
        for t in tokens:
            if t["level"] in (2, 3):
                toc.append((t["level"], t["id"], t["name"]))
            walk(t["children"])

    walk(conv.toc_tokens)
    return body, toc


def data_js():
    return ("window.ROIS=" + json.dumps(ROIS, ensure_ascii=False) + ";\nwindow.SAMPLES=" + json.dumps(SAMPLES)
            + ";\nwindow.GRIDS=" + json.dumps(GRIDS) + ";\n")


def roi_facts(r):
    w, s, e, nn = r["bbox"]
    split_dir = r["split"]
    return [
        ("patch 对", str(r["patches"])),
        ("带评测真值点的 patch", n(r["truth_patches"]) if r["truth_patches"] else "无（训练集不带真值点）"),
        ("中心", f"{lat(r['center'][1])}，{lon(r['center'][0])}"),
        ("范围", f"{lat(s)}–{lat(nn)}，{lon(w)}–{lon(e)}"),
        ("Mini-RF 产品", f"<code>{r['product_id']}</code>"),
        ("成像时刻（UTC）", r["time"].replace("T", " ")),
        ("入射角", f"{r['incidence']:.2f}°"),
        ("视向", {"LEFT": "左视", "RIGHT": "右视"}[r["look"]]),
        ("条带尺寸", f"{r['width_px']:,} × {r['length_px']:,} 像素"),
        ("产物目录", f"<code>Processed_Data/{split_dir}/{r['roi']}/</code>"),
        ("对齐控制点", f"<code>data/tie-points/{r['raw']}/</code>"),
    ]


FACTS = json.loads((A / "roi-facts.json").read_text(encoding="utf-8"))
MINIRF = {}
with open(REPO / "data/metadata/minirf_metadata.csv", encoding="utf-8-sig") as _f:
    for _row in csv.DictReader(_f):
        MINIRF[f"ROI_{int(_row['ROI'].split('_')[1]):03d}"] = _row


def roi_side(r):
    """「原型：ROI 页内容与版式」：数据集一组 + 光学/SAR 对照表。"""
    f, m = FACTS[r["roi"]], MINIRF[r["roi"]]
    w, s, e, nn = r["bbox"]
    ds = [("划分", f'<span class="sw {r["split"]}"></span>{r["split_zh"]}'), ("patch 对", str(r["patches"]))]
    if f["missing"]:
        ds.append(("patch 编号", f"0–{f['last_id']}，缺 {'、'.join(map(str, f['missing']))}"))
    if r["truth_patches"]:
        ds.append(("带评测真值点的 patch", f"{r['truth_patches']}，共 {f['truth_points']} 对点"))
    ds += [("中心", f"{lat(r['center'][1])}，{lon(r['center'][0])}"),
           ("范围", f"{lat(s)}–{lat(nn)}，{lon(w)}–{lon(e)}"),
           ("对齐控制点", f'{f["tie_points"]} 对（<a href="#">标注规程</a>）')]
    fr = f["frames"]
    opt_id = "<br>".join(f"<code>{x['id']}</code>" for x in fr)
    projs = sorted({x["proj"] for x in fr})
    opt_proj = projs[0] if len(projs) == 1 else "<br>".join(f"{x['id'].split('_')[4]}：{x['proj']}" for x in fr)
    rows = [("产品", opt_id, f"<code>{m['PRODUCT_ID']}</code>"),
            ("成像时刻（UTC）", "—", m["成像时刻UTC"].replace("T", " ")),
            ("投影", opt_proj, "等距圆柱，中心经度 180°"),
            ("像元", "7 m", f"{float(m['原生采样_m']):.4f} m"),
            ("入射角", "—", f"{float(m['入射角_deg']):.2f}°"),
            ("视向", "—", {"LEFT": "左视", "RIGHT": "右视"}[m["视向"]]),
            ("条带尺寸", "—", f"{int(m['条带宽_px']):,} × {int(m['条带长_px']):,} 像素")]
    cmp = "".join(f'<tr><th scope="row">{k}</th><td>{o}</td><td>{sv}</td></tr>' for k, o, sv in rows)
    return ('<dl class="facts">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in ds) + "</dl>"
            f'<table class="cmp"><thead><tr><th></th><th>光学 CE-2 DOM</th><th>SAR Mini-RF</th></tr></thead><tbody>{cmp}</tbody></table>')


def neighbours(r):
    i = ROIS.index(r)
    return ROIS[i - 1], ROIS[(i + 1) % len(ROIS)]


# ---------------- 页面外壳 ----------------

NAV = [("首页", "index.html"), ("数据来源", "sources.html"), ("ROI 总表", "rois/index.html")]


def shell(variant, rel, title, body, script="", body_class=""):
    root = "../" * rel.count("/")
    a = root + "../assets/"
    here = "rois/index.html" if rel.startswith("rois/") else rel
    nav = "".join(f'<a href="{root}{href}"{" aria-current=page" if here == href else ""}>{name}</a>' for name, href in NAV)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}{"" if title == TITLE else " – " + TITLE}</title>
<link rel="stylesheet" href="{root}style.css">
</head>
<body class="{body_class}" data-root="{root}">
<header class="top"><a class="site" href="{root}index.html">{TITLE}</a>
<nav>{nav}</nav>
<div class="find"><input id="q" type="search" placeholder="搜索文档" aria-label="搜索文档" autocomplete="off"><div id="hits" hidden></div></div>
</header>
<main>{body}</main>
<script src="{a}data.js"></script>
<script src="{root}search-index.js"></script>
<script src="{a}site.js"></script>
<script>{script}</script>
</body></html>"""


# ---------------- A 月面图集 ----------------

def a_pages():
    pages = {}
    tot = split_totals()
    rows = "".join(
        f'<tr><th scope="row"><span class="sw {t["key"]}"></span>{t["zh"]}</th><td>{t["rois"]}</td><td>{n(t["patches"])}</td>'
        f'<td>{n(t["truth"])}</td><td>{n(t["points"])}</td></tr>' for t in tot)
    pages["index.html"] = (TITLE, f"""
<section class="hero-map" aria-label="ROI 分布">
  <div id="heromap"></div>
</section>
<p class="map-note wrap">LRO LROC 全月拼图，等距圆柱投影，经度 180°W–180°E。条带是各 ROI 的对齐影像范围，点击进入该 ROI。</p>
<section class="intro wrap">
  <div class="intro-text">
    <h1>{TITLE}</h1>
    <p>{INTRO}</p>
    <p class="more"><a href="sources.html">数据来源</a><a href="rois/index.html">ROI 总表</a></p>
  </div>
  <table class="splits">
    <thead><tr><th></th><th>ROI</th><th>patch 对</th><th>带真值点的 patch 对</th><th>评测真值点对</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>
<section class="samples wrap">
  <h2>样例</h2>
  <p class="lede">每组左为 CE-2 光学，右为 Mini-RF SAR 总功率（dB），同为 512 × 512 像素、7.5 m。圆点是评测真值点，指向一个点，另一侧的对应点随之放大。</p>
  <div id="pairs" class="pairs"></div>
</section>""", """
Site.moonMap(document.getElementById('heromap'), {mode:'strips', graticule:true, labels:true});
var box = document.getElementById('pairs');
SAMPLES.slice(0, 6).forEach(function (s) {
  var f = Site.h('figure', 'sample', box);
  Site.pairFigure(f, s, {gap: 10});
  Site.h('figcaption', null, f, '<a href="rois/' + s.roi + '.html">' + s.roi + '</a>，' + ({Val:'验证集',Test:'测试集'})[s.split] + '，patch_' + s.patch + '，' + s.points.length + ' 对真值点');
});""")

    body, toc = sources_html("../assets/")
    toc_html = "".join(f'<a class="l{l}" href="#{i}">{html.escape(t)}</a>' for l, i, t in toc)
    pages["sources.html"] = ("数据来源", f"""
<div class="doc wrap">
  <article class="prose"><h1>数据来源</h1>{body}</article>
  <nav class="toc" aria-label="本页目录">{toc_html}</nav>
</div>""", "")

    filters = '<button type="button" data-f="" aria-pressed="true">全部 67</button>' + "".join(
        f'<button type="button" data-f="{t["key"]}" aria-pressed="false"><span class="sw {t["key"]}"></span>{t["zh"]} {t["rois"]}</button>' for t in tot)
    trs = "".join(
        f'<tr data-roi="{r["roi"]}" data-split="{r["split"]}"><th scope="row"><a href="{r["roi"]}.html">{r["roi"]}</a></th>'
        f'<td><span class="sw {r["split"]}"></span>{r["split_zh"]}</td><td class="num">{r["patches"]}</td><td class="num">{n(r["truth_patches"])}</td>'
        f'<td>{lat(r["center"][1])}，{lon(r["center"][0])}</td><td class="num">{r["incidence"]:.1f}°</td><td>{"左" if r["look"] == "LEFT" else "右"}</td>'
        f'<td class="issues">{"；".join(r["issues"])}</td></tr>' for r in ROIS)
    pages["rois/index.html"] = ("ROI 总表", f"""
<div class="wrap"><h1>ROI 总表</h1><div class="filters" role="group" aria-label="按划分筛选">{filters}</div></div>
<div class="wrap"><div id="map" class="map-mid"></div></div>
<div class="wrap"><table class="roitable">
<thead><tr><th>ROI</th><th>划分</th><th>patch 对</th><th>带真值点</th><th>中心</th><th>入射角</th><th>视向</th><th>已知问题</th></tr></thead>
<tbody>{trs}</tbody></table></div>""", """
var rows = {}; document.querySelectorAll('tr[data-roi]').forEach(function (tr) { rows[tr.dataset.roi] = tr; });
var m = Site.moonMap(document.getElementById('map'), {mode:'strips', graticule:true, onHover: function (id) {
  for (var k in rows) rows[k].classList.toggle('hl', k === id);
}});
Object.keys(rows).forEach(function (k) {
  rows[k].addEventListener('mouseenter', function () { m.highlight(k); });
  rows[k].addEventListener('mouseleave', function () { m.highlight(null); });
});
document.querySelectorAll('.filters button').forEach(function (b) {
  b.addEventListener('click', function () {
    document.querySelectorAll('.filters button').forEach(function (x) { x.setAttribute('aria-pressed', x === b); });
    m.filter(b.dataset.f);
    for (var k in rows) rows[k].hidden = !!b.dataset.f && rows[k].dataset.split !== b.dataset.f;
  });
});""")

    for r in ROIS:
        prev, nxt = neighbours(r)
        facts = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in roi_facts(r))
        issues = "".join(f"<li>{html.escape(i)}</li>" for i in r["issues"]) or "<li>无</li>"
        grid_note = ("<p class=\"note\">网格是各 patch 的 SAR 范围；"
                     f'<span class="sw-t {r["split"]}"></span>着色的格子带评测真值点。</p>') if r["roi"] in GRIDS else ""
        pages[f"rois/{r['roi']}.html"] = (r["roi"], f"""
<div class="wrap roi">
  <header class="roi-head">
    <h1>{r['roi']}</h1>
    <p class="split-tag"><span class="sw {r['split']}"></span>{r['split_zh']}</p>
    <nav class="stepper" aria-label="相邻 ROI"><a href="{prev['roi']}.html">上一个 {prev['roi']}</a><a href="{nxt['roi']}.html">下一个 {nxt['roi']}</a></nav>
  </header>
  <div class="roi-grid">
    <div class="roi-side">
      <div id="loc" class="locator"></div>
      {roi_side(r)}
    </div>
    <div class="roi-main {r['split']}"><div id="strips"></div>{grid_note}
    <p class="note">对齐影像的缩略图，每 114 × 114 像素取有效值的均值。黑色是没有数据的区域。</p></div>
  </div>
</div>""", f"""
Site.moonMap(document.getElementById('loc'), {{mode:'strips', focus:'{r['roi']}'}});
Site.stripFigure(document.getElementById('strips'), '{r['roi']}', ['optical','sar']);""")
    return pages


# ---------------- B 配对图版 ----------------

def b_pages():
    pages = {}
    tot = split_totals()
    lines = "".join(
        f'<tr><th scope="row"><span class="sw {t["key"]}"></span>{t["zh"]}</th><td>{t["rois"]}</td><td>{n(t["patches"])}</td>'
        f'<td>{n(t["truth"])}</td><td>{n(t["points"])}</td></tr>' for t in tot)
    pages["index.html"] = (TITLE, f"""
<section class="hero">
  <div class="plate"><div id="hero"></div></div>
  <div class="hero-foot">
    <p class="caption" id="cap"></p>
    <div class="film" id="film" role="group" aria-label="选择样例"></div>
  </div>
</section>
<section class="col">
  <h1>{TITLE}</h1>
  <p class="lead">{INTRO}</p>
  <table class="splits"><thead><tr><th></th><th>ROI</th><th>patch 对</th><th>带真值点的 patch 对</th><th>评测真值点对</th></tr></thead><tbody>{lines}</tbody></table>
  <p class="more"><a href="sources.html">数据来源</a>　<a href="rois/index.html">ROI 总表</a></p>
</section>
<figure class="fig wide">
  <div class="plate"><div id="map"></div></div>
  <figcaption><b>图 2</b>　67 个 ROI 在月面的位置。底图为 LRO LROC 全月拼图，等距圆柱投影。圆点面积与该 ROI 的 patch 对数成正比，
  颜色表示划分：<span class="sw Train"></span>训练集　<span class="sw Val"></span>验证集　<span class="sw Test"></span>测试集。点击圆点进入该 ROI。</figcaption>
</figure>""", """
var hero = document.getElementById('hero'), cap = document.getElementById('cap'), film = document.getElementById('film');
var ZH = {Val:'验证集', Test:'测试集'};
function show(i) {
  var s = SAMPLES[i];
  hero.innerHTML = '';
  Site.pairFigure(hero, s, {gap: 64, lines: true});
  cap.innerHTML = '<b>图 1</b>　<a href="rois/' + s.roi + '.html">' + s.roi + '</a>（' + ZH[s.split] + '）第 ' + s.patch + ' 对 patch。' +
    '左为 CE-2 光学，右为 Mini-RF SAR 总功率（dB），各 512 × 512 像素。连线是 ' + s.points.length + ' 对评测真值点。' +
    '这对 patch 的光学范围相对 SAR 偏移 ' + Math.abs(s.offset_m[0]) + ' m（东西）、' + Math.abs(s.offset_m[1]) + ' m（南北）。';
  film.querySelectorAll('button').forEach(function (b, j) { b.setAttribute('aria-pressed', i === j); });
}
SAMPLES.forEach(function (s, i) {
  var b = Site.h('button', null, film, '<img src="../assets/samples/' + s.name + '_opt.png" alt=""><img src="../assets/samples/' + s.name + '_sar.png" alt="">');
  b.type = 'button'; b.title = s.roi + ' patch_' + s.patch;
  b.setAttribute('aria-label', s.roi + ' 第 ' + s.patch + ' 对');
  b.addEventListener('click', function () { show(i); });
});
show(1);
Site.moonMap(document.getElementById('map'), {mode:'dots'});""")

    body, toc = sources_html("../assets/", caption_prefix="")
    body = body.replace("<figcaption>", "<figcaption><b>图 3</b>　", 1)
    toc_html = "".join(f'<a class="l{l}" href="#{i}">{html.escape(t)}</a>' for l, i, t in toc)
    pages["sources.html"] = ("数据来源", f"""
<div class="col doc"><h1>数据来源</h1><nav class="toc-inline" aria-label="本页目录">{toc_html}</nav>{body}</div>""", "")

    sections = []
    for key, zh in reversed(SPLITS):
        t = next(x for x in tot if x["key"] == key)
        tiles = "".join(
            f'<a class="tile" href="{r["roi"]}.html"><span class="sl"><img src="../../assets/thumbs/{r["roi"]}_optical.png" alt="" loading="lazy">'
            f'<img src="../../assets/thumbs/{r["roi"]}_sar.png" alt="" loading="lazy"></span><b>{r["roi"][4:]}</b><small>{r["patches"]}</small></a>'
            for r in ROIS if r["split"] == key)
        sections.append(f'<section class="wall-sec"><h2><span class="sw {key}"></span>{zh}</h2>'
                        f'<p class="meta">{t["rois"]} 个 ROI，{n(t["patches"])} 对 patch</p><div class="wall">{tiles}</div></section>')
    trs = "".join(
        f'<tr><th scope="row"><a href="{r["roi"]}.html">{r["roi"]}</a></th><td><span class="sw {r["split"]}"></span>{r["split_zh"]}</td>'
        f'<td class="num">{r["patches"]}</td><td class="num">{n(r["truth_patches"])}</td><td>{lat(r["center"][1])}，{lon(r["center"][0])}</td>'
        f'<td class="num">{r["incidence"]:.1f}°</td><td class="issues">{"；".join(r["issues"])}</td></tr>' for r in ROIS)
    pages["rois/index.html"] = ("ROI 总表", f"""
<div class="col"><h1>ROI 总表</h1><p class="lead">每个 ROI 一对缩略图，左为光学，右为 SAR，数字是 patch 对数。条带是南北向的长条，宽几十公里，长数百公里。</p></div>
<div class="plate walls">{''.join(sections)}</div>
<div class="col wide-table"><h2>表 1　全部 ROI</h2><table class="roitable">
<thead><tr><th>ROI</th><th>划分</th><th>patch 对</th><th>带真值点</th><th>中心</th><th>入射角</th><th>已知问题</th></tr></thead><tbody>{trs}</tbody></table></div>""", "")

    for r in ROIS:
        prev, nxt = neighbours(r)
        facts = "".join(f"<tr><th scope=\"row\">{k}</th><td>{v}</td></tr>" for k, v in roi_facts(r))
        issues = "".join(f"<li>{html.escape(i)}</li>" for i in r["issues"]) or "<li>无</li>"
        grid_note = "网格是各 patch 的 SAR 范围，着色的格子带评测真值点。" if r["roi"] in GRIDS else ""
        pages[f"rois/{r['roi']}.html"] = (r["roi"], f"""
<div class="spine-layout">
  <aside class="spine plate {r['split']}"><div id="strips"></div><p class="spine-cap">对齐影像缩略图。{grid_note}黑色是没有数据的区域。</p></aside>
  <article class="spine-text">
    <p class="crumbs"><a href="index.html">ROI 总表</a></p>
    <h1>{r['roi']}</h1>
    <p class="split-line"><span class="sw {r['split']}"></span>{r['split_zh']}</p>
    <table class="facts">{facts}</table>
    <h2>已知问题</h2><ul>{issues}</ul>
    <figure class="fig"><div class="plate"><div id="loc"></div></div><figcaption>{r['roi']} 在月面的位置（{lat(r['center'][1])}，{lon(r['center'][0])}）。</figcaption></figure>
    <nav class="stepper" aria-label="相邻 ROI"><a href="{prev['roi']}.html">上一个 {prev['roi']}</a><a href="{nxt['roi']}.html">下一个 {nxt['roi']}</a></nav>
  </article>
</div>""", f"""
Site.stripFigure(document.getElementById('strips'), '{r['roi']}', ['optical','sar']);
Site.moonMap(document.getElementById('loc'), {{mode:'dots', focus:'{r['roi']}'}});""", )
    return pages


# ---------------- 输出 ----------------

SWITCH = """<div id="proto-bar"><span>原型</span>{links}</div>
<style>#proto-bar{{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);z-index:999;display:flex;gap:6px;align-items:center;
background:#000;color:#fff;border-radius:999px;padding:5px 8px 5px 14px;font:13px/1.2 system-ui,"Microsoft YaHei";box-shadow:0 6px 20px rgba(0,0,0,.35)}}
#proto-bar span{{opacity:.6;margin-right:4px}}#proto-bar a{{color:#fff;text-decoration:none;padding:4px 10px;border-radius:999px}}
#proto-bar a[aria-current]{{background:#fff;color:#000}}</style>
<script>document.addEventListener('keydown',function(e){{var t=document.activeElement;if(t&&(t.tagName==='INPUT'||t.isContentEditable))return;
if(e.key==='ArrowLeft'||e.key==='ArrowRight')location.href='{other}';}});</script>"""

VARIANTS = [("a-atlas", "A 月面图集", a_pages), ("b-plates", "B 配对图版", b_pages)]


def write_variant(key, pages):
    site = OUT / key
    shutil.copy(HERE / f"{key[0]}.css", site / "style.css")
    index = []
    for rel, (title, body, script) in pages.items():
        doc = shell(key, rel, title, body, script, body_class="home" if rel == "index.html" else "")
        up = "../" * (rel.count("/") + 1)
        other = next(k for k, _, _ in VARIANTS if k != key)
        links = "".join(f'<a href="{up}{k}/{rel}"{" aria-current=page" if k == key else ""}>{label}</a>' for k, label, _ in VARIANTS)
        doc = doc.replace("</body>", SWITCH.format(links=links, other=f"{up}{other}/{rel}") + "</body>")
        p = site / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(doc, encoding="utf-8")
        text = re.sub(r"<script.*?</script>|<[^>]+>", " ", body, flags=re.S)
        index.append({"url": rel, "title": title, "text": re.sub(r"\s+", " ", html.unescape(text)).strip()})
    (site / "search-index.js").write_text("window.SEARCH=" + json.dumps(index, ensure_ascii=False) + ";", encoding="utf-8")


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    shared = OUT / "assets"
    for sub in ("fonts", "samples", "bands"):
        shutil.copytree(A / sub, shared / sub)
    shutil.copy(A / "moon-2k.jpg", shared)
    shutil.copytree(REPO / "docs/rois/thumbnails", shared / "thumbs")
    shutil.copy(HERE / "site.js", shared)
    (shared / "data.js").write_text(data_js(), encoding="utf-8")
    for key, _, make in VARIANTS:
        (OUT / key).mkdir(parents=True)
        write_variant(key, make())
    (OUT / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>原型：文档站的视觉设计</title>'
        '<body style="font:16px/1.8 system-ui,\'Microsoft YaHei\';max-width:40em;margin:3em auto;padding:0 1em">'
        '<h1>原型：文档站的视觉设计</h1><p>两个设计方向，内容相同。页面底部的切换条在两者的同一页之间跳转，键盘 ← → 亦可。</p>'
        '<ul><li><a href="a-atlas/index.html">A 月面图集</a>：地图优先</li><li><a href="b-plates/index.html">B 配对图版</a>：图优先</li></ul>',
        encoding="utf-8")
    print("built", OUT / "index.html")


if __name__ == "__main__":
    main()
