"""文档站渲染后的收尾：把成品改造成 file:// 下也完整可用的样子。

验收标准之一是「克隆后双击首页即可阅读，无需安装任何工具」。双击打开走的是
**file:// 协议**，而 Quarto 的站内搜索在运行时 `fetch("search.json")` 取索引——
同源策略把它拦下了。Quarto 自己知道这件事：它在那条路径上弹一句
"Search requires JavaScript features disabled when running in file://... URLs"
就直接返回，搜索框从此不出结果。于是「双击即可阅读」和「全文搜索可用」这两条
验收标准在开箱状态下是互斥的。

解法是取消那次运行时请求：渲染完成后，把 `search.json` 的内容直接写进
`site_libs/` 里那份 `quarto-search.js`。浏览器加载 `<script src>` 不受同源策略
约束，所以搜索在 file:// 与 http:// 下行为一致，且不必起任何服务器。

改的是**构建产物**而不是 Quarto 本身。`_site/` 每次渲染都整个重生成，所以这一步
挂在 `_quarto.yml` 的 `post-render` 上——`quarto render` 仍然是那一条命令。

## 中文搜索不需要额外分词

Fuse.js 用的是字符级 bitap，Quarto 又开了 `ignoreLocation`，所以中文子串本来就能
直接命中，不存在「必须先切词否则搜不到」的问题。唯一的限制来自 Quarto 把
`minMatchCharLength` 设成 2：单个汉字的查询不返回结果，两个字起可用。

## file:// 下的第二个坑：ES 模块

Quarto 还用 `<script type="module">` 加载 `quarto.js`（页内目录的滚动高亮、窄屏下
把目录收成菜单都在里面）。模块脚本按 CORS 取，而 file:// 的 origin 是 `null`，
浏览器一律拒绝——每一页都会在控制台留一条错误，并且丢掉这些功能。它只 import 了
一个 `tabsets.js`，所以这里把那一个文件内联进去、再把 `type="module"` 摘掉，
让它以经典脚本加载。
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from moondata.errors import DocSiteUnpatchable

SITE_DIRNAME = "_site"
SEARCH_INDEX_FILENAME = "search.json"
SEARCH_SCRIPT_RELPATH = Path("site_libs") / "quarto-search" / "quarto-search.js"

FETCH_ANCHOR = 'const response = await fetch(offsetURL("search.json"));'
"""被同源策略拦下的那一次请求。"""

FILE_PROTOCOL_ANCHOR = 'window.location.protocol === "file:" && !shownWarning'
"""Quarto 判定「现在是双击打开的」的那个条件；命中就弹窗并放弃搜索。"""

BEGIN_MARK = (
    "/* >>> moondata:offline-search-index —— 由 moondata.docsite 生成，勿手改 */"
)
END_MARK = "/* <<< moondata:offline-search-index */"

MAIN_SCRIPT_RELPATH = Path("site_libs") / "quarto-html" / "quarto.js"
TABSETS_SCRIPT_RELPATH = Path("site_libs") / "quarto-html" / "tabsets" / "tabsets.js"

TABSETS_IMPORT_ANCHOR = 'import * as tabsets from "./tabsets/tabsets.js";'
"""quarto.js 里唯一的 import。它一存在，这个文件就只能当模块加载。"""

TABSETS_EXPORT_ANCHOR = "export function init() {"
"""tabsets.js 里唯一的 export。"""

BUNDLE_MARK = "/* moondata:inlined-tabsets —— 由 moondata.docsite 内联，勿手改 */"

MODULE_ATTRIBUTE = ' type="module"'


def _script_src_pattern(relpath: Path) -> str:
    """匹配加载某个脚本的 `<script src>` 开头部分。

    src 带一段随页面深度而变的相对前缀（根目录页面是空，`docs/` 下的页面是 `../`），
    所以只锚定它的后缀。
    """
    return r'<script src="[^"]*' + re.escape(relpath.as_posix()) + '"'


TABSETS_TAG_RE = re.compile(
    r"[ \t]*" + _script_src_pattern(TABSETS_SCRIPT_RELPATH) + r"[^>]*></script>\n?"
)
MAIN_MODULE_TAG_RE = re.compile(
    "(" + _script_src_pattern(MAIN_SCRIPT_RELPATH) + ")" + re.escape(MODULE_ATTRIBUTE)
)
ANY_MODULE_TAG_RE = re.compile(r'<script src="([^"]*)"' + re.escape(MODULE_ATTRIBUTE))


def postprocess(site_dir: Path) -> None:
    """渲染完成后必须做的两件事，都是为了让成品在 file:// 下与在服务器上一样。"""
    embed_search_index(site_dir)
    inline_module_scripts(site_dir)


def embed_search_index(site_dir: Path) -> Path:
    """把 `site_dir/search.json` 嵌进 `quarto-search.js`，返回被改写的那个文件路径。"""
    index_path = site_dir / SEARCH_INDEX_FILENAME
    if not index_path.is_file():
        raise DocSiteUnpatchable(
            f"没有找到搜索索引 search.json（{index_path}）。"
            f"站点是不是在 `search: false` 下渲染的？"
        )
    script_path = _require(site_dir / SEARCH_SCRIPT_RELPATH, "quarto-search.js")

    documents = json.loads(index_path.read_text(encoding="utf-8"))
    script = script_path.read_text(encoding="utf-8")
    if BEGIN_MARK in script:
        script = _replace_existing_block(script, documents)
    else:
        script = _append_block(_bypass_the_runtime_fetch(script), documents)
    script_path.write_text(script, encoding="utf-8")
    return script_path


def _bypass_the_runtime_fetch(script: str) -> str:
    replacements = {
        # 索引已经在同一个文件里，直接给 readSearchData 一个现成的响应对象。
        FETCH_ANCHOR: "const response = __moondataOfflineSearchResponse();",
        # 双击打开正是本站的常规读法，不该被当成异常情况劝退。
        FILE_PROTOCOL_ANCHOR: "false /* moondata: 索引已内嵌，file:// 下同样可用 */",
    }
    for anchor, replacement in replacements.items():
        _require_anchor(script, anchor, "quarto-search.js")
        script = script.replace(anchor, replacement)
    return script


def _replace_existing_block(script: str, documents: object) -> str:
    """重跑时只换数据，不重复改写锚点——锚点在上一次就已经被换掉了。"""
    head, _, rest = script.partition(BEGIN_MARK)
    _, _, tail = rest.partition(END_MARK)
    return _append_block(head, documents) + tail.lstrip("\n")


def _append_block(script: str, documents: object) -> str:
    """块与上文之间空一行，块末尾一个换行。两侧的空白在这里掐准，重跑才不会每次多攒一行。"""
    return script.rstrip("\n") + "\n\n" + _block(documents) + "\n"


def _block(documents: object) -> str:
    return "\n".join(
        [
            BEGIN_MARK,
            f"const __moondataSearchDocuments = {_as_js_literal(documents)};",
            "function __moondataOfflineSearchResponse() {",
            "  return {",
            "    status: 200,",
            "    json: function () {",
            "      return Promise.resolve(__moondataSearchDocuments);",
            "    },",
            "  };",
            "}",
            END_MARK,
        ]
    )


def _as_js_literal(documents: object) -> str:
    """`ensure_ascii=False` 是为了让中文在产物里保持可读——索引是要提交进 git 的。

    代价是 U+2028/U+2029：它们在 JSON 字符串里合法，在 JS 字面量里却是换行符，
    原样写出去就是语法错误。只把这两个字符转义掉，其余照旧。
    """
    literal = json.dumps(documents, ensure_ascii=False)
    return literal.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def inline_module_scripts(site_dir: Path) -> None:
    """把 quarto.js 唯一的依赖内联进去，并把各页面上的 `type="module"` 摘掉。"""
    _bundle_main_script(site_dir)
    for page in sorted(site_dir.rglob("*.html")):
        _drop_module_attributes(page)


def _bundle_main_script(site_dir: Path) -> None:
    script_path = _require(site_dir / MAIN_SCRIPT_RELPATH, "quarto.js")
    script = script_path.read_text(encoding="utf-8")
    if BUNDLE_MARK in script:  # 已经内联过，重跑不该再叠一层
        return
    _require_anchor(script, TABSETS_IMPORT_ANCHOR, "quarto.js")

    tabsets_path = _require(site_dir / TABSETS_SCRIPT_RELPATH, "tabsets.js")
    tabsets = tabsets_path.read_text(encoding="utf-8")
    _require_anchor(tabsets, TABSETS_EXPORT_ANCHOR, "tabsets.js")

    # 保持原来的命名空间语义：quarto.js 里调的是 `tabsets.init()`。
    body = tabsets.replace(
        TABSETS_EXPORT_ANCHOR, TABSETS_EXPORT_ANCHOR.removeprefix("export ")
    )
    inlined = "\n".join(
        [
            BUNDLE_MARK,
            "const tabsets = (function () {",
            body,
            "  return { init: init };",
            "})();",
            "",
        ]
    )
    script_path.write_text(
        script.replace(TABSETS_IMPORT_ANCHOR, inlined), encoding="utf-8"
    )


def _drop_module_attributes(page: Path) -> None:
    original = page.read_text(encoding="utf-8")
    # tabsets 已经内联进 quarto.js；再以经典脚本加载一遍，它的 `export` 就是语法错误。
    html = TABSETS_TAG_RE.sub("", original)
    # 只摘 quarto.js 这一处。别的模块脚本留着，好让下面那道检查看见它们。
    html = MAIN_MODULE_TAG_RE.sub(r"\1", html)
    leftover = ANY_MODULE_TAG_RE.search(html)
    if leftover is not None:
        raise DocSiteUnpatchable(
            f"{page} 仍以模块方式加载 {leftover.group(1)}。"
            f"file:// 下模块脚本会被 CORS 拒绝，这一页在双击打开时会少一块功能。"
            f"请把它一并内联，或确认它在离线阅读下可有可无后在此放行。"
        )
    if html != original:
        page.write_text(html, encoding="utf-8")


def _require(path: Path, what: str) -> Path:
    if not path.is_file():
        raise DocSiteUnpatchable(f"没有找到 {what}（{path}）。先跑 `quarto render`。")
    return path


def _require_anchor(text: str, anchor: str, what: str) -> None:
    if anchor in text:
        return
    raise DocSiteUnpatchable(
        f"{what} 里找不到锚点：{anchor}\n"
        f"Quarto 大概升级并改写了这一段。请对照新版改 moondata/docsite.py 的锚点——"
        f"这一步宁可炸在构建期，也不能让成品带着一处静默降级发出去。"
    )


def main() -> int:
    """`_quarto.yml` 的 post-render 调用它。Quarto 以项目根为工作目录运行本步骤，
    并通过 `QUARTO_PROJECT_OUTPUT_DIR` 告知输出目录。"""
    site_dir = Path(os.environ.get("QUARTO_PROJECT_OUTPUT_DIR") or SITE_DIRNAME)
    try:
        postprocess(site_dir)
    except DocSiteUnpatchable as error:
        # 渲染没问题、只是这一步做不下去时，给一行中文而不是 traceback——与 cli.py 一致。
        print(error, file=sys.stderr)
        return 1
    print(
        f"{site_dir} 已按 file:// 离线阅读处理："
        f"搜索索引已内嵌，模块脚本已改为经典脚本"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
