"""文档站生成器：把仓库里的正文、素材与元数据表渲染成 `_site/`。

    python scripts/build_site.py

输入只有入库文件——`docs/pages/` 的正文、`docs/theme/` 的样式脚本字体、`docs/assets/`
的素材与 `roi-facts.json`、`data/metadata/` 的元数据表、`data/ground-truth/` 的评测真值点。
数据盘不在也能完整重建。素材由 `scripts/make_assets.py` 从数据盘生成后入库。

`_site/` 要能双击在 file:// 下打开，所以：不用 `fetch()`、不用 ES module，搜索索引是
一个经 `<script src>` 加载的 `search-index.js`，按子串匹配（中文不分词）。地图上的 ROI
圆点与总表都在生成时写成静态 HTML，脚本只加悬停、筛选与放大。

输出逐字节确定（不写时间戳、键按序），`tests/test_site.py` 据此核对入库的 `_site/`
就是生成器此刻的输出。
"""

from __future__ import annotations

import html
import json
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import markdown
import numpy as np
from markdown.extensions.toc import slugify_unicode

from moondata.errors import SiteInputUnreadable
from moondata.sources import (
    ASSETS_RELDIR,
    FACTS_NAME,
    OVERLAY_NAME,
    PROCESS_NAME,
    SAMPLES_NAME,
    ground_truth_file,
    ground_truth_files,
    load_metadata,
)

SITE_DIRNAME = "_site"
PAGES_RELDIR = Path("docs") / "pages"
THEME_RELDIR = Path("docs") / "theme"

TITLE = "月球光学–SAR 配准数据集"
SPLITS = {"Train": "训练集", "Val": "验证集", "Test": "测试集"}
LOOK = {"LEFT": "左视", "RIGHT": "右视"}
MINIRF_PROJECTION = "等距圆柱，中心经度 180°"
ANNOTATION_ANCHOR = "process.html#标注规程"
"""ROI 页「控制点」链到的地方：制作流程里标注规程那一节的标题。"""


@dataclass(frozen=True)
class Page:
    path: str
    """输出路径，相对 `_site/`。"""
    source: str
    """正文，相对 `docs/pages/`。"""
    nav: str
    """顶栏里哪一项高亮。"""
    section: str = ""
    """「数据说明」各节在侧栏里的名字。"""


DATA_PAGES = [
    Page("data/sources.html", "data/sources.md", "数据说明", "出处"),
    Page("data/organization.html", "data/organization.md", "数据说明", "组织"),
    Page("data/imaging.html", "data/imaging.md", "数据说明", "成像特征"),
    Page("data/pairing.html", "data/pairing.md", "数据说明", "配对特征"),
    Page("data/statistics.html", "data/statistics.md", "数据说明", "统计与分布"),
    Page("data/usage.html", "data/usage.md", "数据说明", "使用建议"),
    Page("data/difficulty.html", "data/difficulty.md", "数据说明", "样本难度"),
]
DIFFICULTY_PAGES = [
    Page(f"data/difficulty-{name}.html", f"data/difficulty-{name}.md", "数据说明", "样本难度")
    for name in ("distribution", "rois", "direction", "strip")
]
"""「样本难度」概览页上 4 张图卡各自点进的详情页。侧栏不列它们，停在其上时「样本难度」高亮。"""
PAGES = [
    Page("index.html", "index.md", "首页"), *DATA_PAGES, *DIFFICULTY_PAGES, Page("process.html", "process.md", "制作流程"),
]
NAV = [("首页", "index.html"), ("数据说明", DATA_PAGES[0].path), ("制作流程", "process.html")]

SPLIT_TABLE = "<!-- 划分表 -->"
SPLIT_TABLE_WITH_TRUTH = "<!-- 划分表：含评测真值点 -->"
ROI_TABLE = "<!-- ROI 总表 -->"
SAMPLES = "<!-- 样例 -->"
DIFFICULTY_TABLE = "<!-- 难度：ROI 表 -->"
PROCESS_FIGURE = re.compile(r"<!-- 流程配图 (\w+)：(.*?) -->")
"""正文里的占位注释，生成器换成由素材算出的表格与交互图。文字留在正文里手写；流程配图
的图注写在占位注释里。"""

PROCESS_FIGURES = {"images": "", "points": "points", "windows": ""}
"""流程配图的种类 → 静态显示的图层。`windows` 可逐步点开，图层随步骤变。"""
WINDOW_STEPS = ["解算仿射", "滑窗", "映射", "剔除", "编号"]
"""协同切片配图的逐步按钮。`site.js` 按按钮的先后取各步的图层，两边的顺序要一致。"""
PROCESS_RAIL = [
    ("原始影像", "数据说明", "data/sources.html", "in"),
    "CE-2 分幅、Mini-RF 条带",
    ("重叠区提取", "<code>01_overlap.py</code>", "#重叠区提取", ""),
    "重叠区影像",
    ("标控制点", "人工，ENVI", "#标控制点", "manual"),
    "控制点",
    ("协同切片", "<code>02_patches.py</code>", "#协同切片", ""),
    "patch 对",
    ("数据集", "统计与分布", "data/statistics.html", "in"),
]
"""制作流程左侧的线路图：节点（名称、脚本或来源、链接、样式）与节点之间传递的数据。"""


# ---------------------------------------------------------------------------
# 输入


@dataclass(frozen=True)
class Roi:
    roi: str
    split: str
    facts: dict
    """`roi-facts.json` 里这个 ROI 的一项。"""
    metadata: dict[str, str]
    """元数据表的一行。"""

    @property
    def patches(self) -> int:
        return self.facts["patches"]

    @property
    def truth_patches(self) -> int | None:
        return self.facts["truth_patches"]

    @property
    def truth_points(self) -> int | None:
        return self.facts["truth_points"]

    @property
    def lon(self) -> float:
        return self.facts["center"][0]

    @property
    def lat(self) -> float:
        return self.facts["center"][1]


@dataclass(frozen=True)
class Inputs:
    repo_root: Path
    rois: list[Roi]
    samples: list[dict]
    overlays: dict[str, dict]
    process: dict
    """`process.json`：流程配图的那一段影像、控制点与窗口。"""
    difficulty: dict[str, list[tuple[int, float]]]
    """有评测真值点的 ROI → 按编号升序的 (patch 编号, 点上 RMSE)。"""


def load_inputs(repo_root: Path) -> Inputs:
    """元数据表里的每个 ROI 都必须在 `roi-facts.json` 与 `overlay.json` 里有一项：少一项
    就少一个 ROI 页，宁可在这里报错。"""
    assets = repo_root / ASSETS_RELDIR
    facts = _json(assets / FACTS_NAME)
    rois = []
    for roi, record in load_metadata(repo_root).items():
        if roi not in facts:
            raise SiteInputUnreadable(f"{assets / FACTS_NAME} 里没有 {roi}——跑一次 make_assets.py facts {roi}")
        rois.append(Roi(roi, record["划分"].strip(), facts[roi], record))
    samples = [_sample(repo_root, entry) for entry in _json(assets / SAMPLES_NAME)]
    difficulty = {roi.roi: _point_rmse(repo_root, roi) for roi in rois if roi.truth_patches}
    return Inputs(repo_root, rois, samples, _json(assets / OVERLAY_NAME), _json(assets / PROCESS_NAME), difficulty)


def _point_rmse(repo_root: Path, roi: Roi) -> list[tuple[int, float]]:
    """这个 ROI 每个带评测真值点的 patch 对的点上 RMSE：各对点距离的均方根。"""
    values = []
    for path in ground_truth_files(repo_root, roi.split, roi.roi):
        try:
            a = np.loadtxt(path, ndmin=2)
        except (OSError, ValueError) as error:
            raise SiteInputUnreadable(f"{roi.roi} 的评测真值点读不动：{path}（{error}）") from error
        # 每行：光学 x、光学 y、SAR x、SAR y。距离与 y 的符号约定无关
        values.append((int(path.stem.split("_")[1]), float(np.sqrt(((a[:, 2:] - a[:, :2]) ** 2).sum(axis=1).mean()))))
    if not values:
        raise SiteInputUnreadable(f"{roi.roi} 标了 {roi.truth_patches} 个带评测真值点的 patch，仓库里却没有它的真值点文件")
    return values


def _sample(repo_root: Path, entry: dict) -> dict:
    """样例 patch 对加上它的评测真值点。真值点文件的 y 取负存盘，这里翻回向下为正的行号。"""
    roi, split, patch = entry["roi"], entry["split"], entry["patch"]
    path = ground_truth_file(repo_root, split, roi, patch)
    try:
        lines = path.read_text(encoding="utf-8").split()
    except OSError as error:
        raise SiteInputUnreadable(f"样例 {roi} patch_{patch} 的评测真值点读不动：{path}（{error}）") from error
    values = [float(token) for token in lines]
    points = [
        [round(x1, 1), round(-y1, 1), round(x2, 1), round(-y2, 1)]
        for x1, y1, x2, y2 in zip(*[iter(values)] * 4)
    ]
    name = f"{roi}_p{patch}"
    return {"roi": roi, "split": split, "patch": patch, "opt": f"samples/{name}_opt.jpg",
            "sar": f"samples/{name}_sar.jpg", "points": points}


def _json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SiteInputUnreadable(f"素材读不动：{path}（{error}）") from error


# ---------------------------------------------------------------------------
# 构建


def build_site(repo_root: Path) -> dict[str, bytes]:
    """整个站点：相对 `_site/` 的路径 → 文件内容。只读 `repo_root` 下的入库文件。"""
    inputs = load_inputs(repo_root)
    files: dict[str, bytes] = {}
    search = []
    for page in PAGES:
        title, body = _render_markdown(repo_root / PAGES_RELDIR / page.source)
        body = _fill(body, inputs, _root(page.path))
        if page.path == "index.html":
            body = _home(body, inputs)
        elif page.nav == "数据说明":
            body = _data_page(body, page)
        elif page.path == "process.html":
            body = _process_page(body)
        else:
            body = f'<div class="wrap"><article class="prose">{body}</article></div>'
        script = ""
        if page.path == "index.html":
            script = _samples_script(inputs)
        elif page.path == "process.html":
            script = _process_script(inputs)
        files[page.path] = _shell(page.path, title, body, page.nav, script)
        search.append(_search_entry(page.path, title, body))
    for position, roi in enumerate(inputs.rois):
        path = f"rois/{roi.roi}.html"
        body = _roi_page(roi, inputs, position)
        files[path] = _shell(path, roi.roi, body, "")
        search.append(_search_entry(path, roi.roi, body))
    files["search-index.js"] = (
        "window.SEARCH=" + json.dumps(search, ensure_ascii=False, separators=(",", ":")) + ";\n"
    ).encode("utf-8")
    for prefix, directory in (("assets/", repo_root / THEME_RELDIR), ("assets/", repo_root / ASSETS_RELDIR)):
        for source in sorted(directory.rglob("*")):
            rel = source.relative_to(directory).as_posix()
            if source.is_file() and not (source.parent == directory and source.suffix == ".json"):
                files[prefix + rel] = source.read_bytes()
    return files


def write_site(files: dict[str, bytes], out_dir: Path) -> None:
    """整个目录先清掉再写：删掉的页面不会留在 `_site/` 里冒充现行内容。"""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    for rel, data in sorted(files.items()):
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _render_markdown(path: Path) -> tuple[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SiteInputUnreadable(f"正文读不动：{path}（{error}）") from error
    converter = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "attr_list", "md_in_html"],
        extension_configs={"toc": {"slugify": slugify_unicode}},
    )
    body = converter.convert(text)
    # 正文之间用 .md 互链（编辑器里点得开），输出时换成 .html
    body = re.sub(r'href="([^":#]+)\.md(#[^"]*)?"', r'href="\1.html\2"', body)
    match = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    if match is None:
        raise SiteInputUnreadable(f"{path} 没有一级标题")
    return html.unescape(re.sub(r"<[^>]+>", "", match.group(1))), body


def _fill(body: str, inputs: Inputs, root: str) -> str:
    body = (
        body.replace(SPLIT_TABLE_WITH_TRUTH, _split_table(inputs.rois, with_truth=True))
        .replace(SPLIT_TABLE, _split_table(inputs.rois, with_truth=False))
        .replace(ROI_TABLE, _roi_table(inputs.rois, root))
        .replace(SAMPLES, '<div id="samples" class="samples"></div>')
        .replace(DIFFICULTY_TABLE, _difficulty_table(inputs))
    )
    return PROCESS_FIGURE.sub(lambda match: _process_figure(*match.groups()), body)


def _root(path: str) -> str:
    return "../" * path.count("/")


# ---------------------------------------------------------------------------
# 外壳


def _shell(path: str, title: str, body: str, nav: str, script: str = "") -> bytes:
    root = _root(path)
    current = ' aria-current="page"'
    links = "".join(
        f'<a href="{root}{href}"{current if name == nav else ""}>{name}</a>' for name, href in NAV
    )
    full_title = TITLE if title == TITLE else f"{title} – {TITLE}"
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(full_title)}</title>
<link rel="stylesheet" href="{root}assets/style.css">
</head>
<body data-root="{root}">
<header class="top">
<a class="site" href="{root}index.html">{TITLE}</a>
<nav>{links}</nav>
<div class="find"><input id="q" type="search" placeholder="搜索" aria-label="搜索" autocomplete="off"><div id="hits" hidden></div></div>
</header>
<main>
{body}
</main>
<script src="{root}search-index.js"></script>
{script}<script src="{root}assets/site.js"></script>
</body>
</html>
"""
    return page.encode("utf-8")


def _search_entry(path: str, title: str, body: str) -> dict[str, str]:
    text = re.sub(r"<(script|style)\b.*?</\1>|<[^>]+>", " ", body, flags=re.S)
    return {"url": path, "title": title, "text": re.sub(r"\s+", " ", html.unescape(text)).strip()}


# ---------------------------------------------------------------------------
# 首页与数据说明


def _home(body: str, inputs: Inputs) -> str:
    legend = "".join(f'<span><span class="sw {key}"></span>{zh}</span>' for key, zh in SPLITS.items())
    return f"""<section class="hero-map" aria-label="ROI 分布">
{_moon_map(inputs.rois, "", image="moon-4k.jpg", graticule=True)}
<p class="map-legend">{legend}<span>圆点为 ROI 中心，面积与 patch 对数成正比。</span></p>
</section>
<div class="wrap home prose">{body}</div>"""


def _samples_script(inputs: Inputs) -> str:
    data = json.dumps(inputs.samples, ensure_ascii=False, separators=(", ", ": "))
    return f"<script>window.SAMPLES={data};</script>\n"


def _data_page(body: str, page: Page) -> str:
    links = []
    for other in DATA_PAGES:
        current = ' aria-current="page"' if other.section == page.section else ""
        links.append(f'<a href="{_root(page.path)}{other.path}"{current}>{other.section}</a>')
    wide = " wide" if page.path.endswith("statistics.html") or page.section == "样本难度" else ""
    crumb = f'<p class="crumb"><a href="difficulty.html">样本难度</a> ›</p>' if page in DIFFICULTY_PAGES else ""
    return f"""<div class="doc wrap">
<nav class="sections" aria-label="数据说明">{"".join(links)}</nav>
<article class="prose{wide}">{crumb}{body}</article>
</div>"""


def _split_table(rois: list[Roi], *, with_truth: bool) -> str:
    head = "<th>ROI</th><th>patch 对</th>"
    if with_truth:
        head += "<th>带评测真值点的 patch 对</th><th>评测真值点对</th>"
    rows = []
    groups = [(SPLITS[key], key, [r for r in rois if r.split == key]) for key in SPLITS]
    groups.append(("合计", "", rois))
    for label, key, members in groups:
        swatch = f'<span class="sw {key}"></span>' if key else ""
        cells = f"<td>{len(members)}</td><td>{sum(r.patches for r in members)}</td>"
        if with_truth:
            patches = sum(r.truth_patches or 0 for r in members)
            points = sum(r.truth_points or 0 for r in members)
            cells += f"<td>{patches or '—'}</td><td>{points or '—'}</td>"
        total = ' class="total"' if not key else ""
        rows.append(f'<tr{total}><th scope="row">{swatch}{label}</th>{cells}</tr>')
    return f'<table class="splits"><thead><tr><th></th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def _roi_table(rois: list[Roi], root: str) -> str:
    counts = {key: sum(1 for r in rois if r.split == key) for key in SPLITS}
    filters = f'<button type="button" data-split="" aria-pressed="true">全部 {len(rois)}</button>' + "".join(
        f'<button type="button" data-split="{key}" aria-pressed="false"><span class="sw {key}"></span>{zh} {counts[key]}</button>'
        for key, zh in SPLITS.items()
    )
    rows = "".join(
        f'<tr data-roi="{r.roi}" data-split="{r.split}">'
        f'<th scope="row"><a href="{root}rois/{r.roi}.html">{r.roi}</a></th>'
        f'<td><span class="sw {r.split}"></span>{SPLITS[r.split]}</td>'
        f'<td class="num">{r.patches}</td>'
        f'<td class="num">{r.truth_patches or "—"}</td>'
        f'<td class="num">{r.truth_points or "—"}</td>'
        f'<td class="num">{_lon(r.lon)}</td><td class="num">{_lat(r.lat)}</td></tr>'
        for r in rois
    )
    return f"""<div class="roi-index">
<div class="filters" role="group" aria-label="按划分筛选">{filters}</div>
<div class="map-frame">{_moon_map(rois, root, image="moon-2k.jpg", graticule=True)}</div>
<table class="roitable">
<thead><tr><th>ROI</th><th>划分</th><th>patch 对</th><th>带评测真值点的 patch</th><th>真值点对数</th><th>中心经度</th><th>中心纬度</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</div>"""


DIFFICULTY_AXIS = (2.0, 300.0)
"""难度表里范围条与迷你曲线共用的对数刻度（像素），覆盖全部点上 RMSE。"""
RANGE_TICKS = [3, 10, 30, 100, 300]


def _log_unit(value: float) -> float:
    """点上 RMSE 在 `DIFFICULTY_AXIS` 对数刻度上的位置，0–1。"""
    low, high = (math.log(v) for v in DIFFICULTY_AXIS)
    return (math.log(min(max(value, DIFFICULTY_AXIS[0]), DIFFICULTY_AXIS[1])) - low) / (high - low)


def _log_x(value: float, width: float) -> float:
    return round(_log_unit(value) * width, 1)


def _difficulty_table(inputs: Inputs) -> str:
    """有评测真值点的 ROI 按入射角排的表：分位数、10–90 分位的范围条、沿条带的迷你曲线。

    迷你曲线的横轴是 patch 编号：编号按铺窗顺序逐行递增，所以沿条带单调。
    表头点击排序由 `site.js` 按各行的 `data-*` 值做。
    """
    rois = sorted((r for r in inputs.rois if r.roi in inputs.difficulty), key=lambda r: float(r.metadata["入射角_deg"]))
    width, spark_height = 170, 30
    axis = "".join(f'<span style="left:{_log_x(t, width)}px">{t}</span>' for t in RANGE_TICKS)
    rows = []
    for r in rois:
        numbers, values = zip(*inputs.difficulty[r.roi])
        p10, p50, p90 = np.percentile(values, [10, 50, 90])
        incidence = float(r.metadata["入射角_deg"])
        bar = (f'<svg class="range {r.split}" width="{width}" height="14" viewBox="0 0 {width} 14" aria-hidden="true">'
               f'<line x1="{_log_x(p10, width)}" y1="7" x2="{_log_x(p90, width)}" y2="7"/>'
               f'<line class="med" x1="{_log_x(p50, width)}" y1="1" x2="{_log_x(p50, width)}" y2="13"/></svg>')
        last = max(numbers) or 1
        dots = "".join(
            f'<circle cx="{round(n / last * (width - 4) + 2, 1)}" '
            f'cy="{round(spark_height - 2 - _log_unit(v) * (spark_height - 4), 1)}" r="1.1"/>'
            for n, v in zip(numbers, values)
        )
        spark = f'<svg class="spark {r.split}" width="{width}" height="{spark_height}" viewBox="0 0 {width} {spark_height}" aria-hidden="true">{dots}</svg>'
        rows.append(
            f'<tr data-incidence="{incidence:.2f}" data-median="{p50:.3f}" data-patches="{len(values)}">'
            f'<th scope="row">{r.roi}</th><td><span class="sw {r.split}"></span>{SPLITS[r.split]}</td>'
            f'<td class="num">{incidence:.1f}°</td><td class="num">{len(values)}</td>'
            f'<td class="num">{p10:.1f}</td><td class="num"><b>{p50:.1f}</b></td><td class="num">{p90:.1f}</td>'
            f"<td>{bar}</td><td>{spark}</td></tr>"
        )
    return f"""<table class="difftable sortable">
<thead><tr><th>ROI</th><th>划分</th><th class="num" data-key="incidence" aria-sort="ascending">入射角</th>
<th class="num" data-key="patches">patch 对</th><th class="num">10 分位</th><th class="num" data-key="median">中位数</th><th class="num">90 分位</th>
<th>10–90 分位<div class="raxis" style="width:{width}px">{axis}</div></th><th>沿条带</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>"""


# ---------------------------------------------------------------------------
# 制作流程


def _process_page(body: str) -> str:
    """页首（标题与流程图）通栏；其下左侧线路图，右侧每个二级标题起一节。"""
    head, _, rest = body.partition("<h2")
    sections = "".join(f'<section class="step"><h2{part}</section>' for part in rest.split("<h2") if part)
    return f"""<div class="wrap process">
<header class="process-head">{head}</header>
<div class="process-grid">
{_rail()}
<article class="prose">{sections}</article>
</div>
</div>"""


def _rail() -> str:
    items = []
    for entry in PROCESS_RAIL:
        if isinstance(entry, str):
            items.append(f'<li class="data">{entry}</li>')
            continue
        name, note, href, css = entry
        target = f' data-for="{href[1:]}"' if href.startswith("#") else ""
        items.append(f'<li class="{" ".join(["st", css]).strip()}"{target}><a href="{href}"><b>{name}</b><small>{note}</small></a></li>')
    return f'<nav class="rail" aria-label="制作流程"><ol>{"".join(items)}</ol></nav>'


def _process_figure(kind: str, caption: str) -> str:
    """配图的外框；影像、控制点与窗口由 `site.js` 按 `window.PROCESS` 画进去。"""
    if kind not in PROCESS_FIGURES:
        raise SiteInputUnreadable(f"认不出的流程配图：{kind}（可用 {'、'.join(PROCESS_FIGURES)}）")
    buttons = ""
    if kind == "windows":
        buttons = '<div class="stepbtns" role="group" aria-label="逐步查看">' + "".join(
            f'<button type="button" aria-pressed="{str(i == 0).lower()}">{name}</button>'
            for i, name in enumerate(WINDOW_STEPS)
        ) + "</div>"
    return (f'<figure class="pfig" data-layers="{PROCESS_FIGURES[kind]}">{buttons}'
            f'<div class="ppair"></div><figcaption>{html.escape(caption)}</figcaption></figure>')


def _process_script(inputs: Inputs) -> str:
    data = json.dumps(inputs.process, ensure_ascii=False, separators=(",", ":"))
    return f"<script>window.PROCESS={data};</script>\n"


# ---------------------------------------------------------------------------
# 全月地图


MAP_DOT_SCALE = 0.28
"""圆点半径（度）= √(patch 对数) × 此系数，于是面积与 patch 对数成正比。"""


def _moon_map(rois: list[Roi], root: str, *, image: str, graticule: bool = False, focus: str | None = None) -> str:
    """等距圆柱投影的全月底图加 ROI 圆点，经度 −180°–180° 从左到右。

    写成静态 SVG：链接在生成时就在，不靠脚本；大圆点先画，小圆点压在上面点得到。
    """
    parts = [f'<image href="{root}assets/{image}" x="-180" y="-90" width="360" height="180" preserveAspectRatio="none"/>']
    if graticule:
        lines = [f'<line x1="{lon}" y1="-90" x2="{lon}" y2="90"/>' for lon in range(-150, 180, 30)]
        lines += [f'<line x1="-180" y1="{lat}" x2="180" y2="{lat}"/>' for lat in range(-60, 90, 30)]
        parts.append(f'<g class="grat">{"".join(lines)}</g>')
    marks = []
    for r in sorted(rois, key=lambda r: (-r.patches, r.roi)):
        state = "" if focus is None else (" focus" if r.roi == focus else " faint")
        radius = math.sqrt(r.patches) * MAP_DOT_SCALE
        if r.roi == focus:
            radius = max(radius, 3.0)
        truth = f' data-truth="{r.truth_patches}"' if r.truth_patches else ""
        marks.append(
            f'<a href="{root}rois/{r.roi}.html" class="mark {r.split}{state}" data-roi="{r.roi}" '
            f'data-split="{r.split}" data-patches="{r.patches}"{truth} data-lon="{r.lon:.3f}" data-lat="{r.lat:.3f}" '
            f'aria-label="{r.roi}，{SPLITS[r.split]}，{r.patches} 对 patch">'
            f'<circle cx="{r.lon:.3f}" cy="{-r.lat:.3f}" r="{radius:.2f}"/></a>'
        )
    parts.append(f'<g class="marks">{"".join(marks)}</g>')
    return (
        f'<div class="moonmap" data-root="{root}"><svg viewBox="-180 -90 360 180" role="img" '
        f'aria-label="全月地图，标出 {len(rois)} 个 ROI">{"".join(parts)}</svg></div>'
    )


# ---------------------------------------------------------------------------
# ROI 页


def _roi_page(roi: Roi, inputs: Inputs, position: int) -> str:
    previous = inputs.rois[position - 1].roi
    following = inputs.rois[(position + 1) % len(inputs.rois)].roi
    return f"""<div class="wrap roi">
<header class="roi-head">
<h1>{roi.roi}</h1>
<p class="split-tag"><span class="sw {roi.split}"></span>{SPLITS[roi.split]}</p>
<nav class="stepper" aria-label="相邻 ROI"><a href="{previous}.html">上一个 {previous}</a><a href="{following}.html">下一个 {following}</a></nav>
</header>
<div class="roi-grid">
<div class="roi-side">
<div class="locator">{_moon_map(inputs.rois, "../", image="moon-2k.jpg", focus=roi.roi)}</div>
{_dataset_facts(roi, inputs.difficulty)}
{_comparison(roi)}
<h2 class="imgh">原始产品</h2>
{_overlay(roi, inputs.overlays.get(roi.roi))}
</div>
<aside class="roi-thumbs">
<h2 class="imgh">重叠区影像</h2>
<div class="thumbs">
<figure><img src="../assets/thumbs/{roi.roi}_optical.png" alt="{roi.roi} 光学重叠区影像"><figcaption>光学</figcaption></figure>
<figure><img src="../assets/thumbs/{roi.roi}_sar.png" alt="{roi.roi} SAR 重叠区影像"><figcaption>SAR</figcaption></figure>
</div>
<p class="note">黑色为无数据区域。</p>
</aside>
</div>
</div>"""


def _dataset_facts(roi: Roi, difficulty: dict[str, list[tuple[int, float]]]) -> str:
    facts = roi.facts
    west, south, east, north = facts["bbox"]
    rows = [("划分", f'<span class="sw {roi.split}"></span>{SPLITS[roi.split]}'), ("patch 对", str(roi.patches))]
    if facts["missing"]:
        missing = "、".join(str(n) for n in facts["missing"])
        rows.append(("patch 编号", f"0–{facts['last_patch']}，缺 {missing}"))
    if roi.truth_patches:
        rows.append(("带评测真值点的 patch", f"{roi.truth_patches}，共 {roi.truth_points} 对点"))
    if roi.roi in difficulty:
        p10, p50, p90 = np.percentile([v for _, v in difficulty[roi.roi]], [10, 50, 90])
        rows.append(('<a href="../data/difficulty.html">样本难度</a>',
                     f"点上 RMSE 中位数 {p50:.1f} 像素，10–90 分位 {p10:.1f}–{p90:.1f} 像素"))
    rows += [
        ("中心", f"{_lat(roi.lat)}，{_lon(roi.lon)}"),
        ("范围", f"{_lat(south)}–{_lat(north)}，{_lon(west)}–{_lon(east)}"),
        ("控制点", f'{facts["tie_points"]} 对（<a href="../{ANNOTATION_ANCHOR}">标注规程</a>）'),
    ]
    items = "".join(f"<dt>{name}</dt><dd>{value}</dd>" for name, value in rows)
    return f'<h2 class="imgh">数据集</h2><dl class="facts">{items}</dl>'


def _comparison(roi: Roi) -> str:
    """三列对照表：光学原图 | SAR 原图 | 重叠区影像。各幅相同时合并成一行。"""
    frames, overlap, meta = roi.facts["frames"], roi.facts["overlap"], roi.metadata

    def per_frame(render, *, each: bool) -> str:
        values = [render(frame) for frame in frames]
        if len(set(values)) == 1:
            return values[0] + ("（每幅）" if each and len(frames) > 1 else "")
        return "<br>".join(f"{frame['tile']}：{value}" for frame, value in zip(frames, values))

    rows = [
        ("产品", "<br>".join(f"<code>{f['id']}</code>" for f in frames), f"<code>{meta['PRODUCT_ID']}</code>", "—"),
        ("成像时刻（UTC）", "—", meta["成像时刻UTC"].replace("T", " "), "—"),
        ("投影", per_frame(lambda f: _projection(f["projection"]), each=False), MINIRF_PROJECTION,
         _projection(overlap["projection"])),
        ("像元", per_frame(lambda f: f"{f['pixel']:g} m", each=False), f"{float(meta['原生采样_m']):.4f} m",
         f"{overlap['pixel']:g} m"),
        ("图像尺寸", per_frame(lambda f: _size(f["size"]), each=True),
         _size([int(meta["条带宽_px"]), int(meta["条带长_px"])]), _size(overlap["size"])),
        ("入射角", "—", f"{float(meta['入射角_deg']):.2f}°", "—"),
        ("视向", "—", LOOK[meta["视向"]], "—"),
    ]
    body = "".join(
        f'<tr><th scope="row">{name}</th><td>{optical}</td><td>{sar}</td><td class="ovc">{overlap_value}</td></tr>'
        for name, optical, sar, overlap_value in rows
    )
    return f"""<table class="cmp">
<thead><tr><th></th><th>光学原图<br><small>CE-2 DOM</small></th><th>SAR 原图<br><small>Mini-RF</small></th><th class="ovc">重叠区影像<br><small>光学、SAR 各一幅</small></th></tr></thead>
<tbody>{body}</tbody>
</table>
<p class="note">重叠区影像：光学与 SAR 公共覆盖区外扩 1.2 倍，两者重采样到 7.5 m 的同一网格；patch 从这两幅上切出。</p>"""


OVERLAY_MAX = (580, 460)
"""叠合图在信息栏里的最大宽高（CSS 像素）。"""


def _overlay(roi: Roi, overlay: dict | None) -> str:
    """各 CE-2 分幅与 Mini-RF 条带重投影到重叠区影像的坐标系，逐图层开关，点击放大。"""
    if overlay is None:
        raise SiteInputUnreadable(f"{OVERLAY_NAME} 里没有 {roi.roi}——跑一次 make_assets.py overlays {roi.roi}")
    width, height = overlay["size"]
    scale = min(OVERLAY_MAX[0] / width, OVERLAY_MAX[1] / height)
    shown = (round(width * scale), round(height * scale))
    base = f"../assets/overlay/{roi.roi}/"
    layers = "".join(
        f'<img class="ly" data-layer="{f["tile"]}" src="{base}ce2_{f["tile"]}.webp" alt="">' for f in overlay["frames"]
    )
    layers += f'<img class="ly sar" data-layer="sar" src="{base}sar.webp" alt="">'

    def rect(box: list[float], css: str, layer: str) -> str:
        x, y, w, h = box
        return f'<rect class="{css}" data-layer="{layer}" x="{x}" y="{y}" width="{w}" height="{h}"/>'

    boxes = "".join(rect(f["box"], "fr", f["tile"]) for f in overlay["frames"]) + rect(overlay["overlap"], "ov", "ov")

    def chip(layer: str, label: str, title: str, css: str) -> str:
        return (f'<button type="button" class="chip {css}" data-layer="{layer}" aria-pressed="true" title="{title}">'
                f'<span class="box" aria-hidden="true"></span>{label}</button>')

    optical = "".join(chip(f["tile"], f["tile"], f["id"], "opt") for f in overlay["frames"])
    return f"""<figure class="ovl both">
<div class="ovl-img" style="width:{shown[0]}px;height:{shown[1]}px" tabindex="0" role="button" aria-label="放大">{layers}<svg viewBox="0 0 1 1" preserveAspectRatio="none">{boxes}</svg></div>
<div class="layers">
<span class="grp"><span class="gl">光学原图</span>{optical}</span>
<span class="grp"><span class="gl">SAR 原图</span>{chip("sar", "Mini-RF", roi.metadata["PRODUCT_ID"], "sar")}</span>
<span class="grp">{chip("ov", "重叠区", "重叠区影像的范围", "ov")}</span>
</div>
<figcaption>重投影到重叠区影像的坐标系，图宽 {overlay["width_km"]} km。点击图像放大。</figcaption>
</figure>"""


# ---------------------------------------------------------------------------
# 格式


def _lat(value: float) -> str:
    return f"{abs(value):.1f}°{'S' if value < 0 else 'N'}"


def _lon(value: float) -> str:
    value = (value + 180.0) % 360.0 - 180.0
    return f"{abs(value):.1f}°{'W' if value < 0 else 'E'}"


def _size(size: list[int]) -> str:
    return f"{size[0]:,} × {size[1]:,} 像素"


def _projection(params: dict) -> str:
    """墨卡托只取标准纬线的余弦，盘上有北半球分幅把它写成负值；写成 ±，免得读者以为
    纬线在另一个半球。"""
    name = params["name"]
    if name == "merc":
        return f"Mercator，标准纬线 ±{abs(params['lat_ts']):g}°"
    if name == "stere":
        pole = "北" if params["lat_0"] > 0 else "南"
        return f"极射赤面，{pole}极，标准纬线 ±{abs(params['lat_ts']):g}°"
    if name == "eqc":
        return f"等距圆柱，中心经度 {params['lon_0']:g}°"
    raise SiteInputUnreadable(f"认不出的投影：{params}")
