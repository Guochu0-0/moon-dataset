"""命令行入口。

子命令分两类，区别只在**要不要读影像**：

- **只读自检/查询**：`doctor`。移动硬盘没插照样跑完并给出报告。
- **只读仓库的生成**：`pages`，按仓库里的元数据表、统计快照、缩略图清单与已知问题清单
  生成 ROI 档案页。不碰数据盘，`quarto render` 前自动跑。
- **只读仓库的流程步骤**：`tiepoints` 与 `transform`。对齐控制点在仓库的 `data/` 里，
  估计变换是纯几何，所以这两步既不要数据盘、也不要 GDAL。
- **只读仓库的验收**：`verify-windows`，拿 `work/windows/` 里的正向结果对照窗口清单。
- **要读影像的**：四步流程里的 `overlap`、`windows` 与 `patches`，读遍 patch 产物、写出统计快照的
  `scan`，以及从对齐影像画 ROI 缩略图的 `thumbnails`。
  它们进门第一件事是检查数据根，不可达就干净地退出。

四步流程的子命令与包的顶层模块一一对应。带 `--verify` 时拿正向结果对照仓库里的窗口清单
（验收，不影响产出）；对不上以退出码 1 结束，好让脚本据此判断。

预期内的错误一律渲染成一行中文并以退出码 1 结束，不打印 traceback。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

from moondata.config import (
    ENV_VAR,
    METADATA_RELPATH,
    THUMBNAILS_RELDIR,
    Config,
    load_config,
)
from moondata.doctor import Reachability, format_report, probe_data_root, run_doctor
from moondata.errors import (
    DataRootUnavailable,
    MoonDataError,
    NotImplementedYet,
    RepoRootNotFound,
    StatsUnavailable,
)
from moondata.geometry import TransformModel, plan_windows
from moondata.manifest import ManifestRoi, load_window_manifests, write_window_manifest
from moondata.metadata import dataset_rows, load_metadata, padded_roi
from moondata.overlap import (
    DEFAULT_RESAMPLE,
    GridCrs,
    align,
    align_selection,
    grid_differences,
    has_selection,
    locate_sources,
    plan_alignment,
)
from moondata.patches import (
    PATCH_SIZE,
    SELECTION_RELDIR,
    WINDOWS_RELDIR,
    compare_windows,
    select_windows,
)
from moondata.roipages import generate as generate_roi_pages
from moondata.snapshot import Snapshot, compute_fingerprint, write_snapshot
from moondata.stats import PRODUCT_DIRNAME, parse_removed_manifest, scan_products
from moondata.thumbnails import generate_thumbnails
from moondata.tiepoints import load_tie_points
from moondata.transform import DEFAULT_MODEL, compare_with_manifest, solve

# 尚未实现的流程步骤：子命令名 → (中文说明, 留待实现的 issue 号)
PENDING_STEPS: dict[str, tuple[str, int]] = {
    "patches": ("在正向算出的窗口上切分 patch", 10),
}
ALIGNED_RELDIR = Path("work") / "aligned"
"""`overlap` 的默认输出目录（相对仓库根，不入库）。数据盘只读，产物一律写在这边。"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="moondata",
        description="CE-2 7 m DOM × Mini-RF SAR 配准数据集的处理与自检工具。",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--data-root",
        metavar="PATH",
        help=f"影像数据根，优先于环境变量 {ENV_VAR} 与 moondata.toml。",
    )

    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser(
        "doctor",
        parents=[common],
        help="自检：数据根在哪、是否可达、与统计快照的指纹是否一致",
    )
    subcommands.add_parser(
        "scan",
        parents=[common],
        help="扫描 patch 产物，重新生成统计快照 stats/snapshot.json（读遍全部 patch，需时十来分钟）",
    )
    subcommands.add_parser(
        "pages",
        parents=[common],
        help="生成 ROI 档案页 docs/rois/*.md（只读仓库，不需要数据盘）",
    )
    subcommands.add_parser(
        "thumbnails",
        parents=[common],
        help=f"从对齐影像为每个 ROI 画缩略图，写进 {THUMBNAILS_RELDIR.as_posix()}/（读六十多 GB，需时约五分钟）",
    )
    overlap = subcommands.add_parser(
        "overlap",
        parents=[common],
        help="第一步：算重叠区，把光学与 SAR 对齐到同一像素网格（每个 ROI 约一分钟）",
    )
    overlap.add_argument("roi", help="如 ROI_35、ROI_035 或 35")
    overlap.add_argument(
        "--grid-crs",
        choices=[c.value for c in GridCrs],
        default=GridCrs.OPTICAL.value,
        help="网格用哪一侧的投影（默认 optical；ROI_34/57/58/70 当年用的是 sar）",
    )
    overlap.add_argument(
        "--resample", default=DEFAULT_RESAMPLE, help="GDAL 重采样方式（默认 cubic）"
    )
    overlap.add_argument(
        "--out", metavar="DIR", help=f"输出目录（默认 仓库根/{ALIGNED_RELDIR.as_posix()}/<ROI>）"
    )
    overlap.add_argument("--plan-only", action="store_true", help="只算网格、不写影像")
    overlap.add_argument("--verify", action="store_true", help="与窗口清单里记的历史网格对照")

    tiepoints = subcommands.add_parser(
        "tiepoints", parents=[common], help="第二步：读取仓库里的对齐控制点（不需要数据盘）"
    )
    tiepoints.add_argument("rois", nargs="+", metavar="roi")

    transform = subcommands.add_parser(
        "transform", parents=[common], help="第三步：由对齐控制点估计全局变换（不需要数据盘）"
    )
    transform.add_argument("rois", nargs="+", metavar="roi")
    transform.add_argument(
        "--model",
        choices=[m.value for m in TransformModel],
        default=DEFAULT_MODEL.value,
        help="变换模型（默认 affine，即产出现有数据集的那个）",
    )
    transform.add_argument(
        "--verify", action="store_true", help="逐窗口对照窗口清单，看是否与既有结果一致"
    )

    windows = subcommands.add_parser(
        "windows",
        parents=[common],
        help="第四步前半：正向算出窗口，写进 "
        f"{WINDOWS_RELDIR.as_posix()}/（首次每个 ROI 约两分钟，要做一对筛选影像）",
    )
    windows.add_argument("rois", nargs="+", metavar="roi")
    windows.add_argument(
        "--grid-crs",
        choices=[c.value for c in GridCrs],
        default=GridCrs.OPTICAL.value,
        help="同 overlap（ROI_34/57/58/70 当年用的是 sar）",
    )
    windows.add_argument(
        "--selection-dir",
        metavar="DIR",
        help=f"筛选影像的父目录，每 ROI 一个子目录（默认 仓库根/{SELECTION_RELDIR.as_posix()}；"
        "已有且网格对得上就复用）",
    )

    verify_windows = subcommands.add_parser(
        "verify-windows",
        parents=[common],
        help="第一级验收：正向窗口与窗口清单逐条比对（不读影像，不需要数据盘）",
    )
    verify_windows.add_argument(
        "rois", nargs="*", metavar="roi", help="默认是验收门：窗口清单里全部验证集与测试集 ROI"
    )

    for name, (description, issue) in PENDING_STEPS.items():
        # help 里就写明「尚未实现」——否则 `moondata --help` 对外承诺了本轮没有的能力。
        subcommands.add_parser(
            name, parents=[common], help=f"{description}（尚未实现，见 issue #{issue}）"
        )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _tolerate_narrow_console()
    args = build_parser().parse_args(argv)
    try:
        config = load_config(cli_data_root=args.data_root)
        if args.command == "doctor":
            return _doctor(config)
        if args.command == "scan":
            return _scan(config)
        if args.command == "pages":
            return _pages(config)
        if args.command == "thumbnails":
            return _thumbnails(config)
        if args.command == "overlap":
            return _overlap(config, args)
        if args.command == "tiepoints":
            return _tiepoints(config, args.rois)
        if args.command == "transform":
            return _transform(config, args.rois, TransformModel(args.model), args.verify)
        if args.command == "windows":
            return _windows(config, args)
        if args.command == "verify-windows":
            return _verify_windows(config, args.rois)
        return _pipeline_step(args.command, config)
    except MoonDataError as error:
        print(error, file=sys.stderr)
        return 1


def _tolerate_narrow_console() -> None:
    """本工具的输出是中文。在非中文 locale 的 Windows 上 stdout 可能是 cp1252，
    编码不了就抛 UnicodeEncodeError——自检命令因为一行说明而自己崩掉最说不过去。
    宁可把编不出的字符转义掉。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")


def _doctor(config: Config) -> int:
    report = run_doctor(config)
    print(format_report(report))
    return 0 if report.ok else 1


def _scan(config: Config) -> int:
    data_root = require_data_root(config)
    if config.repo_root is None:
        raise StatsUnavailable(
            "找不到仓库根：窗口清单与删除清单都在仓库的 data/ 下，请在仓库内运行。"
        )
    product_root = data_root / PRODUCT_DIRNAME
    if not product_root.is_dir():
        # scan_products 也会查，但那时已经白白遍历完整个数据根算了指纹
        raise StatsUnavailable(f"数据根下没有 {PRODUCT_DIRNAME}/：{data_root}")

    removed = [
        parse_removed_manifest(path.read_text(encoding="utf-8"))
        for path in config.removed_manifests()
    ]

    # 先记时间、先算指纹：快照说的是「扫描开始那一刻的数据」
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"计算数据指纹：{data_root}", file=sys.stderr)
    fingerprint = compute_fingerprint(data_root)
    stats = scan_products(
        product_root,
        removed=removed,
        window_manifests=config.window_manifests(),
        progress=lambda where: print(f"扫描 {where}", file=sys.stderr),
    )
    write_snapshot(config.snapshot_path, Snapshot(generated_at, fingerprint, stats))
    print(f"统计快照已写入 {config.snapshot_path}（{generated_at}，{fingerprint.digest}）")
    return 0


def _pages(config: Config) -> int:
    changed = generate_roi_pages(require_repo_root(config, "档案页的输入都在仓库里"))
    print(f"ROI 档案页：{len(changed)} 个文件有变动" + (f"（{'、'.join(changed)}）" if changed else ""))
    return 0


def _thumbnails(config: Config) -> int:
    data_root = require_data_root(config)
    repo_root = require_repo_root(config, "要画哪些 ROI 取自仓库里的元数据表")
    rows = dataset_rows(load_metadata(repo_root / METADATA_RELPATH))
    out_dir = repo_root / THUMBNAILS_RELDIR
    manifest = generate_thumbnails(
        data_root,
        {row.roi: row.raw_name for row in rows},
        out_dir,
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        progress=lambda where: print(f"读取 {where}", file=sys.stderr),
    )
    print(f"缩略图已写入 {out_dir}：{len(manifest['rois'])} 个 ROI")
    for roi, paths in manifest["missing"].items():
        print(f"  {roi} 没有对齐影像：{'、'.join(paths)}")
    print("接着跑 `quarto render`，档案页会按新的缩略图清单重新生成。")
    return 0


def _overlap(config: Config, args: argparse.Namespace) -> int:
    data_root = require_data_root(config)
    sources = locate_sources(data_root, _roi_arg(args.roi))
    plan = plan_alignment(sources, GridCrs(args.grid_crs))
    grid = plan.grid
    print(f"{sources.roi}：光学 {len(sources.optical_tiles)} 幅分幅 + SAR {sources.sar.name}")
    for tile in plan.corrected_tiles:
        print(f"  {tile.name} 头里的 lat_ts 写错，读取时已按纬度带纠正（源文件未改动）")
    print(
        f"  网格：{grid.width}×{grid.height}，像元 {grid.resolution} m，"
        f"原点 ({grid.origin_x:.6f}, {grid.origin_y:.6f})，坐标系取自 {plan.reference.name}"
    )

    status = 0
    if args.verify:
        historical = _manifest_roi(config, sources.roi)
        if historical is None:
            status = 1
        else:
            problems = grid_differences(grid, historical.grid)
            verdict = "一致" if not problems else "不一致——" + "；".join(problems)
            print(f"  与窗口清单里的历史网格：{verdict}")
            status = 1 if problems else 0
    if args.plan_only:
        return status

    if args.out:
        out_dir = Path(args.out)
    else:
        repo_root = require_repo_root(config, "默认输出目录在仓库里（或用 --out 指定）")
        out_dir = repo_root / ALIGNED_RELDIR / sources.roi
    print(f"  重采样（{args.resample}）→ {out_dir}", file=sys.stderr)
    align(plan, out_dir, resample=args.resample)
    print(f"  已写出 {out_dir / 'opt.tif'}、{out_dir / 'sar.tif'}，两幅都已核对落在规划的网格上")
    return status


def _tiepoints(config: Config, rois: Sequence[str]) -> int:
    repo_root = require_repo_root(config, "对齐控制点在仓库的 data/tie-points/ 下")
    for roi in rois:
        points = load_tie_points(repo_root, _roi_arg(roi))
        path = points.path.relative_to(repo_root).as_posix()
        print(f"{points.roi}：{len(points.optical)} 对（{path}）")
        for name, xy in (("光学", points.optical), ("SAR ", points.sar)):
            print(
                f"  {name} 列 {xy[:, 0].min():.1f}–{xy[:, 0].max():.1f}，"
                f"行 {xy[:, 1].min():.1f}–{xy[:, 1].max():.1f}"
            )
    return 0


def _transform(config: Config, rois: Sequence[str], model: TransformModel, verify: bool) -> int:
    repo_root = require_repo_root(config, "对齐控制点在仓库的 data/tie-points/ 下")
    status = 0
    for roi in rois:
        solved = solve(load_tie_points(repo_root, _roi_arg(roi)), model)
        path = solved.tie_points.path.relative_to(repo_root).as_posix()
        print(
            f"{solved.roi}：{model.value}，{len(solved.tie_points.optical)} 对点，"
            f"拟合残差 RMSE {solved.rmse:.2f} px（{path}）"
        )
        for row in solved.matrix:
            print("  [" + "  ".join(f"{v: .10g}" for v in row) + "]")
        if not verify:
            continue
        historical = _manifest_roi(config, solved.roi)
        if historical is None:
            status = 1
            continue
        result = compare_with_manifest(solved, historical)
        spread = (
            f"偏差 x [{result.dx_range[0]:.2f}, {result.dx_range[1]:.2f}]、"
            f"y [{result.dy_range[0]:.2f}, {result.dy_range[1]:.2f}] px"
        )
        if result.consistent:
            print(f"  与窗口清单一致（{result.split}，{result.windows} 个窗口，{spread}，在取整误差内）")
            continue
        status = 1
        print(
            f"  与窗口清单不一致（{result.split}）：{result.windows} 个窗口里 "
            f"{len(result.outliers)} 个超出取整误差，{spread}"
        )
        for outlier in result.outliers[:5]:
            print(f"    patch_{outlier.index}：偏差 x {outlier.dx:+.2f}、y {outlier.dy:+.2f} px")
    return status


def _windows(config: Config, args: argparse.Namespace) -> int:
    data_root = require_data_root(config)
    repo_root = require_repo_root(config, "对齐控制点在仓库里，正向结果也写在仓库的 work/ 下")
    splits = {row.roi: row.split for row in load_metadata(repo_root / METADATA_RELPATH)}
    selection_root = Path(args.selection_dir) if args.selection_dir else repo_root / SELECTION_RELDIR
    for roi in args.rois:
        solved = solve(load_tie_points(repo_root, _roi_arg(roi)))
        plan = plan_alignment(locate_sources(data_root, solved.roi), GridCrs(args.grid_crs))
        grid = plan.grid
        print(f"{solved.roi}：网格 {grid.width}×{grid.height}，{solved.model.value} 变换 RMSE {solved.rmse:.2f} px")

        selection = selection_root / solved.roi
        if has_selection(plan, selection):
            print(f"  复用筛选影像 {selection}")
        else:
            print(f"  做筛选影像（光学一次、SAR 两次最近邻）→ {selection}", file=sys.stderr)
            align_selection(plan, selection)

        geometric = plan_windows((grid.width, grid.height), (grid.width, grid.height), solved.matrix, PATCH_SIZE)
        kept = select_windows(geometric, selection / "opt.tif", selection / "sar.tif")
        tiled = len(geometric.windows) + geometric.out_of_bounds + geometric.low_overlap
        print(
            f"  铺 {tiled} 个窗口：SAR 出界 {geometric.out_of_bounds}、重叠不足 "
            f"{geometric.low_overlap}、含 nodata {len(geometric.windows) - len(kept)}，留下 {len(kept)} 个"
        )
        out = repo_root / WINDOWS_RELDIR / f"{solved.roi}.json"
        write_window_manifest(
            out,
            ManifestRoi(solved.roi, splits.get(solved.roi, ""), PATCH_SIZE, grid, kept),
            provenance={
                "tie_points": solved.tie_points.path.relative_to(repo_root).as_posix(),
                "model": solved.model.value,
                "matrix": solved.matrix.tolist(),
                "grid_crs": plan.grid_crs.value,
                "discarded": {
                    "out_of_bounds": geometric.out_of_bounds,
                    "low_overlap": geometric.low_overlap,
                    "nodata": len(geometric.windows) - len(kept),
                },
            },
        )
        print(f"  已写出 {out}")
    return 0


GATE_SPLITS = ("Val", "Test")
"""第一级验收设门的划分：它们的 patch 上有人工评测真值点，窗口一变就全部作废。"""
MAX_LISTED = 5


def _verify_windows(config: Config, rois: Sequence[str]) -> int:
    repo_root = require_repo_root(config, "窗口清单与正向结果都在仓库里")
    manifests = load_window_manifests(config.window_manifests())
    forward = load_window_manifests(sorted((repo_root / WINDOWS_RELDIR).glob("*.json")))
    targets = (
        [_roi_arg(r) for r in rois]
        if rois
        else sorted(r for r, m in manifests.items() if m.split in GATE_SPLITS)
    )
    passed = 0
    for roi in targets:
        if roi not in manifests:
            print(f"{roi}：窗口清单里没有它，无从比对")
            continue
        if roi not in forward:
            print(f"{roi}：还没有正向结果，先跑 `moondata windows {roi}`")
            continue
        result = compare_windows(forward[roi], manifests[roi])
        if result.consistent:
            passed += 1
            print(f"{roi}（{manifests[roi].split}）：{result.windows} 个窗口逐条一致")
            continue
        print(
            f"{roi}（{manifests[roi].split}）：不一致——正向 {result.forward_windows} 个、"
            f"清单 {result.windows} 个，第一个对不上的是 patch_{result.first_divergence}"
        )
        for problem in result.grid_differences:
            print(f"  网格：{problem}")
        for label, extra in (("正向多出", result.only_forward), ("正向缺少", result.only_manifest)):
            for w in extra[:MAX_LISTED]:
                print(f"  {label} patch_{w.index}：光学 {w.optical}、SAR {w.sar}")
        if result.renumbered:
            first, last = result.renumbered[0], result.renumbered[-1]
            print(
                f"  {len(result.renumbered)} 个窗口位置相同、编号变了"
                f"（清单 patch_{first[0]} → 正向 patch_{first[1]} … patch_{last[0]} → patch_{last[1]}）"
            )
        for m in result.mismatches[:MAX_LISTED]:
            print(
                f"  patch_{m.index}：光学差 ({m.optical_offset[0]:+d}, {m.optical_offset[1]:+d})、"
                f"SAR 差 ({m.sar_offset[0]:+d}, {m.sar_offset[1]:+d}) px（正向减清单）"
            )
        if len(result.mismatches) > MAX_LISTED:
            print(f"  ……同编号位置不同的共 {len(result.mismatches)} 个")
    print(f"逐条一致 {passed}/{len(targets)} 个 ROI")
    return 0 if passed == len(targets) else 1


def _manifest_roi(config: Config, roi: str) -> ManifestRoi | None:
    manifests = load_window_manifests(config.window_manifests())
    if roi not in manifests:
        print(f"  窗口清单里没有 {roi}，无从对照")
        return None
    return manifests[roi]


def _roi_arg(text: str) -> str:
    """命令行里的 ROI：`ROI_35`、`ROI_035`、`35` 都行。"""
    text = text.strip()
    return padded_roi(f"ROI_{text}" if text.isdigit() else text)


def _pipeline_step(command: str, config: Config) -> int:
    require_data_root(config)
    description, issue = PENDING_STEPS[command]
    raise NotImplementedYet(f"`{command}`（{description}）尚未实现，见 issue #{issue}。")


def require_data_root(config: Config) -> Path:
    """凡是要读影像的命令在动手之前调用它，返回可达的数据根。只 stat，不算指纹。"""
    reachability = probe_data_root(config.data_root)
    if reachability is Reachability.REACHABLE and config.data_root is not None:
        return config.data_root
    raise DataRootUnavailable(
        f"本命令需要读取影像，但数据根{reachability.value}："
        f"{config.data_root if config.data_root else '（未设置）'}\n"
        f"用 `moondata doctor` 查看完整自检报告。"
    )


def require_repo_root(config: Config, why: str) -> Path:
    if config.repo_root is None:
        raise RepoRootNotFound(f"找不到仓库根：{why}，请在仓库内运行。")
    return config.repo_root


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
