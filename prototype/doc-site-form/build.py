"""PROTOTYPE（一次性）：「原型：文档站形式」的三种文档站形式。

同一份内容（content/：首页、数据来源片段、ROI 总表、67 个 ROI 页）分别构建成
  a-quarto/      Quarto + lightbox + moondata.docsite 修补
  b-mkdocs/      MkDocs Material + offline + privacy + jieba
  c-handwritten/ Python markdown 库 + 手写模板 + search-index.js
每页底部注入一个浮动切换条，可在三种形式的同一页之间跳转（← → 键亦可）。

用法：python prototype/doc-site-form/build.py
环境变量 QUARTO、MKDOCS 指向可执行文件；python 需装 markdown。
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CONTENT = HERE / "content"
WORK = HERE / "_work"
OUT = HERE / "out"
TITLE = "月球光学–SAR 配准数据集"
NAV = [("首页", "index.md"), ("数据来源", "sources.md"), ("ROI 总表", "rois/index.md")]
VARIANTS = [("a-quarto", "A · Quarto"), ("b-mkdocs", "B · MkDocs Material"), ("c-handwritten", "C · 手写生成器")]


# ---------- 内容：从现有 ROI 页转出精简版 ----------

def prepare_rois() -> None:
    src = REPO / "docs" / "rois"
    dst = CONTENT / "rois"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src / "thumbnails", dst / "thumbnails")

    index = (src / "index.md").read_text(encoding="utf-8")
    table = re.search(r"## 总览\n\n(.*?)\n\n", index, re.S).group(1)
    (dst / "index.md").write_text(f"# ROI 总表\n\n{table}\n", encoding="utf-8")

    for page in sorted(src.glob("ROI_*.md")):
        text = page.read_text(encoding="utf-8")
        title = re.search(r'^title: "(.*)"', text, re.M).group(1)
        subtitle = re.search(r'^subtitle: "(.*)"', text, re.M).group(1)
        body = text.split("---", 2)[2]
        body = re.sub(r"<!--.*?-->\n*", "", body, flags=re.S)
        body = body.split("## 本页数字从哪来")[0]
        body = re.sub(r"「官方」取自.*\n", "", body)
        body = re.sub(r"::: \{\.callout[^}]*\}\n## ", "### ", body)
        body = re.sub(r"^:::.*\n", "", body, flags=re.M)
        body = body.replace("**待本人复核。**", "")
        body = re.sub(r"\n{3,}", "\n\n", body)
        body = re.sub(r"(!\[[^\n]*\))\n\n(!\[)", r"\1\n\2", body)  # 两张缩略图并排
        (dst / page.name).write_text(f"# {title}\n\n{subtitle}\n{body}", encoding="utf-8")


def copy_content(dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(CONTENT, dst)


def run(cmd: list[str], cwd: Path) -> None:
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


# ---------- A：Quarto ----------

QUARTO_YML = f"""
project:
  type: website
  output-dir: _site
  render: ["*.md", "rois/*.md"]
lang: zh
website:
  title: "{TITLE}"
  search:
    location: navbar
    type: overlay
  navbar:
    left:
      - {{href: index.md, text: 首页}}
      - {{href: sources.md, text: 数据来源}}
      - {{href: rois/index.md, text: ROI 总表}}
format:
  html:
    theme: cosmo
    toc: true
    toc-depth: 3
    lightbox: auto
    resources-from-cdn: false
"""


def build_quarto() -> Path:
    proj = WORK / "quarto"
    copy_content(proj)
    (proj / "_quarto.yml").write_text(QUARTO_YML, encoding="utf-8")
    for md in proj.rglob("*.md"):  # Quarto 的页面标题取自 front matter
        text = md.read_text(encoding="utf-8")
        md.write_text(re.sub(r"\A# (.+)\n", r'---\ntitle: "\1"\n---\n', text), encoding="utf-8")
    run([os.environ.get("QUARTO", "quarto"), "render"], proj)
    sys.path.insert(0, str(REPO / "src"))
    from moondata.docsite import postprocess
    postprocess(proj / "_site")
    return proj / "_site"


# ---------- B：MkDocs Material ----------

MKDOCS_YML = f"""
site_name: "{TITLE}"
use_directory_urls: false
theme:
  name: material
  language: zh
  features: [navigation.sections, navigation.top, toc.follow, search.highlight]
markdown_extensions: [tables, attr_list, md_in_html, toc, pymdownx.superfences, pymdownx.highlight]
plugins:
  - search:
      separator: '[\\s\\u200b\\-_,:!=\\[\\]()"`/]+|\\.(?!\\d)|&[lg]t;|(?!\\b)(?=[A-Z][a-z])'
  - privacy
  - offline
nav:
  - 首页: index.md
  - 数据来源: sources.md
  - ROI 总表: rois/index.md
"""


def build_mkdocs() -> Path:
    proj = WORK / "mkdocs"
    copy_content(proj / "docs")
    (proj / "mkdocs.yml").write_text(MKDOCS_YML, encoding="utf-8")
    run([os.environ.get("MKDOCS", "mkdocs"), "build", "-q", "-d", "site"], proj)
    return proj / "site"


# ---------- C：手写生成器 ----------

CSS = """
*{box-sizing:border-box}
body{margin:0;font:15px/1.7 system-ui,"Microsoft YaHei",sans-serif;color:#222}
header{position:sticky;top:0;background:#fff;border-bottom:1px solid #ddd;padding:8px 20px;display:flex;gap:20px;align-items:center;z-index:5}
header .site{font-weight:600;color:#222;text-decoration:none}
header nav a{margin-right:14px;color:#555;text-decoration:none}
header nav a.here{color:#0b63c5;font-weight:600}
#q{margin-left:auto;padding:4px 8px;width:220px;border:1px solid #bbb;border-radius:4px}
#hits{position:absolute;right:20px;top:44px;width:420px;max-height:70vh;overflow:auto;background:#fff;border:1px solid #ccc;box-shadow:0 4px 16px #0002;display:none}
#hits a{display:block;padding:8px 12px;border-bottom:1px solid #eee;color:#222;text-decoration:none}
#hits a:hover{background:#f3f7fc}#hits b{color:#0b63c5}#hits small{color:#666}
.wrap{display:flex;max-width:1200px;margin:0 auto}
main{flex:1;min-width:0;padding:10px 32px 80px}
aside{width:220px;padding:20px 10px;font-size:13px;position:sticky;top:50px;align-self:flex-start;max-height:calc(100vh - 60px);overflow:auto}
aside a{display:block;color:#555;text-decoration:none;padding:2px 0}aside a.l3{padding-left:12px}
h1{font-size:1.7em;margin:.8em 0 .4em}h2{border-bottom:1px solid #eee;padding-bottom:4px;margin-top:1.8em}
table{border-collapse:collapse;margin:1em 0;font-size:14px}th,td{border:1px solid #ddd;padding:4px 10px}th{background:#f5f5f5}
code{background:#f3f3f3;padding:1px 4px;border-radius:3px;font-size:.92em}pre{background:#f6f8fa;padding:12px;overflow:auto}pre code{background:none}
img{max-width:48%;margin-right:1%;vertical-align:top;border:1px solid #ddd}
"""

SEARCH_JS = """
(function(){
  var q=document.getElementById('q'),hits=document.getElementById('hits'),root=document.body.dataset.root;
  function esc(s){return s.replace(/[&<>]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;'}[c]})}
  q.addEventListener('input',function(){
    var t=q.value.trim().toLowerCase();hits.innerHTML='';
    if(!t){hits.style.display='none';return}
    var n=0;
    window.SEARCH.forEach(function(d){
      var i=d.text.toLowerCase().indexOf(t),inTitle=d.title.toLowerCase().indexOf(t)>=0;
      if(i<0&&!inTitle)return;
      if(++n>30)return;
      var s=i<0?'':esc(d.text.slice(Math.max(0,i-30),i))+'<b>'+esc(d.text.substr(i,t.length))+'</b>'+esc(d.text.substr(i+t.length,50));
      var a=document.createElement('a');a.href=root+d.url;a.innerHTML=esc(d.title)+'<br><small>'+s+'</small>';hits.appendChild(a);
    });
    if(!n)hits.innerHTML='<a>无结果</a>';
    hits.style.display='block';
  });
  document.addEventListener('click',function(e){if(e.target!==q)hits.style.display='none'});
})();
"""


def build_handwritten() -> Path:
    site = WORK / "handwritten"
    if site.exists():
        shutil.rmtree(site)
    shutil.copytree(CONTENT / "rois" / "thumbnails", site / "rois" / "thumbnails")
    (site / "style.css").write_text(CSS, encoding="utf-8")
    (site / "search.js").write_text(SEARCH_JS, encoding="utf-8")
    index = []
    for md_path in sorted(CONTENT.rglob("*.md")):
        rel = md_path.relative_to(CONTENT).with_suffix(".html").as_posix()
        root = "../" * rel.count("/")
        conv = markdown.Markdown(extensions=["tables", "fenced_code", "toc"], extension_configs={"toc": {"toc_depth": "2-3"}})
        text = md_path.read_text(encoding="utf-8")
        body = conv.convert(text)
        body = re.sub(r'href="([^":]+)\.md(#[^"]*)?"', r'href="\1.html\2"', body)
        body = re.sub(r'<img alt="([^"]*)" src="([^"]+)" />', r'<a href="\2" target="_blank"><img alt="\1" title="\1" src="\2" loading="lazy"></a>', body)
        title = re.search(r"^# (.+)$", text, re.M).group(1)
        toc = "".join(
            f'<a class="l{t["level"]}" href="#{t["id"]}">{t["name"]}</a>'
            for t0 in conv.toc_tokens for t in [t0, *t0["children"]] if t["level"] > 1
        ) or "".join(f'<a class="l{c["level"]}" href="#{c["id"]}">{c["name"]}</a>' for t0 in conv.toc_tokens for c in t0["children"])
        nav = "".join(
            f'<a href="{root}{href[:-3]}.html" class="{"here" if rel == href[:-3] + ".html" or (href.startswith("rois") and rel.startswith("rois")) else ""}">{name}</a>'
            for name, href in NAV
        )
        page = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} – {TITLE}</title><link rel="stylesheet" href="{root}style.css"></head>
<body data-root="{root}">
<header><a class="site" href="{root}index.html">{TITLE}</a><nav>{nav}</nav>
<input id="q" placeholder="搜索" autocomplete="off"><div id="hits"></div></header>
<div class="wrap"><main>{body}</main><aside>{toc}</aside></div>
<script src="{root}search-index.js"></script><script src="{root}search.js"></script>
</body></html>"""
        out = site / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page, encoding="utf-8")
        plain = re.sub(r"<[^>]+>", " ", body)
        index.append({"url": rel, "title": title, "text": re.sub(r"\s+", " ", html.unescape(plain)).strip()})
    (site / "search-index.js").write_text("window.SEARCH=" + json.dumps(index, ensure_ascii=False) + ";", encoding="utf-8")
    return site


# ---------- 切换条 ----------

SWITCHER = """
<div id="proto-bar" style="position:fixed;left:50%;bottom:14px;transform:translateX(-50%);z-index:99999;background:#111;color:#fff;border-radius:20px;padding:6px 10px;font:13px system-ui,'Microsoft YaHei';box-shadow:0 4px 14px #0006;display:flex;gap:8px;align-items:center">
<span style="opacity:.6">PROTOTYPE</span>__LINKS__</div>
<script>
document.addEventListener('keydown',function(e){
  var t=document.activeElement;if(t&&(t.tagName==='INPUT'||t.tagName==='TEXTAREA'||t.isContentEditable))return;
  if(e.key==='ArrowLeft')location.href='__PREV__';if(e.key==='ArrowRight')location.href='__NEXT__';
});
</script>
"""


def inject_switcher() -> None:
    keys = [v for v, _ in VARIANTS]
    for i, (variant, _) in enumerate(VARIANTS):
        for page in (OUT / variant).rglob("*.html"):
            rel = page.relative_to(OUT / variant).as_posix()
            up = "../" * (rel.count("/") + 1)
            href = {k: f"{up}{k}/{rel}" for k in keys}
            links = "".join(
                f'<a href="{href[k]}" style="color:#fff;padding:2px 8px;border-radius:12px;text-decoration:none;{"background:#0b63c5" if k == variant else ""}">{label}</a>'
                for k, label in VARIANTS
            )
            bar = (SWITCHER.replace("__LINKS__", links)
                   .replace("__PREV__", href[keys[(i - 1) % 3]]).replace("__NEXT__", href[keys[(i + 1) % 3]]))
            text = page.read_text(encoding="utf-8")
            if "</body>" in text:
                page.write_text(text.replace("</body>", bar + "</body>", 1), encoding="utf-8")


LANDING = """<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>原型：文档站形式</title></head>
<body style="font:15px/1.8 system-ui,'Microsoft YaHei';max-width:720px;margin:40px auto">
<h1>原型：文档站形式</h1>
<p>三种形式，内容相同（首页、数据来源片段、ROI 总表、67 个 ROI 页）。页面底部的黑色切换条可在三者的同一页之间跳转，键盘 ← → 亦可。</p>
<ul>
<li><a href="a-quarto/index.html">A · Quarto</a>：lightbox 开启；搜索靠 docsite.py 修补</li>
<li><a href="b-mkdocs/index.html">B · MkDocs Material</a>：offline + privacy 插件，jieba 分词</li>
<li><a href="c-handwritten/index.html">C · 手写生成器</a>：Python markdown 库 + 一个模板，子串搜索</li>
</ul>
<p>建议对比：数据来源页的导航与目录、搜索「圆极化」「lat_ts」「ROI_054」「错位」、ROI 总表、ROI_008 的缩略图。</p>
</body></html>"""


def main() -> None:
    prepare_rois()
    WORK.mkdir(exist_ok=True)
    built = {"a-quarto": build_quarto(), "b-mkdocs": build_mkdocs(), "c-handwritten": build_handwritten()}
    if OUT.exists():
        shutil.rmtree(OUT)
    for name, site in built.items():
        shutil.copytree(site, OUT / name, ignore=shutil.ignore_patterns("*.md", "sitemap.xml*"))
    inject_switcher()
    (OUT / "index.html").write_text(LANDING, encoding="utf-8")
    print("built:", OUT / "index.html")


if __name__ == "__main__":
    main()
