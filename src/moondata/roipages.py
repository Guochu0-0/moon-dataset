"""ROI 档案页：每个 ROI 一页，由脚本按模板批量生成，不手写。

输入全在仓库里，所以**移动硬盘没插也能生成**：

- 元数据表 `data/metadata/minirf_metadata.csv`——决定有哪些页、条带参数；
- 统计快照 `stats/snapshot.json`——patch 数、评测真值点覆盖、已删除 ROI 的状态；
- 缩略图清单 `docs/rois/thumbnails/thumbnails.json`——由 `moondata thumbnails` 接盘生成；
- 已知问题清单 `docs/rois/known-issues.toml`——唯一手写的部分。

产出是 `docs/rois/` 下的 `ROI_<nnn>.md` 与总览页 `index.md`。写成 `.md` 而不是
`.qmd`：页面里没有要执行的代码，六十几页若各起一个 Python 内核，渲染要多等几分钟。

生成物随仓库提交（`quarto render` 前也会自动重跑一遍），并有测试守着
「提交的页面 == 生成器此刻的输出」——改了输入忘了重新生成，测试会失败。
"""

from __future__ import annotations

import json
import statistics
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from moondata.config import (
    METADATA_RELPATH,
    ROI_PAGES_RELDIR,
    SNAPSHOT_RELPATH,
    THUMBNAILS_RELDIR,
)
from moondata.docvalues import num, pct, table
from moondata.errors import (
    MetadataUnreadable,
    SnapshotUnreadable,
    StatsUnavailable,
    ThumbnailUnavailable,
)
from moondata.metadata import MetadataRow, load_metadata, padded_roi
from moondata.snapshot import Snapshot, load_snapshot
from moondata.thumbnails import MANIFEST_NAME, MODALITIES

KNOWN_ISSUES_NAME = "known-issues.toml"
OVERVIEW_NAME = "index.md"
TIEPOINTS_RELDIR = Path("data") / "tie-points"
RANGE_COLUMN = "实测有效分辨率_距离向_m"

SPLIT_NAMES = {"Train": "训练集", "Val": "验证集", "Test": "测试集"}

# 元数据表的列 → （页面上的名字, 单位）。不在这里的列按原名照样列出，
# 这样表里将来多一列也不会悄悄丢掉。
COLUMN_LABELS: dict[str, tuple[str, str]] = {
    "PRODUCT_ID": ("产品 ID", ""),
    "轨道号": ("轨道号", ""),
    "任务阶段": ("任务阶段", ""),
    "成像时刻UTC": ("成像时刻（UTC）", ""),
    "模式": ("模式", ""),
    "中心频率_GHz": ("中心频率", " GHz"),
    "入射角_deg": ("入射角", "°"),
    "视向": ("视向", ""),
    "视方位角_deg": ("视方位角", "°"),
    "投影": ("投影", ""),
    "MAP_RESOLUTION_ppd": ("地图分辨率", " 像素/度"),
    "原生采样_m": ("原生采样间隔", " m"),
    "波段数": ("波段数", ""),
    "实测有效分辨率_距离向_m": ("有效分辨率（距离向）", " m"),
    "实测有效分辨率_方位向_m": ("有效分辨率（方位向）", " m"),
}
STRIP_COLUMNS = ("条带宽_px", "条带长_px")
SKIPPED_COLUMNS = {"ROI", "划分"}

GENERATED_BANNER = (
    "<!-- 本页由 `moondata pages` 生成，不要手改。"
    "已知问题改 docs/rois/known-issues.toml，其余数字改输入后重新生成。 -->"
)


@dataclass(frozen=True)
class KnownIssue:
    title: str
    rois: tuple[str, ...]
    text: str
    source: str
    details: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class KnownIssues:
    issues: list[KnownIssue]
    range_threshold: float
    range_note: str
    range_source: str


@dataclass(frozen=True)
class RoiPageInputs:
    metadata: list[MetadataRow]
    snapshot: Snapshot
    issues: KnownIssues
    thumbnails: dict[str, Any] | None
    """缩略图清单；还没接盘生成过就是 None。"""
    tiepoint_dirs: set[str]
    """仓库 `data/tie-points/` 下有哪些 ROI 目录（不补零的写法）。"""


def load_known_issues(path: Path) -> KnownIssues:
    try:
        with Path(path).open("rb") as stream:
            document = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise MetadataUnreadable(f"已知问题清单读不动：{path}（{error}）") from error

    def required(entry: dict, key: str, where: str) -> Any:
        if key not in entry:
            raise MetadataUnreadable(f"已知问题清单 {where} 缺少 {key}：{path}")
        return entry[key]

    issues = []
    for index, entry in enumerate(document.get("issue", []), 1):
        where = f"第 {index} 条"
        rois = tuple(padded_roi(name) for name in required(entry, "rois", where))
        details = {padded_roi(k): v for k, v in entry.get("details", {}).items()}
        stray = sorted(set(details) - set(rois))
        if stray:
            raise MetadataUnreadable(
                f"已知问题清单 {where}（{entry.get('title')}）的 details 里有 rois 没列出的 ROI："
                f"{'、'.join(stray)}：{path}"
            )
        issues.append(
            KnownIssue(
                title=required(entry, "title", where),
                rois=rois,
                text=required(entry, "text", where).strip(),
                source=required(entry, "source", where),
                details=details,
            )
        )

    rule = required(document, "range_resolution", "")
    return KnownIssues(
        issues=issues,
        range_threshold=float(required(rule, "threshold", "[range_resolution]")),
        range_note=required(rule, "note", "[range_resolution]").strip(),
        range_source=required(rule, "source", "[range_resolution]"),
    )


def range_resolution_issue(rows: list[MetadataRow], issues: KnownIssues) -> KnownIssue | None:
    """SAR 距离向有效分辨率异常偏粗：按元数据表的实测列现算，不手写名单。"""
    try:
        measured = {
            r.roi: float(r.fields[RANGE_COLUMN]) for r in rows if r.fields.get(RANGE_COLUMN)
        }
    except ValueError as error:
        raise MetadataUnreadable(f"元数据表的「{RANGE_COLUMN}」列有非数字：{error}") from error
    if not measured:
        return None
    median = statistics.median(measured.values())
    line = median * issues.range_threshold
    flagged = sorted(roi for roi, value in measured.items() if value > line)
    if not flagged:
        return None
    return KnownIssue(
        title="SAR 距离向有效分辨率异常偏粗",
        rois=tuple(flagged),
        text=(
            f"元数据表里距离向实测有效分辨率的中位数是 {median:g} m；超过它的 "
            f"{issues.range_threshold:g} 倍（{line:g} m）即标注于此。方位向没有这种现象。\n\n"
            f"{issues.range_note}"
        ),
        source=issues.range_source,
        details={
            roi: f"本 ROI 距离向 {measured[roi]:g} m，是中位数的 {measured[roi] / median:.1f} 倍。"
            for roi in flagged
        },
    )


def render_pages(inputs: RoiPageInputs) -> dict[str, str]:
    """文件名 → 内容。每个元数据表中的 ROI 一页，已知问题清单里提到、表里却没有的 ROI
    也各一页，外加总览页。"""
    issues = list(inputs.issues.issues)
    computed = range_resolution_issue(inputs.metadata, inputs.issues)
    if computed is not None:
        issues.append(computed)

    rows = {row.roi: row for row in inputs.metadata}
    rois = sorted(set(rows) | {roi for issue in issues for roi in issue.rois})
    removed = {r["roi"]: r for r in inputs.snapshot.stats.get("removed_rois", [])}
    by_roi = {roi: [i for i in issues if roi in i.rois] for roi in rois}

    pages = {
        f"{roi}.md": _roi_page(roi, rows.get(roi), removed.get(roi), by_roi[roi], inputs)
        for roi in rois
    }
    pages[OVERVIEW_NAME] = _overview(rois, rows, removed, by_roi, issues, inputs)
    return pages


def write_pages(out_dir: Path, pages: dict[str, str]) -> list[str]:
    """只写内容变了的页面，删掉已经不该存在的 `ROI_*.md`。返回动过的文件名。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    changed = []
    for name, text in sorted(pages.items()):
        path = out_dir / name
        if path.is_file() and path.read_bytes() == text.encode("utf-8"):
            continue
        path.write_bytes(text.encode("utf-8"))
        changed.append(name)
    for stale in sorted(out_dir.glob("ROI_*.md")):
        if stale.name not in pages:
            stale.unlink()
            changed.append(stale.name)
    return changed


def load_inputs(repo_root: Path) -> RoiPageInputs:
    snapshot = load_snapshot(repo_root / SNAPSHOT_RELPATH)
    if snapshot is None or not snapshot.stats:
        raise SnapshotUnreadable(
            f"没有可用的统计快照：{repo_root / SNAPSHOT_RELPATH}。接上数据盘后运行 `moondata scan`。"
        )
    manifest_path = repo_root / THUMBNAILS_RELDIR / MANIFEST_NAME
    thumbnails = None
    if manifest_path.is_file():
        try:
            thumbnails = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ThumbnailUnavailable(
                f"缩略图清单读不动：{manifest_path}（{error}）。接上数据盘重跑 `moondata thumbnails`。"
            ) from error
    tiepoints = repo_root / TIEPOINTS_RELDIR
    return RoiPageInputs(
        metadata=load_metadata(repo_root / METADATA_RELPATH),
        snapshot=snapshot,
        issues=load_known_issues(repo_root / ROI_PAGES_RELDIR / KNOWN_ISSUES_NAME),
        thumbnails=thumbnails,
        tiepoint_dirs={p.name for p in tiepoints.iterdir() if p.is_dir()}
        if tiepoints.is_dir()
        else set(),
    )


def generate(repo_root: Path) -> list[str]:
    return write_pages(repo_root / ROI_PAGES_RELDIR, render_pages(load_inputs(repo_root)))


# ---- 单页 -------------------------------------------------------------------


def _roi_page(
    roi: str,
    row: MetadataRow | None,
    removed: dict | None,
    issues: list[KnownIssue],
    inputs: RoiPageInputs,
) -> str:
    stats = inputs.snapshot.stats["rois"].get(roi)
    split = (stats or removed or {}).get("split")
    subtitle = [_split_name(split) if split else "不在数据集里"]
    if removed is not None:
        subtitle[0] += "（已删除）"
    if row is not None and row.fields.get("PRODUCT_ID"):
        subtitle.append(f"Mini-RF {row.fields['PRODUCT_ID']}")

    parts = [
        f'---\ntitle: "{roi}"\nsubtitle: "{" · ".join(subtitle)}"\n---',
        GENERATED_BANNER,
    ]
    if row is None:
        parts.append(
            "::: {.callout-important}\n## 不在数据集里\n\n"
            "元数据表里没有这一行，也没有 patch。本页只是为了记下它的已知问题。\n:::"
        )
    elif stats is None and removed is None:
        raise StatsUnavailable(
            f"{roi} 在元数据表里，统计快照里却既不在现存 ROI、也不在已删除 ROI 中——"
            "快照与元数据表对不上，先重新 `moondata scan`。"
        )
    if removed is not None:
        parts.append(_removed_callout(removed))

    if row is not None:
        parts.append("## 概况\n\n" + _summary(roi, row, stats or removed, removed, inputs))
        parts.append("## Mini-RF 条带\n\n" + _strip_table(row))
    if issues:
        parts.append("## 已知问题\n\n" + "\n\n".join(_issue_callout(i, roi) for i in issues))
    if row is not None:
        parts.append("## 缩略图\n\n" + _thumbnails(roi, row, inputs.thumbnails))
    parts.append("## 本页数字从哪来\n\n" + _provenance(inputs))
    return "\n\n".join(parts) + "\n"


def _split_name(split: str) -> str:
    return SPLIT_NAMES.get(split, split)


def _removed_callout(removed: dict) -> str:
    return (
        "::: {.callout-important}\n## 已从数据盘删除\n\n"
        f"原属{_split_name(removed['split'])}。{removed['reason']}。删除于 {removed['deleted_on']}。\n\n"
        "下面的 patch 数取自删除时留下的文件清单 "
        f"`data/metadata/removed_{removed['roi']}_manifest.txt`——清单只有文件名，"
        "所以评测真值点的**点数未知**。标注现在在哪，见下方「已知问题」。\n:::"
    )


def _summary(
    roi: str, row: MetadataRow, stats: dict, removed: dict | None, inputs: RoiPageInputs
) -> str:
    split = stats["split"]
    patches, labeled = stats["patch_count"], stats["labeled_patch_count"]
    points = stats.get("label_point_count")
    if split == "Train":
        coverage = "无（训练集没有评测真值点）"
        point_text = "—"
    else:
        coverage = f"{num(labeled)} / {num(patches)}（{pct(labeled, patches)}）"
        point_text = "未知" if points is None else num(points)
    product_dir = f"`Processed_Data/{split}/{roi}/`"
    if removed is not None:
        product_dir += "（已删除）"
    tiepoints = (
        f"`{(TIEPOINTS_RELDIR / row.raw_name).as_posix()}/`"
        if row.raw_name in inputs.tiepoint_dirs
        else "仓库里没有"
    )
    return table(
        ["项", "值"],
        [
            ["所属划分", f"{_split_name(split)}（`{split}`）"],
            ["patch 对", num(patches)],
            ["带评测真值点的 patch", coverage],
            ["评测真值点对数", point_text],
            ["产物目录", product_dir],
            ["对齐控制点", tiepoints],
            ["元数据表中的写法", f"`{row.raw_name}`"],
        ],
        align="ll",
    )


def _strip_table(row: MetadataRow) -> str:
    rows = []
    strip_done = False
    for column, value in row.fields.items():
        if column in SKIPPED_COLUMNS:
            continue
        if column in STRIP_COLUMNS:
            if not strip_done:
                width, length = (row.fields.get(c, "") for c in STRIP_COLUMNS)
                rows.append(["条带尺寸（宽 × 长）", f"{_int(width)} × {_int(length)} 像素", "官方"])
                strip_done = True
            continue
        label, unit = COLUMN_LABELS.get(column, (column, ""))
        shown = f"`{value}`" if column == "PRODUCT_ID" else f"{value}{unit}"
        rows.append([label, shown if value else "—", "实测" if column.startswith("实测") else "官方"])
    return (
        table(["项", "值", "来源"], rows, align="lll")
        + "\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，"
        "口径见 `data/README.md`。"
    )


def _int(text: str) -> str:
    try:
        return num(int(text))
    except ValueError:
        return text or "—"


def _issue_callout(issue: KnownIssue, roi: str) -> str:
    body = [issue.text]
    if roi in issue.details:
        body.append(f"**本 ROI：** {issue.details[roi]}")
    if len(issue.rois) > 1:
        others = [f"[{r}]({r}.md)" for r in issue.rois if r != roi]
        body.append("同一条还涉及：" + "、".join(others) + "。")
    body.append(f"出处：{issue.source}")
    return (
        '::: {.callout-warning appearance="simple"}\n'
        f"## {issue.title}\n\n" + "\n\n".join(body) + "\n:::"
    )


def _thumbnails(roi: str, row: MetadataRow, manifest: dict[str, Any] | None) -> str:
    if manifest is None:
        return "缩略图尚未生成：接上数据盘跑 `moondata thumbnails`，再重新生成本页。"
    if roi in manifest.get("missing", {}):
        paths = "、".join(f"`{p}`" for p in manifest["missing"][roi])
        return f"没有缩略图：生成缩略图时，数据盘上找不到 {paths}。"
    entry = manifest.get("rois", {}).get(roi)
    if entry is None:
        return "没有缩略图：生成缩略图那次没有画这个 ROI，重跑 `moondata thumbnails`。"

    figures = []
    for modality in MODALITIES:
        thumb = entry[modality.name]
        low, high = thumb["stretch"]
        figures.append(
            f"![{modality.label}：{thumb['shown']}，拉伸区间 "
            f"{num(low)} ~ {num(high)}{thumb['unit']}](thumbnails/{thumb['file']})"
        )
    first = entry[MODALITIES[0].name]
    width, height = first["source_size"]
    step = first["step"]
    low_pct, high_pct = manifest["percentiles"]
    sources = "、".join(f"`{entry[m.name]['source']}`" for m in MODALITIES)
    return (
        "::: {layout-ncol=2}\n" + "\n\n".join(figures) + "\n:::\n\n"
        f"取自对齐影像 {sources}（{num(width)} × {num(height)} 像素），"
        f"每 {step} × {step} 个像素取有效像素的均值并成一个，按行列原样画出；"
        f"拉伸区间是有效像素的 {low_pct:g}% 与 {high_pct:g}% 分位。**黑色是没有数据的区域**，"
        "对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"
    )


def _provenance(inputs: RoiPageInputs) -> str:
    snapshot = inputs.snapshot
    lines = [
        f"- patch 数与评测真值点：统计快照 `stats/snapshot.json`，生成于 {snapshot.generated_at}，"
        f"数据指纹 `{snapshot.fingerprint.digest}`。",
        "- 条带参数：元数据表 `data/metadata/minirf_metadata.csv`。",
    ]
    if inputs.thumbnails is not None:
        lines.append(f"- 缩略图：`moondata thumbnails` 生成于 {inputs.thumbnails['generated_at']}。")
    lines.append("- 已知问题：`docs/rois/known-issues.toml`（手写，每条注明出处）。")
    return "\n".join(lines)


# ---- 总览页 -----------------------------------------------------------------


def _overview(
    rois: list[str],
    rows: dict[str, MetadataRow],
    removed: dict[str, dict],
    by_roi: dict[str, list[KnownIssue]],
    issues: list[KnownIssue],
    inputs: RoiPageInputs,
) -> str:
    stats = inputs.snapshot.stats["rois"]
    listed = [roi for roi in rois if roi in rows]
    outside = [roi for roi in rois if roi not in rows]

    table_rows = []
    for roi in listed:
        row = rows[roi]
        entry = stats.get(roi) or removed.get(roi) or {}
        split = entry.get("split", "")
        split_text = _split_name(split) + ("（已删除）" if roi in removed else "")
        patches = entry.get("patch_count")
        labeled = entry.get("labeled_patch_count")
        table_rows.append(
            [
                f"[{roi}]({roi}.md)",
                split_text,
                num(patches) if patches is not None else "—",
                "—" if split == "Train" or labeled is None else num(labeled),
                f"{row.fields.get('入射角_deg', '')}°",
                row.fields.get("视向", ""),
                "；".join(i.title for i in by_roi[roi]) or "",
            ]
        )

    parts = [
        "---\ntitle: ROI 档案\nsubtitle: 每个 ROI 一页\n---",
        GENERATED_BANNER,
        f"元数据表里的每个 ROI 各有一页（{num(len(listed))} 页，含已删除的 "
        f"{'、'.join(removed) or '（无）'}），另有 {num(len(outside))} 页给不在数据集里、"
        "但有已知问题要记的 ROI。点 ROI 编号进入档案页。数量的两种口径见"
        "[产物文档](../products.qmd#划分与数量)。",
        "## 总览\n\n"
        + table(
            ["ROI", "划分", "patch 对", "带真值点的", "入射角", "视向", "已知问题"],
            table_rows,
            align="llrrrll",
        ),
    ]
    if outside:
        parts.append(
            "## 不在数据集里的 ROI\n\n"
            + "\n".join(
                f"- [{roi}]({roi}.md)：{'；'.join(i.title for i in by_roi[roi])}" for roi in outside
            )
        )
    parts.append(
        "## 已知问题一览\n\n"
        "照实记录，不做解释；原因多数待作者复核。每条的出处写在档案页上。\n\n"
        + "\n".join(
            f"- **{issue.title}**：" + "、".join(f"[{r}]({r}.md)" for r in issue.rois)
            for issue in issues
        )
    )
    parts.append(
        "## 这些页面是怎么来的\n\n"
        "全部由 `moondata pages` 生成（`quarto render` 会先自动跑一遍），不手写任何一页：\n\n"
        + _provenance(inputs)
        + "\n\n缩略图要读对齐影像，所以只能接上数据盘生成（`moondata thumbnails`），"
        "生成后作为产物随仓库提交；其余输入都在仓库里，没插盘也能重新生成页面。"
    )
    return "\n\n".join(parts) + "\n"
