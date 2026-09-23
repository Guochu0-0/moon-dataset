"""ROI 档案页：数据集里每个 ROI 一页，由脚本按模板批量生成，不手写。

输入全在仓库里，所以**移动硬盘没插也能生成**：

- 元数据表 `data/metadata/minirf_metadata.csv`——条带参数；
- 统计快照 `stats/snapshot.json`——patch 数、评测真值点覆盖；
- 缩略图清单 `docs/rois/thumbnails/thumbnails.json`——由 `moondata thumbnails` 接盘生成；
- 已知问题清单 `docs/rois/known-issues.toml`——唯一手写的部分。

**只给数据集里的 ROI 建页**，即元数据表中划分为 Train/Val/Test 的行。已删除的 ROI_60
在表里还留着一行，但它已不是数据集的一部分，不建页。

产出是 `docs/rois/` 下的 `ROI_<nnn>.md` 与总览页 `index.md`。写成 `.md` 而不是
`.qmd`：页面里没有要执行的代码，六十几页若各起一个 Python 内核，渲染要多等几分钟。

生成物随仓库提交（`quarto render` 前也会自动重跑一遍），并有测试守着
「提交的页面 == 生成器此刻的输出」——改了输入忘了重新生成，测试会失败。
"""

from __future__ import annotations

import json
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
from moondata.metadata import MetadataRow, dataset_rows, load_metadata, padded_roi
from moondata.snapshot import Snapshot, load_snapshot
from moondata.thumbnails import MANIFEST_NAME, MODALITIES

KNOWN_ISSUES_NAME = "known-issues.toml"
OVERVIEW_NAME = "index.md"
TIEPOINTS_RELDIR = Path("data") / "tie-points"

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
class RoiPageInputs:
    metadata: list[MetadataRow]
    snapshot: Snapshot
    issues: list[KnownIssue]
    thumbnails: dict[str, Any] | None
    """缩略图清单；还没接盘生成过就是 None。"""
    tiepoint_dirs: set[str]
    """仓库 `data/tie-points/` 下有哪些 ROI 目录（不补零的写法）。"""


def load_known_issues(path: Path) -> list[KnownIssue]:
    try:
        with Path(path).open("rb") as stream:
            document = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise MetadataUnreadable(f"已知问题清单读不动：{path}（{error}）") from error

    issues = []
    for index, entry in enumerate(document.get("issue", []), 1):
        where = f"第 {index} 条"
        missing = [key for key in ("title", "rois", "text", "source") if key not in entry]
        if missing:
            raise MetadataUnreadable(f"已知问题清单 {where} 缺少 {'、'.join(missing)}：{path}")
        rois = tuple(padded_roi(name) for name in entry["rois"])
        details = {padded_roi(k): v for k, v in entry.get("details", {}).items()}
        stray = sorted(set(details) - set(rois))
        if stray:
            raise MetadataUnreadable(
                f"已知问题清单 {where}（{entry['title']}）的 details 里有 rois 没列出的 ROI："
                f"{'、'.join(stray)}：{path}"
            )
        issues.append(
            KnownIssue(entry["title"], rois, entry["text"].strip(), entry["source"], details)
        )
    return issues


def render_pages(inputs: RoiPageInputs) -> dict[str, str]:
    """文件名 → 内容：数据集里每个 ROI 一页，外加总览页。"""
    rows = {row.roi: row for row in dataset_rows(inputs.metadata)}
    stray = sorted({roi for i in inputs.issues for roi in i.rois} - set(rows))
    if stray:
        # 多半是抄错了编号——宁可生成失败，也不让一条已知问题悄悄没了去处
        raise MetadataUnreadable(f"已知问题清单提到了数据集里没有的 ROI：{'、'.join(stray)}")
    by_roi = {roi: [i for i in inputs.issues if roi in i.rois] for roi in rows}

    pages = {
        f"{roi}.md": _roi_page(roi, row, by_roi[roi], inputs) for roi, row in rows.items()
    }
    pages[OVERVIEW_NAME] = _overview(rows, by_roi, inputs)
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


def _roi_stats(roi: str, inputs: RoiPageInputs) -> dict:
    stats = inputs.snapshot.stats["rois"].get(roi)
    if stats is None:
        raise StatsUnavailable(
            f"{roi} 在元数据表里是数据集的一部分，统计快照里却没有它——"
            "快照与元数据表对不上，先重新 `moondata scan`。"
        )
    return stats


def _roi_page(
    roi: str, row: MetadataRow, issues: list[KnownIssue], inputs: RoiPageInputs
) -> str:
    stats = _roi_stats(roi, inputs)
    subtitle = f"{_split_name(stats['split'])} · Mini-RF {row.fields.get('PRODUCT_ID', '')}"
    parts = [
        f'---\ntitle: "{roi}"\nsubtitle: "{subtitle}"\n---',
        GENERATED_BANNER,
        "## 概况\n\n" + _summary(roi, row, stats, inputs),
        "## Mini-RF 条带\n\n" + _strip_table(row),
    ]
    if issues:
        parts.append("## 已知问题\n\n" + "\n\n".join(_issue_callout(i, roi) for i in issues))
    parts.append("## 缩略图\n\n" + _thumbnails(roi, inputs.thumbnails))
    parts.append("## 本页数字从哪来\n\n" + _provenance(inputs))
    return "\n\n".join(parts) + "\n"


def _split_name(split: str) -> str:
    return SPLIT_NAMES.get(split, split)


def _summary(roi: str, row: MetadataRow, stats: dict, inputs: RoiPageInputs) -> str:
    split = stats["split"]
    patches, labeled = stats["patch_count"], stats["labeled_patch_count"]
    if split == "Train":
        coverage = "无（训练集没有评测真值点）"
        points = "—"
    else:
        coverage = f"{num(labeled)} / {num(patches)}（{pct(labeled, patches)}）"
        points = num(stats["label_point_count"])
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
            ["评测真值点对数", points],
            ["产物目录", f"`Processed_Data/{split}/{roi}/`"],
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


def _thumbnails(roi: str, manifest: dict[str, Any] | None) -> str:
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
    rows: dict[str, MetadataRow], by_roi: dict[str, list[KnownIssue]], inputs: RoiPageInputs
) -> str:
    table_rows = []
    for roi, row in rows.items():
        stats = _roi_stats(roi, inputs)
        split = stats["split"]
        table_rows.append(
            [
                f"[{roi}]({roi}.md)",
                _split_name(split),
                num(stats["patch_count"]),
                "—" if split == "Train" else num(stats["labeled_patch_count"]),
                f"{row.fields.get('入射角_deg', '')}°",
                row.fields.get("视向", ""),
                "；".join(i.title for i in by_roi[roi]),
            ]
        )

    parts = [
        "---\ntitle: ROI 档案\nsubtitle: 每个 ROI 一页\n---",
        GENERATED_BANNER,
        f"数据集里的 {num(len(rows))} 个 ROI 各有一页，点 ROI 编号进入。"
        "划分与数量的口径见[产物文档](../products.qmd#划分与数量)。",
        "## 总览\n\n"
        + table(
            ["ROI", "划分", "patch 对", "带真值点的", "入射角", "视向", "已知问题"],
            table_rows,
            align="llrrrll",
        ),
        "## 已知问题一览\n\n"
        "照实记录，不做解释；多数待作者复核。每条的出处写在档案页上。\n\n"
        + "\n".join(
            f"- **{issue.title}**：" + "、".join(f"[{r}]({r}.md)" for r in issue.rois)
            for issue in inputs.issues
        ),
        "## 这些页面是怎么来的\n\n"
        "全部由 `moondata pages` 生成（`quarto render` 会先自动跑一遍），不手写任何一页：\n\n"
        + _provenance(inputs)
        + "\n\n缩略图要读对齐影像，所以只能接上数据盘生成（`moondata thumbnails`），"
        "生成后作为产物随仓库提交；其余输入都在仓库里，没插盘也能重新生成页面。",
    ]
    return "\n\n".join(parts) + "\n"
