"""接缝二：站点生成器的整体输出。

生成器只读仓库里的文件（文档正文、`docs/theme/`、`docs/assets/`、`data/metadata/`、
`data/ground-truth/`），所以这里不接数据盘：用 3 个 ROI 的小型夹具驱动它，再对真实
仓库跑一遍，核对入库的 `_site/` 就是它此刻的输出。
"""

from __future__ import annotations

import html
import json
import posixpath
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from moondata.site import build_site

REPO = Path(__file__).resolve().parents[1]

METADATA_HEADER = (
    "ROI,划分,PRODUCT_ID,轨道号,任务阶段,成像时刻UTC,模式,中心频率_GHz,入射角_deg,视向,"
    "视方位角_deg,投影,MAP_RESOLUTION_ppd,原生采样_m,条带宽_px,条带长_px,波段数"
)
METADATA_ROWS = [
    "ROI_6,Test,LSZ_00001_2CD_EKU_10S100_V1,1,NOMINAL MISSION,2009-10-01T00:00:01,ZOOM_S,2.3800,48.10,LEFT,270.00,EQUIRECTANGULAR,4096.0,7.4032,2765,52703,4",
    "ROI_27,Train,LSZ_00002_2CD_EKU_20N200_V1,2,NOMINAL MISSION,2009-11-01T00:00:02,ZOOM_S,2.3800,50.20,RIGHT,90.00,EQUIRECTANGULAR,4096.0,7.4032,3000,40000,4",
    "ROI_35,Val,LSZ_00003_2CD_EKU_30S300_V1,3,NOMINAL MISSION,2009-12-01T00:00:03,ZOOM_S,2.3800,49.00,LEFT,270.00,EQUIRECTANGULAR,4096.0,7.4032,2500,30000,4",
]


def _frame(tile: str, lat_ts: float) -> dict:
    return {
        "id": f"CE2_GRAS_DOM_07m_{tile}_03S131W_A",
        "tile": tile,
        "projection": {"name": "merc", "lat_ts": lat_ts},
        "pixel": 7.0,
        "size": [32348, 30273],
    }


def _facts(patches: int, *, missing: tuple[int, ...] = (), truth: tuple[int, int] | None = None,
           frames: list[dict], center: list[float]) -> dict:
    return {
        "patches": patches,
        "last_patch": patches + len(missing) - 1,
        "missing": list(missing),
        "truth_patches": truth[0] if truth else None,
        "truth_points": truth[1] if truth else None,
        "tie_points": 30,
        "center": center,
        "bbox": [center[0] - 0.4, center[1] - 4, center[0] + 0.4, center[1] + 4],
        "frames": frames,
        "overlap": {"projection": {"name": "merc", "lat_ts": 7.0}, "pixel": 7.5, "size": [3251, 33915]},
    }


FACTS = {
    "ROI_006": _facts(81, truth=(60, 480), frames=[_frame("H107", -7.0)], center=[-127.3, -3.5]),
    "ROI_027": _facts(
        234, missing=[95, 98, 99], frames=[_frame("E215", 35.0), _frame("E216", 35.0)],
        center=[40.0, 30.0],
    ),
    "ROI_035": _facts(214, truth=(200, 1500), frames=[_frame("I219", -21.0)], center=[179.8, -25.0]),
}

PAGES = {
    "index.md": "# 月球光学–SAR 配准数据集\n\nLRO Mini-RF 的 S 波段混合极化 SAR（发射圆极化）。\n\n<!-- 划分表 -->\n",
    "data/sources.md": "# 出处\n",
    "data/organization.md": "# 组织\n",
    "data/imaging.md": "# 成像特征\n",
    "data/pairing.md": "# 配对特征\n",
    "data/statistics.md": "# 统计与分布\n\n## 划分与数量\n\n<!-- 划分表 -->\n\n## ROI 总表\n\n<!-- ROI 总表 -->\n",
    "data/usage.md": "# 使用建议\n",
    "process.md": (
        '# 制作流程\n\n<div class="flow"><svg><a href="#标控制点"><text>标控制点</text></a></svg></div>\n\n'
        "## 重叠区提取\n\n## 标控制点\n\n### 标注规程\n\n"
        "## 协同切片\n\n<!-- 流程配图 windows：同一段，逐步点开。 -->\n"
    ),
}

PROCESS = {
    "roi": "ROI_006", "rows": [0, 1024], "scale": 4, "size": [1024, 1024], "patch": 512,
    "optical": "process/opt.jpg", "sar": "process/sar.jpg",
    "points": [[100.0, 200.0, 110.0, 190.0]],
    "windows": [{"o": [0, 0], "s": [10, -8], "i": None}, {"o": [512, 0], "s": [522, -8], "i": 0}],
}


@pytest.fixture(scope="module")
def fixture_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("repo")
    for rel, text in PAGES.items():
        _write(root / "docs" / "pages" / rel, text)
    _write(root / "docs" / "theme" / "style.css", "body { color: #1B2733; }\n")
    _write(root / "docs" / "theme" / "site.js", "window.Site = {};\n")
    _write(root / "docs" / "theme" / "fonts" / "plex.woff2", "font")
    assets = root / "docs" / "assets"
    _write(assets / "roi-facts.json", json.dumps(FACTS, ensure_ascii=False))
    _write(assets / "samples.json", json.dumps([{"roi": "ROI_006", "split": "Test", "patch": 3}]))
    _write(assets / "overlay.json", json.dumps({roi: {
        "size": [800, 1600], "width_km": 180,
        "overlap": [0.3, 0.1, 0.2, 0.8],
        "frames": [{"tile": f["tile"], "id": f["id"], "box": [0, 0, 1, 0.5]} for f in facts["frames"]],
        "sar": [0.35, 0, 0.1, 1],
    } for roi, facts in FACTS.items()}))
    _write(assets / "process.json", json.dumps(PROCESS, ensure_ascii=False))
    for name in ("moon-2k.jpg", "moon-4k.jpg", "samples/ROI_006_p3_opt.jpg", "samples/ROI_006_p3_sar.jpg",
                 "process/opt.jpg", "process/sar.jpg"):
        _write(assets / name, "img")
    _write(root / "data" / "metadata" / "minirf_metadata.csv",
           "﻿" + "\r\n".join([METADATA_HEADER, *METADATA_ROWS]) + "\r\n")
    _write(root / "data" / "ground-truth" / "Test" / "ROI_006" / "patch_3.txt",
           "177.1\t-332.9\t262.6\t-333.8\r\n205.5\t-244.7\t297.3\t-244.8\r\n")
    return root


@pytest.fixture(scope="module")
def fixture_site(fixture_repo: Path) -> dict[str, bytes]:
    return build_site(fixture_repo)


@pytest.fixture(scope="module")
def real_site() -> dict[str, bytes]:
    return build_site(REPO)


# ---------------------------------------------------------------------------
# 夹具


def test_every_roi_has_a_page_linked_from_the_roi_table_and_the_home_map(
    fixture_site: dict[str, bytes],
) -> None:
    home = _links_inside(fixture_site["index.html"], "moonmap")
    table = _links_inside(fixture_site["data/statistics.html"], "roitable")
    for roi in FACTS:
        assert f"rois/{roi}.html" in fixture_site
        assert f"rois/{roi}.html" in home
        assert f"../rois/{roi}.html" in table


def test_patch_numbers_appear_only_when_they_have_gaps(fixture_site: dict[str, bytes]) -> None:
    gapped = _text(fixture_site["rois/ROI_027.html"])
    assert "patch 编号" in gapped and "0–236，缺 95、98、99" in gapped
    assert "patch 编号" not in _text(fixture_site["rois/ROI_006.html"])


def test_truth_points_are_shown_only_for_validation_and_test(fixture_site: dict[str, bytes]) -> None:
    assert "60，共 480 对点" in _text(fixture_site["rois/ROI_006.html"])
    assert "带评测真值点的 patch" not in _text(fixture_site["rois/ROI_027.html"])
    row = _table_row(fixture_site["data/statistics.html"], "ROI_027")
    assert row[:3] == ["ROI_027", "训练集", "234"] and row[3:5] == ["—", "—"]


def test_home_samples_carry_the_ground_truth_points(fixture_site: dict[str, bytes]) -> None:
    home = fixture_site["index.html"].decode("utf-8")
    assert "[177.1, 332.9, 262.6, 333.8]" in home  # y 取负存盘，页面上是向下为正的像素行


def test_process_figure_carries_the_windows_and_its_caption(fixture_site: dict[str, bytes]) -> None:
    page = fixture_site["process.html"].decode("utf-8")
    assert '"windows":[{"o":[0,0],"s":[10,-8],"i":null}' in page
    assert "同一段，逐步点开。" in _text(fixture_site["process.html"])
    assert [step for step in ("解算仿射", "滑窗", "映射", "剔除", "编号") if step not in page] == []


def test_search_index_holds_page_text_for_substring_search(fixture_site: dict[str, bytes]) -> None:
    index = fixture_site["search-index.js"].decode("utf-8")
    assert index.startswith("window.SEARCH=")
    assert "圆极化" in index



# ---------------------------------------------------------------------------
# 夹具与真实仓库共用的约束


@pytest.fixture(params=["fixture", "real"])
def any_site(request: pytest.FixtureRequest) -> dict[str, bytes]:
    return request.getfixturevalue(f"{request.param}_site")


def test_pages_never_fetch_or_use_es_modules(any_site: dict[str, bytes]) -> None:
    for path, data in any_site.items():
        if not path.endswith((".html", ".js")):
            continue
        text = data.decode("utf-8")
        assert "fetch(" not in text, path
        assert 'type="module"' not in text and "type=module" not in text, path
        assert not re.search(r"^\s*(import|export)\s", text, re.M), path
        if path.endswith(".html"):
            assert re.search(r'<script src="(\.\./)*search-index\.js"></script>', text), path


def test_links_inside_the_site_reach_an_existing_page_and_anchor(any_site: dict[str, bytes]) -> None:
    """ROI 页的控制点链到标注规程、流程图与线路图链到各节：链接写错了，页面不会报错。"""
    ids = {path: _ids(data) for path, data in any_site.items() if path.endswith(".html")}
    broken = []
    for path in ids:
        for href in _hrefs(any_site[path]):
            if re.match(r"[a-z]+:", href):
                continue
            target, _, anchor = href.partition("#")
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target)) if target else path
            if resolved not in any_site or (anchor and anchor not in ids.get(resolved, set())):
                broken.append(f"{path} → {href}")
    assert broken == []


def test_rendered_text_has_no_issue_references(any_site: dict[str, bytes]) -> None:
    for path, data in any_site.items():
        if path.endswith(".html"):
            assert not re.search(r"#\d+", _text(data)), path


def test_every_roi_in_the_metadata_table_has_a_page(real_site: dict[str, bytes]) -> None:
    rois = [
        f"ROI_{int(line.split(',', 1)[0][4:]):03d}"
        for line in (REPO / "data/metadata/minirf_metadata.csv").read_text(encoding="utf-8-sig").splitlines()[1:]
        if line.strip()
    ]
    assert len(rois) == 67
    home = _links_inside(real_site["index.html"], "moonmap")
    table = _links_inside(real_site["data/statistics.html"], "roitable")
    for roi in rois:
        assert f"rois/{roi}.html" in real_site
        assert f"rois/{roi}.html" in home and f"../rois/{roi}.html" in table


def test_committed_site_is_the_generator_output(real_site: dict[str, bytes]) -> None:
    """改了正文、素材或元数据却忘了重建，页面不会报错，只会悄悄过期。"""
    committed = {
        p.relative_to(REPO / "_site").as_posix(): p for p in (REPO / "_site").rglob("*") if p.is_file()
    }
    assert set(committed) == set(real_site), "文件集合对不上，跑一次 python scripts/build_site.py"
    stale = sorted(path for path, data in real_site.items() if committed[path].read_bytes() != data)
    assert stale == [], f"这些文件过期了，跑一次 python scripts/build_site.py：{stale[:10]}"


# ---------------------------------------------------------------------------


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


class _Collector(HTMLParser):
    """收集页面的正文文本、某个 class 元素内的链接、表格行。"""

    def __init__(self, scope_class: str | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.scope_class = scope_class
        self.depth = 0
        self.links: set[str] = set()
        self.text: list[str] = []
        self.rows: list[list[str]] = []
        self._skip = 0
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        if self.depth:
            self.depth += 1
        elif self.scope_class and self.scope_class in (attributes.get("class") or "").split():
            self.depth = 1
        if self.depth and tag == "a" and attributes.get("href"):
            self.links.add(attributes["href"])
        if tag == "tr":
            self.rows.append([])
        if tag in ("td", "th"):
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip -= 1
        if self.depth:
            self.depth -= 1
        if tag in ("td", "th") and self._cell is not None and self.rows:
            self.rows[-1].append("".join(self._cell).strip())
            self._cell = None

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.text.append(data)
            if self._cell is not None:
                self._cell.append(data)


def _links_inside(page: bytes, css_class: str) -> set[str]:
    collector = _Collector(css_class)
    collector.feed(page.decode("utf-8"))
    return collector.links


def _hrefs(page: bytes) -> set[str]:
    return {html.unescape(href) for href in re.findall(r'\bhref="([^"]*)"', page.decode("utf-8"))}


def _ids(page: bytes) -> set[str]:
    return {html.unescape(value) for value in re.findall(r'\bid="([^"]*)"', page.decode("utf-8"))}


def _text(page: bytes) -> str:
    collector = _Collector()
    collector.feed(page.decode("utf-8"))
    return " ".join(collector.text)


def _table_row(page: bytes, first_cell: str) -> list[str]:
    collector = _Collector()
    collector.feed(page.decode("utf-8"))
    return next(row for row in collector.rows if row and row[0] == first_cell)
