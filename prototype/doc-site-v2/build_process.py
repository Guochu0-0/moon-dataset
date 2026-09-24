"""PROTOTYPE（一次性）：流程篇的三个方案，挂在 A 月面图集站点上。

  out/a-atlas/process.html?variant=A   横幅流程图：深色通栏，节点里嵌真实影像；正文配真实影像
  out/a-atlas/process.html?variant=B   竖向线路图兼目录：左侧固定，随滚动高亮；正文配抽象示意
  out/a-atlas/process.html?variant=C   数据形态主线：节点画数据形态，箭头标操作；第二步配可逐步点开的真实影像

先跑 prep_process_assets.py 生成 assets/process/。本脚本先调用 build.py 重建整站，再写流程篇。
用法：python build_process.py
"""

from __future__ import annotations

import html
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402

build.NAV.insert(1, ("流程", "process.html"))
FIG = json.loads((HERE / "assets/process/roi054.json").read_text(encoding="utf-8"))

# ---------------- 内容（三个方案共用） ----------------

PROTOCOL = """<table>
<thead><tr><th>项目</th><th>做法</th></tr></thead>
<tbody>
<tr><td>软件</td><td>ENVI</td></tr>
<tr><td>标注影像</td><td>重叠区影像（光学与 SAR 已重采样到同一网格）</td></tr>
<tr><td>数量</td><td>每个 ROI 约 30 对；最早标的几个 ROI 较多（最多 150 对），个别难标的 ROI 较少（最少 19 对）</td></tr>
<tr><td>分布</td><td>沿条带从上到下尽量均匀覆盖</td></tr>
<tr><td>选点</td><td>在两幅影像中找到对应的小陨石坑，取坑中心；坑越小，定位的相对误差越小</td></tr>
</tbody></table>"""

ROI073 = ("ROI_073 的控制点最初误标在 ROI_074 的影像上，2026-09-11 重标为 30 对。"
          "该 ROI 在训练集，按重标后的控制点重新切片、重新编号，现有 119 对 patch。")

STEPS = [
    {
        "id": "overlap", "no": "第一步", "name": "重叠区提取", "script": "scripts/01_overlap.py",
        "inputs": [("CE-2 DOM", "7 m 正射影像分幅，一个 ROI 可跨多幅", "sources.html"),
                   ("Mini-RF SAR", "S 波段条带", "sources.html")],
        "proc": ["求光学与 SAR 的公共覆盖区。",
                 "把两者统一到同一坐标系和像素网格，cubic 重采样到 7.5 m。"],
        "outputs": [("重叠区影像", "<code>opt.tif</code>、<code>sar.tif</code>，同一网格、同一尺寸",
                     "work/01_overlap/ROI_xxx/")],
    },
    {
        "id": "tiepoints", "no": "人工步骤", "name": "标控制点", "script": None,
        "inputs": [("重叠区影像", "第一步的输出", None)],
        "proc": None,
        "outputs": [("控制点", "每行一对：光学 x、y，SAR x、y，单位为重叠区影像像素", "data/tie-points/ROI_xxx.pts")],
    },
    {
        "id": "patches", "no": "第二步", "name": "协同切片", "script": "scripts/02_patches.py",
        "inputs": [("重叠区影像", "第一步的输出", None), ("控制点", "人工步骤的输出", None)],
        "proc": ["由全部控制点最小二乘解算光学到 SAR 的全局仿射。",
                 "在光学上按 512 × 512、步长 512 滑窗，边缘余量丢弃。",
                 "窗口四角经仿射映射到 SAR，确定 SAR 窗口。",
                 "剔除出界、重叠比低于 70%、含 nodata（0）的窗口。",
                 "按先行后列编号，从 <code>patch_0</code> 起。",
                 "切片，写出光学与 SAR patch。"],
        "outputs": [("patch 对", "<code>Optical/</code>、<code>SAR/</code>，512 × 512，同号即配对",
                     "work/02_patches/{Train,Val,Test}/ROI_xxx/"),
                    ("仿射矩阵与窗口列表", "JSON，供检查", "work/02_patches/…")],
    },
]
SUBSTEPS = ["解算仿射", "滑窗", "映射", "剔除", "编号", "切片"]


def io_list(items):
    out = []
    for name, desc, target in items:
        label = f'<a href="{target}">{name}</a>' if target and target.endswith(".html") else name
        path = f'<code class="path">{target}</code>' if target and not target.endswith(".html") else ""
        out.append(f'<li><b>{label}</b><span>{desc}</span>{path}</li>')
    return '<ul class="io">' + "".join(out) + "</ul>"


def proc_block(s):
    if s["proc"] is None:
        return PROTOCOL + f"<p>{ROI073}</p>"
    return "<ol class=proc>" + "".join(f"<li>{p}</li>" for p in s["proc"]) + "</ol>"


def head(s, tag="h2"):
    script = f'<code class="script">{s["script"]}</code>' if s["script"] else ""
    return f'<{tag} id="{s["id"]}"><span class="no">{s["no"]}</span>{s["name"]}</{tag}>{script}'


def section_three(s, fig):
    """输入 / 处理 / 输出 三小节。"""
    return f"""<section class="step">
{head(s)}
<h3>输入</h3>{io_list(s["inputs"])}
<h3>{"处理" if s["proc"] else "标注规程"}</h3>{proc_block(s)}
{fig}
<h3>输出</h3>{io_list(s["outputs"])}
</section>"""


def real_fig(layers, caption, interactive=False):
    btns = ""
    if interactive:
        btns = '<div class="stepbtns" role="group" aria-label="逐步查看">' + "".join(
            f'<button type="button" data-k="{i}" aria-pressed="{"true" if i == 0 else "false"}">{i + 1}　{n}</button>'
            for i, n in enumerate(SUBSTEPS[:5])) + "</div>"
    return f"""<figure class="realfig"{' data-interactive="1"' if interactive else ''} data-layers="{layers}">{btns}
<div class="pairwrap"></div><figcaption>{caption}</figcaption></figure>"""


# ---------------- 抽象示意（方案 B） ----------------

def abs_fig(kind):
    hatch = """<defs><pattern id="hx" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
<line x1="0" y1="0" x2="0" y2="6" stroke="#8C96A1" stroke-width="2"/></pattern></defs>"""
    if kind == "overlap":
        body = """
<g class="ab-l"><text x="20" y="24">CE-2 DOM 分幅与 Mini-RF 条带</text>
<rect x="20" y="36" width="200" height="120" class="opt"/><rect x="20" y="156" width="200" height="120" class="opt"/>
<line x1="20" y1="156" x2="220" y2="156" class="seam"/>
<polygon points="112,36 148,34 192,282 156,284" class="sar"/>
<rect x="109" y="36" width="90" height="240" class="common"/>
<text x="206" y="298" class="n">公共覆盖区</text></g>
<path d="M 330 160 h 50" class="arr"/><path d="M372 153 l 8 7 l -8 7" class="arrh"/>
<g class="ab-l"><text x="410" y="24">重叠区影像，7.5 m 同一网格</text>
<rect x="410" y="36" width="110" height="240" class="opt"/><rect x="540" y="36" width="110" height="240" class="blank"/>
<polygon points="552,36 600,36 638,276 590,276" class="sar"/>
<g class="px">""" + "".join(f'<line x1="{410 + i * 10}" y1="36" x2="{410 + i * 10}" y2="276"/>' for i in range(12)) + \
            "".join(f'<line x1="410" y1="{36 + i * 10}" x2="520" y2="{36 + i * 10}"/>' for i in range(25)) + "</g></g>"
        return f'<figure class="absfig"><svg viewBox="0 0 680 312">{hatch}{body}</svg><figcaption>示意：公共覆盖区上，两幅影像落到同一像素网格。</figcaption></figure>'
    if kind == "tiepoints":
        pts = [(40, 60, 38, 66), (80, 130, 84, 135), (30, 200, 36, 207), (90, 250, 95, 255)]
        dots = ""
        for i, (ax, ay, bx, by) in enumerate(pts, 1):
            dots += (f'<circle cx="{150 + ax}" cy="{ay}" r="9" class="crater"/><circle cx="{400 + bx}" cy="{by}" r="9" class="crater"/>'
                     f'<path d="M{150 + ax - 5} {ay}h10M{150 + ax} {ay - 5}v10" class="cross"/><path d="M{400 + bx - 5} {by}h10M{400 + bx} {by - 5}v10" class="cross"/>'
                     f'<line x1="{150 + ax + 12}" y1="{ay}" x2="{400 + bx - 12}" y2="{by}" class="tie"/>'
                     f'<text x="{150 + ax + 14}" y="{ay - 10}" class="n">{i}</text>')
        body = f"""<rect x="150" y="20" width="130" height="260" class="opt"/><rect x="400" y="20" width="130" height="260" class="sarr"/>
<text x="150" y="14">光学</text><text x="400" y="14">SAR</text>{dots}"""
        return f'<figure class="absfig"><svg viewBox="0 0 680 300">{body}</svg><figcaption>示意：两幅重叠区影像中的同一个小陨石坑，取坑中心为一对控制点。</figcaption></figure>'
    cells, sarc, k = "", "", 0
    for r in range(5):
        for c in range(3):
            x, y = 40 + c * 50, 30 + r * 50
            bad = (r, c) in {(0, 0), (4, 2), (2, 2)}
            cells += f'<rect x="{x}" y="{y}" width="50" height="50" class="{"rej" if bad else "win"}"/>'
            if not bad:
                cells += f'<text x="{x + 6}" y="{y + 16}" class="n">{k}</text>'
                k += 1
                sx, sy = 420 + c * 50 + r * 4, 38 + r * 50 - c * 3
                sarc += f'<polygon points="{sx},{sy} {sx + 50},{sy - 3} {sx + 54},{sy + 47} {sx + 4},{sy + 50}" class="win"/>'
    body = f"""{hatch}<text x="40" y="20">光学：512 × 512 滑窗</text><text x="420" y="20">SAR：经仿射映射的窗口</text>
<rect x="40" y="30" width="170" height="262" class="opt"/>{cells}
<path d="M 250 160 h 120" class="arr"/><path d="M362 153 l 8 7 l -8 7" class="arrh"/><text x="262" y="150">全局仿射</text>
{sarc}"""
    return f'<figure class="absfig"><svg viewBox="0 0 680 300">{body}</svg><figcaption>示意：斜线格为剔除的窗口；保留的窗口按先行后列编号，编号跳过剔除的格子。</figcaption></figure>'


# ---------------- 流程图 ----------------

def flow_a():
    """横向，深色通栏，节点里嵌真实影像。"""
    def thumb(href, x, y, w, h, cid):
        return (f'<clipPath id="{cid}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="2"/></clipPath>'
                f'<image href="../assets/process/{href}" x="{x}" y="{y}" width="{w}" height="{h}" '
                f'preserveAspectRatio="xMidYMid slice" clip-path="url(#{cid})"/>')
    grid = "".join(f'<rect x="{866 + c * 22}" y="{96 + r * 22}" width="22" height="22" class="g"/>' for r in range(4) for c in range(3))
    return f"""<nav class="flowA" aria-label="流程图"><svg viewBox="0 0 1180 300" role="img">
<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#fff"/></marker></defs>
<a href="sources.html"><g class="in"><rect x="10" y="70" width="150" height="58" rx="4"/><text x="24" y="96">CE-2 DOM</text><text x="24" y="116" class="s">7 m 正射影像</text></g></a>
<a href="sources.html"><g class="in"><rect x="10" y="170" width="150" height="58" rx="4"/><text x="24" y="196">Mini-RF SAR</text><text x="24" y="216" class="s">S 波段条带</text></g></a>
<path d="M160 99 C 200 99, 200 150, 236 150" class="e" marker-end="url(#ah)"/><path d="M160 199 C 200 199, 200 150, 236 150" class="e" marker-end="url(#ah)"/>
<a href="#overlap"><g class="node"><rect x="240" y="40" width="220" height="220" rx="6"/>
<text x="256" y="68" class="k">第一步</text><text x="256" y="92">重叠区提取</text>
{thumb("opt.png", 256, 110, 90, 130, "ca")}{thumb("sar.png", 354, 110, 90, 130, "cb")}</g></a>
<path d="M460 150 H 536" class="e" marker-end="url(#ah)"/><text x="498" y="140" class="lab" text-anchor="middle">重叠区影像</text>
<a href="#tiepoints"><g class="node manual"><rect x="540" y="40" width="220" height="220" rx="6"/>
<text x="556" y="68" class="k">人工</text><text x="556" y="92">标控制点</text>
{thumb("opt.png", 556, 110, 90, 130, "cc")}{thumb("sar.png", 654, 110, 90, 130, "cd")}
<g class="cp"><circle cx="590" cy="150" r="6"/><circle cx="690" cy="156" r="6"/><circle cx="578" cy="205" r="6"/><circle cx="680" cy="211" r="6"/></g></g></a>
<path d="M760 150 H 836" class="e" marker-end="url(#ah)"/><text x="798" y="140" class="lab" text-anchor="middle">控制点</text>
<path d="M350 40 C 350 4, 950 4, 950 36" class="e dim" marker-end="url(#ah)"/><text x="650" y="16" class="lab" text-anchor="middle">重叠区影像</text>
<a href="#patches"><g class="node"><rect x="840" y="40" width="220" height="220" rx="6"/>
<text x="856" y="68" class="k">第二步</text><text x="856" y="92">协同切片</text>
{thumb("opt.png", 866, 96, 66, 88, "ce")}{grid}
<g class="subs">""" + "".join(f'<text x="946" y="{112 + i * 22}">{i + 1} {n}</text>' for i, n in enumerate(SUBSTEPS)) + """</g></g></a>
<path d="M1060 150 H 1096" class="e" marker-end="url(#ah)"/>
<a href="#products"><g class="out"><rect x="1100" y="104" width="44" height="44" class="t1"/><rect x="1110" y="114" width="44" height="44" class="t2"/><rect x="1120" y="124" width="44" height="44" class="t3"/>
<text x="1100" y="196">patch 对</text></g></a>
</svg></nav>"""


def flow_b():
    """竖向线路图，左侧固定，兼作目录。"""
    items = []
    items.append('<li class="st in"><a href="sources.html"><b>CE-2 DOM、Mini-RF SAR</b><small>数据来源</small></a></li>')
    for s in STEPS:
        subs = ""
        if s["id"] == "patches":
            subs = '<ol class="subs">' + "".join(f"<li>{n}</li>" for n in SUBSTEPS) + "</ol>"
        cls = "st manual" if s["script"] is None else "st"
        sc = f'<small><code>{s["script"]}</code></small>' if s["script"] else "<small>人工，ENVI</small>"
        items.append(f'<li class="{cls}" data-for="{s["id"]}"><a href="#{s["id"]}"><span class="k">{s["no"]}</span><b>{s["name"]}</b>{sc}</a>{subs}</li>')
        out = s["outputs"][0][0]
        items.append(f'<li class="data">{out}</li>')
    items.append('<li class="st in"><a href="#products"><b>数据集</b><small>产物</small></a></li>')
    return '<nav class="flowB" aria-label="流程图"><ol>' + "".join(items) + "</ol></nav>"


def flow_c():
    """节点画数据形态，箭头标操作。"""
    def cap(x, t, s):
        return f'<text x="{x}" y="232" class="t">{t}</text><text x="{x}" y="252" class="s">{s}</text>'
    tiles = ('<rect x="20" y="70" width="60" height="60" class="opt"/><rect x="20" y="130" width="60" height="60" class="opt"/>'
             '<polygon points="100,62 124,58 150,196 126,200" class="sar"/>')
    pair = '<rect x="330" y="60" width="44" height="140" class="opt"/><rect x="384" y="60" width="44" height="140" class="blank"/><polygon points="392,60 414,60 424,200 402,200" class="sar"/>'
    cps = pair.replace('x="330"', 'x="630"').replace('x="384"', 'x="684"').replace("392,60 414,60 424,200 402,200", "692,60 714,60 724,200 702,200")
    cps += "".join(f'<path d="M{x - 5} {y}h10M{x} {y - 5}v10" class="cross"/>' for x, y in [(645, 80), (660, 130), (648, 180), (704, 82), (712, 132), (716, 182)])
    stacks = "".join(f'<rect x="{930 + i * 9}" y="{80 + i * 9}" width="56" height="56" class="{("opt" if i % 2 == 0 else "sarp")}"/>' for i in range(6))
    return f"""<nav class="flowC" aria-label="流程图"><svg viewBox="0 0 1100 280" role="img">
<defs><marker id="ahc" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#1B2733"/></marker></defs>
<a href="sources.html"><g class="dn">{tiles}{cap(20, "原始影像", "CE-2 DOM 分幅、Mini-RF 条带")}</g></a>
<a href="#overlap"><g class="op"><path d="M170 130 H 316" marker-end="url(#ahc)"/><text x="243" y="116" text-anchor="middle">重叠区提取</text><text x="243" y="152" text-anchor="middle" class="m">01_overlap.py</text></g></a>
<g class="dn">{pair}{cap(330, "重叠区影像", "同一网格，7.5 m")}</g>
<a href="#tiepoints"><g class="op manual"><path d="M446 130 H 616" marker-end="url(#ahc)"/><text x="531" y="116" text-anchor="middle">标控制点</text><text x="531" y="152" text-anchor="middle" class="m">人工，ENVI</text></g></a>
<g class="dn">{cps}{cap(630, "控制点", "约 30 对 / ROI")}</g>
<a href="#patches"><g class="op"><path d="M746 130 H 916" marker-end="url(#ahc)"/><text x="831" y="116" text-anchor="middle">协同切片</text><text x="831" y="152" text-anchor="middle" class="m">02_patches.py</text></g></a>
<a href="#products"><g class="dn">{stacks}{cap(930, "patch 对", "512 × 512")}</g></a>
</svg></nav>"""


# ---------------- 三个方案 ----------------

PRODUCTS = '<section class="step"><h2 id="products">产物</h2><p>目录结构、文件格式与标签文件见<a href="#">产物篇</a>（原型未做）。</p></section>'


def variant_a():
    figs = {
        "overlap": real_fig("", "ROI_054 重叠区影像的一段（光学行 9216–14848），左为光学，右为 SAR。SAR 条带较窄，两侧为 nodata。"),
        "tiepoints": real_fig("points", "同一段上的控制点，编号相同的为一对。"),
        "patches": real_fig("windows,sar,rejected,numbers", "同一段上的窗口：白框为保留的窗口及其编号，斜线格为剔除的窗口。指向一个窗口，另一侧的对应窗口随之高亮。"),
    }
    body = "".join(section_three(s, figs[s["id"]]) for s in STEPS) + PRODUCTS
    toc = "".join(f'<a href="#{s["id"]}">{s["no"]}　{s["name"]}</a>' for s in STEPS)
    return f"""<div class="pv" data-v="A">
<section class="bandA"><div class="wrap"><h1>流程</h1></div>{flow_a()}</section>
<div class="doc wrap"><article class="prose">{body}</article><nav class="toc" aria-label="本页目录">{toc}</nav></div></div>"""


def variant_b():
    body = "".join(section_three(s, abs_fig(s["id"])) for s in STEPS) + PRODUCTS
    return f"""<div class="pv" data-v="B"><div class="wrap layoutB">{flow_b()}
<article class="prose"><h1>流程</h1>{body}</article></div></div>"""


def variant_c():
    figs = {
        "overlap": real_fig("", "ROI_054 的一段：输出的两幅重叠区影像。"),
        "tiepoints": real_fig("points", "同一段上的控制点。"),
        "patches": real_fig("", "同一段，逐步点开：控制点解算仿射 → 光学上滑窗 → 映射到 SAR → 剔除 → 编号。", interactive=True),
    }

    def sec(s):
        io = f"""<div class="ioc"><div><h3>输入</h3>{io_list(s["inputs"])}</div><div><h3>输出</h3>{io_list(s["outputs"])}</div></div>"""
        return f"""<section class="step">{head(s)}{io}<h3>{"处理" if s["proc"] else "标注规程"}</h3>{proc_block(s)}{figs[s["id"]]}</section>"""
    body = "".join(sec(s) for s in STEPS) + PRODUCTS
    return f"""<div class="pv" data-v="C"><div class="wrap"><h1 class="hc">流程</h1></div>
<div class="wrap">{flow_c()}</div>
<div class="wrap narrow"><article class="prose">{body}</article></div></div>"""


CSS = (HERE / "process.css").read_text(encoding="utf-8")
JS = (HERE / "process.js").read_text(encoding="utf-8")
BAR = """<div id="proto-bar"><span>流程篇原型</span><a data-v="A">A 横幅流程图</a><a data-v="B">B 竖向线路图</a><a data-v="C">C 数据形态</a></div>"""


def main():
    build.main()
    shutil.copytree(HERE / "assets/process", build.OUT / "assets/process")
    body = f"<style>{CSS}</style>" + variant_a() + variant_b() + variant_c() + BAR
    script = "window.FIG=" + json.dumps(FIG) + ";\n" + JS
    doc = build.shell("a-atlas", "process.html", "流程", body, script)
    (build.OUT / "a-atlas/process.html").write_text(doc, encoding="utf-8")
    print("built", build.OUT / "a-atlas/process.html")


if __name__ == "__main__":
    main()
