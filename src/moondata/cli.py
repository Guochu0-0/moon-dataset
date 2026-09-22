"""命令行入口。

子命令分两类，区别只在**要不要读影像**：

- **只读自检/查询**：`doctor`。移动硬盘没插照样跑完并给出报告。
- **四步流程**：`overlap` / `tiepoints` / `transform` / `patches`，与包的顶层模块一一对应。
  它们必须读影像，所以进门第一件事是检查数据根，不可达就干净地退出。

预期内的错误一律渲染成一行中文并以退出码 1 结束，不打印 traceback。
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from moondata.config import ENV_VAR, Config, load_config
from moondata.doctor import Reachability, format_report, run_doctor
from moondata.errors import DataRootUnavailable, MoonDataError, NotImplementedYet

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
    for name, (description, _issue) in PIPELINE_STEPS.items():
        subcommands.add_parser(name, parents=[common], help=description)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _tolerate_narrow_console()
    args = build_parser().parse_args(argv)
    try:
        config = load_config(cli_data_root=args.data_root)
        if args.command == "doctor":
            return _doctor(config)
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


def _pipeline_step(command: str, config: Config) -> int:
    require_data_root(config)
    description, issue = PIPELINE_STEPS[command]
    raise NotImplementedYet(f"`{command}`（{description}）尚未实现，见 issue #{issue}。")


def require_data_root(config: Config) -> None:
    """凡是要读影像的命令在动手之前调用它。"""
    report = run_doctor(config)
    if report.reachability is Reachability.REACHABLE:
        return
    raise DataRootUnavailable(
        f"本命令需要读取影像，但数据根{report.reachability.value}："
        f"{config.data_root if config.data_root else '（未设置）'}\n"
        f"用 `moondata doctor` 查看完整自检报告。"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
