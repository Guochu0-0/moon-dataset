"""命令行入口。

子命令分两类，区别只在**要不要读影像**：

- **只读自检/查询**：`doctor`。移动硬盘没插照样跑完并给出报告。
- **只读仓库的生成**：`pages`，按仓库里的元数据表、统计快照、缩略图清单与已知问题清单
  生成 ROI 档案页。不碰数据盘，`quarto render` 前自动跑。
- **要读影像的**：四步流程 `overlap` / `tiepoints` / `transform` / `patches`（与包的顶层
  模块一一对应），读遍 patch 产物、写出统计快照的 `scan`，以及从对齐影像画 ROI
  缩略图的 `thumbnails`。
  它们进门第一件事是检查数据根，不可达就干净地退出。

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
from moondata.metadata import load_metadata
from moondata.roipages import generate as generate_roi_pages
from moondata.snapshot import Snapshot, compute_fingerprint, write_snapshot
from moondata.stats import PRODUCT_DIRNAME, parse_removed_manifest, scan_products
from moondata.thumbnails import generate_thumbnails

# 四步流程：子命令名 → (中文说明, 留待实现的 issue 号)
PIPELINE_STEPS: dict[str, tuple[str, int]] = {
    "overlap": ("计算光学与 SAR 的重叠区", 8),
    "tiepoints": ("读取并规范化对齐控制点", 8),
    "transform": ("由对齐控制点估计全局变换", 8),
    "patches": ("正向算出窗口并切分 patch", 10),
}


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
    for name, (description, issue) in PIPELINE_STEPS.items():
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
    rows = load_metadata(repo_root / METADATA_RELPATH)
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


def _pipeline_step(command: str, config: Config) -> int:
    require_data_root(config)
    description, issue = PIPELINE_STEPS[command]
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
