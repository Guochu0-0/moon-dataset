"""文档站构建后处理：把搜索索引嵌进 JS，使 file:// 下的全文搜索可用。

这里测的是**改写本身**，不是 Quarto。所以 fixture 自己造一份带锚点的
quarto-search.js，不依赖真的渲染过一遍——测试必须在没装 Quarto 的机器上也能跑。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from moondata.docsite import (
    FETCH_ANCHOR,
    FILE_PROTOCOL_ANCHOR,
    MAIN_SCRIPT_RELPATH,
    SEARCH_SCRIPT_RELPATH,
    TABSETS_EXPORT_ANCHOR,
    TABSETS_IMPORT_ANCHOR,
    TABSETS_SCRIPT_RELPATH,
    embed_search_index,
    inline_module_scripts,
    postprocess,
)
from moondata.errors import DocSiteUnpatchable

REPO_ROOT = Path(__file__).resolve().parents[1]

# 从真实 quarto-search.js 里截出的两处锚点所在的上下文，去掉了无关的几十行。
QUARTO_SEARCH_JS = f"""\
var fuseIndex = undefined;
var shownWarning = false;

async function readSearchData() {{
  if (fuseIndex === undefined) {{
    if ({FILE_PROTOCOL_ANCHOR}) {{
      window.alert("Search requires JavaScript features disabled ...");
      shownWarning = true;
      return;
    }}
    const fuse = new window.Fuse([], kFuseIndexOptions);
    {FETCH_ANCHOR}
    if (response.status == 200) {{
      return response.json().then(function (searchDocs) {{
        searchDocs.forEach(function (searchDoc) {{
          fuse.add(searchDoc);
        }});
        fuseIndex = fuse;
        return fuseIndex;
      }});
    }}
  }}
  return fuseIndex;
}}
"""

DOCS = [
    {"objectID": "CONTEXT.html", "title": "术语表", "text": "对齐控制点覆盖全部 67 个 ROI。"},
    {"objectID": "index.html", "title": "首页", "text": "标签文件对 y 取负。"},
]


def build_site(site: Path, docs: list[dict[str, str]] = DOCS) -> Path:
    script = site / SEARCH_SCRIPT_RELPATH
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(QUARTO_SEARCH_JS, encoding="utf-8")
    (site / "search.json").write_text(
        json.dumps(docs, ensure_ascii=False), encoding="utf-8"
    )
    return script


@pytest.fixture
def site(tmp_path: Path) -> Path:
    root = tmp_path / "_site"
    root.mkdir()
    build_site(root)
    return root


class TestEmbedding:
    def test_the_runtime_fetch_is_gone(self, site: Path) -> None:
        """fetch("search.json") 正是 file:// 下被同源策略拦下的那一次请求。"""
        patched = embed_search_index(site).read_text(encoding="utf-8")
        assert FETCH_ANCHOR not in patched

    def test_the_file_protocol_bail_out_is_disabled(self, site: Path) -> None:
        """Quarto 在 file:// 下会弹窗并直接返回，不禁掉它则搜索框永远没有结果。

        弹窗那几行留在原地不要紧——判定条件被换成常量 false 之后它们已经到不了。
        """
        patched = embed_search_index(site).read_text(encoding="utf-8")
        assert FILE_PROTOCOL_ANCHOR not in patched
        assert "if (false " in patched

    def test_every_document_is_embedded_verbatim(self, site: Path) -> None:
        patched = embed_search_index(site).read_text(encoding="utf-8")
        assert "对齐控制点覆盖全部 67 个 ROI。" in patched
        assert "标签文件对 y 取负。" in patched

    def test_chinese_stays_readable_rather_than_escaped(self, site: Path) -> None:
        """索引是要提交的构建产物。\\u6807 这种形式会让它凭空膨胀数倍。"""
        patched = embed_search_index(site).read_text(encoding="utf-8")
        assert "\\u6807" not in patched

    def test_line_separators_are_escaped(self, tmp_path: Path) -> None:
        """U+2028/U+2029 在 JSON 字符串里合法，在 JS 字面量里是换行——不转义则语法错。"""
        root = tmp_path / "_site"
        root.mkdir()
        build_site(root, [{"title": "t", "text": "before after end"}])
        patched = embed_search_index(root).read_text(encoding="utf-8")
        assert " " not in patched
        assert "\\u2028" in patched and "\\u2029" in patched


class TestRerunningTheBuild:
    def test_a_second_run_picks_up_the_new_index(self, site: Path) -> None:
        """`quarto render` 会重新生成 _site，但手动重跑这一步不该嵌进一份陈旧索引。"""
        embed_search_index(site)
        (site / "search.json").write_text(
            json.dumps([{"title": "改过了", "text": "新内容"}], ensure_ascii=False),
            encoding="utf-8",
        )
        patched = embed_search_index(site).read_text(encoding="utf-8")
        assert "新内容" in patched
        assert "对齐控制点覆盖全部 67 个 ROI。" not in patched

    def test_a_second_run_leaves_exactly_one_embedded_block(self, site: Path) -> None:
        embed_search_index(site)
        patched = embed_search_index(site).read_text(encoding="utf-8")
        assert patched.count("moondata:offline-search-index") == 2  # 起止各一


class TestItFailsLoudly:
    """这一步静默失败的代价是搜索框在已提交的成品里永远转圈，没人会发现。"""

    def test_a_missing_search_index(self, site: Path) -> None:
        (site / "search.json").unlink()
        with pytest.raises(DocSiteUnpatchable, match="search.json"):
            embed_search_index(site)

    def test_a_missing_search_script(self, site: Path) -> None:
        (site / SEARCH_SCRIPT_RELPATH).unlink()
        with pytest.raises(DocSiteUnpatchable, match="quarto-search.js"):
            embed_search_index(site)

    def test_an_anchor_quarto_no_longer_emits(self, site: Path) -> None:
        """Quarto 升级后改了那两行的写法时，必须炸在构建期而不是蒙混过关。"""
        script = site / SEARCH_SCRIPT_RELPATH
        script.write_text(
            QUARTO_SEARCH_JS.replace(FETCH_ANCHOR, "// 换了写法"), encoding="utf-8"
        )
        with pytest.raises(DocSiteUnpatchable, match="锚点"):
            embed_search_index(site)


class TestTheCommittedSite:
    """验收标准是「克隆后双击首页即可阅读」，所以成品必须在库里，且搜索必须已内嵌。"""

    def test_the_home_page_is_committed(self) -> None:
        assert (REPO_ROOT / "_site" / "index.html").is_file()

    def test_the_glossary_is_committed(self) -> None:
        assert (REPO_ROOT / "_site" / "CONTEXT.html").is_file()

    def test_search_works_without_a_web_server(self) -> None:
        script = REPO_ROOT / "_site" / SEARCH_SCRIPT_RELPATH
        patched = script.read_text(encoding="utf-8")
        assert FETCH_ANCHOR not in patched
        assert "moondata:offline-search-index" in patched

    def test_the_glossary_page_is_the_repo_root_context_file(self) -> None:
        """站点里的术语表与 agent 读的 CONTEXT.md 必须是同一份，不能有第二份会漂的副本。"""
        rendered = (REPO_ROOT / "_site" / "CONTEXT.html").read_text(encoding="utf-8")
        assert "评测真值点" in rendered and "alignment tie points" in rendered


MAIN_SCRIPT_JS = f"""\
{TABSETS_IMPORT_ANCHOR}

const sectionChanged = new CustomEvent("quarto-sectionChanged", {{}});
window.document.addEventListener("DOMContentLoaded", function () {{
  // 管理 toc 与 sidebar 的可见性
}});
tabsets.init();
"""

TABSETS_JS = """\
{TABSETS_EXPORT_ANCHOR}
  const tabsets = window.document.querySelectorAll(".panel-tabset");
}
""".replace("{TABSETS_EXPORT_ANCHOR}", TABSETS_EXPORT_ANCHOR)

PAGE_HTML = """\
<!DOCTYPE html>
<html><head>
<script src="{prefix}site_libs/quarto-search/quarto-search.js"></script>
<script src="{prefix}site_libs/quarto-html/quarto.js" type="module"></script>
<script src="{prefix}site_libs/quarto-html/tabsets/tabsets.js" type="module"></script>
</head><body>正文</body></html>
"""


def build_scripts(site: Path) -> None:
    for relpath, body in (
        (MAIN_SCRIPT_RELPATH, MAIN_SCRIPT_JS),
        (TABSETS_SCRIPT_RELPATH, TABSETS_JS),
    ):
        (site / relpath).parent.mkdir(parents=True, exist_ok=True)
        (site / relpath).write_text(body, encoding="utf-8")
    (site / "index.html").write_text(PAGE_HTML.format(prefix=""), encoding="utf-8")
    nested = site / "docs"
    nested.mkdir(exist_ok=True)
    (nested / "page.html").write_text(PAGE_HTML.format(prefix="../"), encoding="utf-8")


@pytest.fixture
def scripted_site(site: Path) -> Path:
    build_scripts(site)
    return site


class TestInliningModuleScripts:
    """`type="module"` 的 <script> 在 file:// 下被 CORS 挡掉（origin 为 null）。

    Quarto 把 toc 滚动高亮、窄屏下的目录折叠都放在这个模块里，不处理的话双击打开的
    成品会在每一页报一次 CORS 错误，并且丢掉这些功能。
    """

    def test_no_page_still_loads_a_module(self, scripted_site: Path) -> None:
        inline_module_scripts(scripted_site)
        for page in scripted_site.rglob("*.html"):
            assert 'type="module"' not in page.read_text(encoding="utf-8")

    def test_the_main_script_is_still_loaded(self, scripted_site: Path) -> None:
        inline_module_scripts(scripted_site)
        page = (scripted_site / "index.html").read_text(encoding="utf-8")
        assert '<script src="site_libs/quarto-html/quarto.js"></script>' in page

    def test_the_relative_prefix_of_nested_pages_survives(
        self, scripted_site: Path
    ) -> None:
        inline_module_scripts(scripted_site)
        page = (scripted_site / "docs" / "page.html").read_text(encoding="utf-8")
        assert '<script src="../site_libs/quarto-html/quarto.js"></script>' in page

    def test_the_tabsets_tag_is_dropped_because_it_is_now_inlined(
        self, scripted_site: Path
    ) -> None:
        """留着它会以经典脚本重新加载一遍，而它带着 `export` —— 那是语法错误。"""
        inline_module_scripts(scripted_site)
        page = (scripted_site / "index.html").read_text(encoding="utf-8")
        assert "tabsets/tabsets.js" not in page

    def test_tabsets_is_inlined_ahead_of_its_first_use(
        self, scripted_site: Path
    ) -> None:
        inline_module_scripts(scripted_site)
        bundled = (scripted_site / MAIN_SCRIPT_RELPATH).read_text(encoding="utf-8")
        assert TABSETS_IMPORT_ANCHOR not in bundled
        assert "export " not in bundled
        assert bundled.index("panel-tabset") < bundled.index("tabsets.init();")

    def test_rerunning_is_a_no_op(self, scripted_site: Path) -> None:
        inline_module_scripts(scripted_site)
        once = (scripted_site / MAIN_SCRIPT_RELPATH).read_text(encoding="utf-8")
        inline_module_scripts(scripted_site)
        assert (scripted_site / MAIN_SCRIPT_RELPATH).read_text(encoding="utf-8") == once

    def test_an_unknown_module_script_is_not_swallowed(
        self, scripted_site: Path
    ) -> None:
        """将来某一页引入了别的模块（例如 OJS）时，要在构建期看见，而不是在读者的控制台里。"""
        page = scripted_site / "index.html"
        page.write_text(
            page.read_text(encoding="utf-8").replace(
                "</head>", '<script src="ojs.js" type="module"></script></head>'
            ),
            encoding="utf-8",
        )
        with pytest.raises(DocSiteUnpatchable, match="ojs.js"):
            inline_module_scripts(scripted_site)

    def test_a_changed_quarto_module_layout(self, site: Path) -> None:
        build_scripts(site)
        script = site / MAIN_SCRIPT_RELPATH
        script.write_text(
            MAIN_SCRIPT_JS.replace(TABSETS_IMPORT_ANCHOR, "// 换了写法"),
            encoding="utf-8",
        )
        with pytest.raises(DocSiteUnpatchable, match="锚点"):
            inline_module_scripts(site)


class TestPostprocess:
    def test_it_does_both_halves(self, scripted_site: Path) -> None:
        postprocess(scripted_site)
        assert FETCH_ANCHOR not in (
            scripted_site / SEARCH_SCRIPT_RELPATH
        ).read_text(encoding="utf-8")
        assert 'type="module"' not in (scripted_site / "index.html").read_text(
            encoding="utf-8"
        )


class TestTheCommittedSiteLoadsNoModules:
    def test_every_committed_page(self) -> None:
        for page in (REPO_ROOT / "_site").rglob("*.html"):
            assert 'type="module"' not in page.read_text(encoding="utf-8")
