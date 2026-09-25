"""PROTOTYPE（「标注质量」页原型，用完即弃）：把三种写法挂进文档站，`?variant=A|B|C` 切换。

    PYTHONPATH=src conda run -n moon-dataset python research/annotation-quality-prototype/figures.py
    PYTHONPATH=src conda run -n moon-dataset python research/annotation-quality-prototype/build.py

整站写到本目录的 `_site/`（不入库），双击 `_site/data/annotation-quality.html`。
「数据说明」侧栏临时多出「标注质量」一项，放在「配对特征」之后。
"""

import re
from pathlib import Path

import markdown
from markdown.extensions.toc import slugify_unicode

from moondata import site
from moondata.config import REPO_ROOT

HERE = Path(__file__).resolve().parent
PATH = "data/annotation-quality.html"
VARIANTS = {"A": ("variant-a.md", "教科书式：逐法全展开"), "B": ("variant-b.md", "数轴开头 + 细节折叠"),
            "C": ("variant-c.md", "对照表 + 标签页")}

STYLE = """<style>
.prose figure { margin: 1.4em 0; } .prose figure img { max-width: 100%; display: block; }
.prose figcaption { font-size: 13.5px; color: var(--ink2); margin-top: .4em; }
.prose .outline { border-left: 3px solid var(--rule); padding: .2em 0 .2em 1em; color: var(--ink2); }
.prose details { border-top: 1px solid var(--rule); padding: .5em 0; }
.prose details summary { cursor: pointer; font-weight: 600; }
.prose .tabbar { display: flex; gap: 0; border-bottom: 1px solid var(--frame); margin-top: 1.6em; }
.prose .tabbar button { font: inherit; background: none; border: 1px solid transparent; border-bottom: none;
  padding: 6px 14px; cursor: pointer; color: var(--ink2); }
.prose .tabbar button.on { border-color: var(--frame); background: #fff; color: var(--ink); margin-bottom: -1px; }
.prose .tabs > section { display: none; } .prose .tabs > section.on { display: block; }
.proto-variant { display: none; } .proto-variant.on { display: block; }
.proto-bar { position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%); z-index: 99;
  background: #111; color: #fff; border-radius: 999px; padding: 6px 10px; display: flex; gap: 10px;
  align-items: center; font: 13px/1.2 sans-serif; box-shadow: 0 4px 18px rgba(0,0,0,.35); }
.proto-bar button { background: #333; color: #fff; border: 0; border-radius: 999px; width: 28px; height: 28px; cursor: pointer; }
</style>
"""

SCRIPT = """<script>
(function () {
  var keys = %s, names = %s;
  var params = new URLSearchParams(location.search);
  var current = keys.indexOf(params.get("variant")); if (current < 0) current = 0;
  var bar = document.createElement("div"); bar.className = "proto-bar";
  bar.innerHTML = '<button aria-label="上一个">←</button><span></span><button aria-label="下一个">→</button>';
  document.body.appendChild(bar);
  function show(k) {
    current = (k + keys.length) %% keys.length;
    document.querySelectorAll(".proto-variant").forEach(function (el) {
      el.classList.toggle("on", el.dataset.variant === keys[current]); });
    bar.querySelector("span").textContent = "原型 " + keys[current] + "（" + names[current] + "）";
    var url = new URL(location.href); url.searchParams.set("variant", keys[current]);
    history.replaceState(null, "", url);
  }
  bar.querySelectorAll("button")[0].onclick = function () { show(current - 1); };
  bar.querySelectorAll("button")[1].onclick = function () { show(current + 1); };
  document.addEventListener("keydown", function (e) {
    if (e.target.closest("input, textarea, [contenteditable]")) return;
    if (e.key === "ArrowLeft") show(current - 1); if (e.key === "ArrowRight") show(current + 1); });
  document.querySelectorAll(".tabbar button").forEach(function (b) {
    b.onclick = function () {
      var tabs = b.closest(".tabs");
      tabs.querySelectorAll(".tabbar button, :scope > section").forEach(function (el) { el.classList.remove("on"); });
      b.classList.add("on"); tabs.querySelector("#" + b.dataset.tab).classList.add("on"); }; });
  show(current);
})();
</script>
"""


def source(name: str) -> str:
    text = (HERE / name).read_text(encoding="utf-8")
    return re.sub(r"\{\{([\w-]+)\}\}", lambda m: (HERE / "parts" / f"{m.group(1)}.md").read_text(encoding="utf-8"), text)


def render(text: str) -> str:
    converter = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "attr_list", "md_in_html"],
        extension_configs={"toc": {"slugify": slugify_unicode}},
    )
    return re.sub(r'href="([^":#]+)\.md(#[^"]*)?"', r'href="\1.html\2"', converter.convert(text))


def main() -> None:
    page = site.Page(PATH, "data/pairing.md", "数据说明", "标注质量")
    site.DATA_PAGES.insert(4, page)
    site.PAGES.insert(site.PAGES.index(site.DATA_PAGES[3]) + 1, page)
    files = site.build_site(REPO_ROOT)
    bodies = []
    for key, (name, _) in VARIANTS.items():
        body = site._data_page(render(source(name)), page)
        bodies.append(f'<div class="proto-variant" data-variant="{key}">{body}</div>')
    keys = list(VARIANTS)
    names = [label for _, label in VARIANTS.values()]
    script = STYLE + SCRIPT % (keys, names)
    files[PATH] = site._shell(PATH, "标注质量", "\n".join(bodies), "数据说明", script)
    for fig in (HERE / "figs").glob("*.svg"):
        files[f"assets/aq/{fig.name}"] = fig.read_bytes()
    site.write_site(files, HERE / "_site")
    print("已写出", HERE / "_site" / PATH)


if __name__ == "__main__":
    main()
