"""PROTOTYPE（「标注质量」页 UI 原型，用完即弃）：同一份正文，四种版式，`?variant=A|B|C|D` 切换。

    PYTHONPATH=src conda run -n moon-dataset python research/annotation-quality-ui/figures.py
    PYTHONPATH=src conda run -n moon-dataset python research/annotation-quality-ui/build.py

整站写到本目录的 `_site/`（不入库），双击 `_site/data/annotation-quality.html`。
正文只读 `research/annotation-quality-text/text.md`，一字不改；各变体只改顺序、分栏与显隐。
「数据说明」侧栏临时多出「标注质量」一项；切换条上的「位置」按钮把它挪到「配对特征」或「使用建议」之后。
"""

import html
import re
from pathlib import Path

import markdown
from markdown.extensions.toc import slugify_unicode

from moondata import site
from moondata.config import REPO_ROOT

HERE = Path(__file__).resolve().parent
TEXT = HERE.parent / "annotation-quality-text" / "text.md"
PATH = "data/annotation-quality.html"
PARTS = ("原理", "计算", "结果", "出处")
FIGS = {  # 占位文字的开头 → 图
    "一个 patch 上": "affine-example",
    "13 个 ROI": "roi-incidence",
    "左，错位曲线": "variogram-example",
    "x、y 两个分量": "moon-variogram",
    "同一个撞击坑": "repeat-example",
}
VARIANTS = {
    "A": "线性长文，图随文",
    "B": "结果前置，图在右栏",
    "C": "三法并排对照",
    "D": "概览卡片 + 分方法详情",
}


# ---------------------------------------------------------------------------
# 解析正文


def figure(caption: str) -> str:
    name = next(v for k, v in FIGS.items() if caption.startswith(k))
    return (f'<figure class="aq-fig"><img src="../assets/aq/{name}.svg" alt="{html.escape(caption)}">'
            f"<figcaption>{html.escape(caption)}</figcaption></figure>")


def with_figures(md: str) -> str:
    return re.sub(r"〔图：(.*?)〕", lambda m: figure(m.group(1)), md)


def figures_in(md: str) -> list[str]:
    return [figure(c) for c in re.findall(r"〔图：(.*?)〕", md)]


def without_figures(md: str) -> str:
    return re.sub(r"\n*〔图：.*?〕\n*", "\n\n", md)


def render(md: str) -> str:
    converter = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "attr_list", "md_in_html"],
        extension_configs={"toc": {"slugify": slugify_unicode}},
    )
    return converter.convert(md.replace("<details>", '<details markdown="1">'))


def parse() -> dict:
    text = TEXT.read_text(encoding="utf-8")
    text = re.sub(r"^# .*\n", "", text, count=1)
    chunks = re.split(r"^## (.+)\n", text, flags=re.M)
    doc = {"intro": chunks[0].strip(), "h2": dict(zip(chunks[1::2], (c.strip() for c in chunks[2::2])))}
    m = re.split(r"^### (.+)\n", doc["h2"]["估计方法"], flags=re.M)
    methods = []
    for name, body in zip(m[1::2], m[2::2]):
        example = re.search(r"<details>.*?</details>", body, re.S).group(0)
        rest = body.replace(example, "")
        pieces = re.split(r"^\*\*(" + "|".join(PARTS) + r")\*\*", rest, flags=re.M)
        parts = {k: v.strip().lstrip("　").strip() for k, v in zip(pieces[1::2], pieces[2::2])}
        methods.append({"name": name, "body": body.strip(), "example": example, "parts": parts})
    doc["methods"] = methods
    return doc


def summary_figure() -> str:
    return ('<figure class="aq-fig"><img src="../assets/aq/summary-axis.svg" alt="估计结果数轴">'
            "<figcaption>估计结果。灰条：上界；黑线：置信区间或外推范围；蓝点：重复测量 ± 标准误。</figcaption></figure>")


# ---------------------------------------------------------------------------
# 四种版式


def variant_a(doc: dict) -> str:
    """定稿原样：引言 → 误差模型 → 估计方法（三法依次）→ 估计结果；图就在占位处。"""
    md = [doc["intro"]]
    for name, body in doc["h2"].items():
        md.append(f"## {name}\n\n{with_figures(body)}")
    return render("# 标注质量\n\n" + "\n\n".join(md))


def variant_b(doc: dict) -> str:
    """引言后先给估计结果（数轴图 + 表），再讲误差模型与方法；每种方法正文在左、图在右栏。"""
    out = [render("# 标注质量\n\n" + doc["intro"])]
    out.append(render("## 估计结果"))
    out.append(summary_figure())
    out.append(render(doc["h2"]["估计结果"]))
    out.append(render("## 误差模型\n\n" + doc["h2"]["误差模型"]))
    out.append(render("## 估计方法"))
    for m in doc["methods"]:
        figs = "".join(figures_in(m["body"]))
        out.append(f'<section class="b-method"><div class="b-text">{render("### " + m["name"] + chr(10) * 2 + without_figures(m["body"]))}</div>'
                   f'<aside class="b-figs">{figs}</aside></section>')
    return "\n".join(out)


def variant_c(doc: dict) -> str:
    """三种方法排成三列，例子 / 原理 / 计算 / 结果 / 出处逐行对齐。"""
    out = [render("# 标注质量\n\n" + doc["intro"]), render("## 误差模型\n\n" + doc["h2"]["误差模型"]),
           render("## 估计方法")]
    ms = doc["methods"]
    cells = [f'<div class="c-head c-row-label"></div>'] + [f'<h3 class="c-head">{m["name"]}</h3>' for m in ms]
    for key in ("例子", *PARTS):
        cells.append(f'<div class="c-row-label">{key}</div>')
        for m in ms:
            md = with_figures(m["example"]) if key == "例子" else with_figures(m["parts"].get(key, ""))
            cells.append(f'<div class="c-cell">{render(md)}</div>')
    out.append(f'<div class="c-grid">{"".join(cells)}</div>')
    out.append(render("## 估计结果\n\n" + doc["h2"]["估计结果"]))
    return "\n".join(out)


def variant_d(doc: dict) -> str:
    """概览：引言、误差模型、三张方法卡、估计结果；点卡片进入该方法的详情（同页，#锚点切换）。"""
    ms = doc["methods"]
    rows = {r.split("|")[1].strip(): r for r in doc["h2"]["估计结果"].splitlines() if r.startswith("| ") and "---" not in r}
    cards = []
    for i, m in enumerate(ms, 1):
        prose = re.sub(r"\n+(    .*\n*)+", "", m["parts"]["原理"])  # 摘句跳过缩进的公式
        first = re.split(r"(?<=。)", prose, maxsplit=1)[0]
        cols = [c.strip() for c in rows[m["name"]].split("|")[1:-1]]
        thumb = figures_in(m["example"])[0]
        cards.append(f'<a class="d-card" href="#m{i}">{thumb}<h3>{m["name"]}</h3>{render(first)}'
                     f'<p class="d-num">σ̂x {cols[1]}　σ̂y {cols[2]}　<span>{cols[4]}</span></p></a>')
    overview = [render("# 标注质量\n\n" + doc["intro"]), render("## 误差模型\n\n" + doc["h2"]["误差模型"]),
                render("## 估计方法"), f'<div class="d-cards">{"".join(cards)}</div>',
                render("## 估计结果"), summary_figure(), render(doc["h2"]["估计结果"])]
    views = [f'<div class="d-view" data-view="">{"".join(overview)}</div>']
    for i, m in enumerate(ms, 1):
        prev = f'<a href="#m{i - 1}">← {ms[i - 2]["name"]}</a>' if i > 1 else "<span></span>"
        nxt = f'<a href="#m{i + 1}">{ms[i]["name"]} →</a>' if i < len(ms) else "<span></span>"
        views.append(f'<div class="d-view" data-view="m{i}"><p class="d-crumb"><a href="#">标注质量</a> › 估计方法</p>'
                     f'{render("# " + m["name"] + chr(10) * 2 + with_figures(m["body"]))}'
                     f'<nav class="d-pager">{prev}{nxt}</nav></div>')
    return "\n".join(views)


# ---------------------------------------------------------------------------
# 外壳与切换条


STYLE = """<style>
.aq-fig { margin: 1.4em 0; } .aq-fig img { max-width: 100%; display: block; }
.aq-fig figcaption { font-size: 13px; color: var(--ink2); margin-top: .4em; }
.prose details { border-left: 3px solid var(--rule); padding: .1em 0 .1em 1em; margin: 1em 0; }
.prose details summary { cursor: pointer; color: var(--ink2); }
.proto-variant { display: none; } .proto-variant.on { display: block; }
/* B */
.b-method { display: grid; grid-template-columns: minmax(0, 44em) minmax(0, 1fr); gap: 32px; align-items: start; }
.b-figs { position: sticky; top: 76px; padding-top: 3.2em; }
.b-figs .aq-fig:first-child { margin-top: 0; }
/* C */
.c-grid { display: grid; grid-template-columns: 4.5em repeat(3, minmax(0, 1fr)); gap: 0 20px; margin: 1em 0 2em; }
.c-grid > * { border-top: 1px solid var(--rule); padding: .6em 0; min-width: 0; }
.c-head { margin: 0; position: sticky; top: 52px; background: var(--paper); z-index: 1; border-top: 0; font-size: 1.05em; }
.c-row-label { color: var(--ink2); font-size: 14px; font-weight: 600; }
.c-cell { font-size: 14.5px; } .c-cell > :first-child { margin-top: 0; } .c-cell details { margin: 0; }
.c-cell pre code { font-size: 12px; } .c-cell table { font-size: 13px !important; }
/* D */
.d-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; margin: 1.2em 0 2em; }
.d-card { display: block; background: #fff; border: 1px solid var(--rule); border-radius: 4px; padding: 12px 14px;
  color: var(--ink); text-decoration: none; } .d-card:hover { border-color: var(--ink); }
.d-card h3 { margin: .4em 0 .2em; } .d-card .aq-fig { margin: 0; } .d-card figcaption { display: none; }
.d-card p { font-size: 14px; margin: .3em 0; } .d-num { font-weight: 600; } .d-num span { font-weight: 400; color: var(--ink2); }
.d-view { display: none; } .d-view.on { display: block; }
.d-crumb { font-size: 14px; color: var(--ink2); } .d-pager { display: flex; justify-content: space-between;
  border-top: 1px solid var(--rule); margin-top: 3em; padding-top: 1em; }
/* 切换条 */
.proto-bar { position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%); z-index: 99;
  background: #111; color: #fff; border-radius: 999px; padding: 6px 10px; display: flex; gap: 10px;
  align-items: center; font: 13px/1.2 sans-serif; box-shadow: 0 4px 18px rgba(0,0,0,.35); }
.proto-bar button { background: #333; color: #fff; border: 0; border-radius: 999px; min-width: 28px; height: 28px;
  cursor: pointer; padding: 0 10px; }
</style>
"""

SCRIPT = """<script>
(function () {
  var keys = %s, names = %s, wide = %s;
  var params = new URLSearchParams(location.search);
  var current = Math.max(0, keys.indexOf(params.get("variant")));
  var pos = params.get("pos") === "usage" ? "usage" : "pairing";
  var bar = document.createElement("div"); bar.className = "proto-bar";
  bar.innerHTML = '<button aria-label="上一个">←</button><span></span><button aria-label="下一个">→</button>'
    + '<button class="pos"></button>';
  document.body.appendChild(bar);
  var nav = document.querySelector(".sections"), me = nav.querySelector("[aria-current]");
  function url(k, v) { var u = new URL(location.href); u.searchParams.set(k, v); history.replaceState(null, "", u); }
  function place() {
    var after = nav.querySelector('a[href$="' + pos + '.html"]');
    after.after(me);
    bar.querySelector(".pos").textContent = "位置：" + (pos === "usage" ? "使用建议之后" : "配对特征之后");
    url("pos", pos);
  }
  function route() {
    var v = location.hash.slice(1);
    document.querySelectorAll(".d-view").forEach(function (el) { el.classList.toggle("on", el.dataset.view === v); });
  }
  function show(k) {
    current = (k + keys.length) %% keys.length;
    document.querySelectorAll(".proto-variant").forEach(function (el) {
      el.classList.toggle("on", el.dataset.variant === keys[current]); });
    var isWide = wide.indexOf(keys[current]) >= 0;
    document.querySelector("article.prose").classList.toggle("wide", isWide);
    document.querySelector(".doc.wrap").style.maxWidth = isWide ? "1640px" : "";
    bar.querySelector("span").textContent = "原型 " + keys[current] + "（" + names[current] + "）";
    url("variant", keys[current]);
  }
  bar.querySelectorAll("button")[0].onclick = function () { show(current - 1); };
  bar.querySelectorAll("button")[1].onclick = function () { show(current + 1); };
  bar.querySelector(".pos").onclick = function () { pos = pos === "usage" ? "pairing" : "usage"; place(); };
  document.addEventListener("keydown", function (e) {
    if (e.target.closest("input, textarea, [contenteditable]")) return;
    if (e.key === "ArrowLeft") show(current - 1); if (e.key === "ArrowRight") show(current + 1); });
  window.addEventListener("hashchange", function () { route(); window.scrollTo(0, 0); });
  route(); place(); show(current);
})();
</script>
"""


def main() -> None:
    page = site.Page(PATH, "data/pairing.md", "数据说明", "标注质量")
    at = next(i for i, p in enumerate(site.DATA_PAGES) if p.path == "data/pairing.html") + 1
    site.DATA_PAGES.insert(at, page)
    site.PAGES.insert(site.PAGES.index(site.DATA_PAGES[at - 1]) + 1, page)
    files = site.build_site(REPO_ROOT)

    doc = parse()
    builders = {"A": variant_a, "B": variant_b, "C": variant_c, "D": variant_d}
    bodies = "\n".join(f'<div class="proto-variant" data-variant="{k}">{f(doc)}</div>' for k, f in builders.items())
    body = site._data_page(bodies, page)
    script = STYLE + SCRIPT % (list(VARIANTS), list(VARIANTS.values()), ["B", "C"])
    files[PATH] = site._shell(PATH, "标注质量", body, "数据说明", script)
    for fig in (HERE / "figs").glob("*.svg"):
        files[f"assets/aq/{fig.name}"] = fig.read_bytes()
    site.write_site(files, HERE / "_site")
    print("已写出", HERE / "_site" / PATH)


if __name__ == "__main__":
    main()
