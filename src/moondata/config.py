"""数据根与快照路径的解析。

955 GB 影像在一块移动硬盘上，不同机器、不同时刻挂载在不同盘符，所以数据根必须
可配置。三层来源按以下优先级取第一个给出非空值的：

1. 命令行 `--data-root`
2. 环境变量 `MOONDATA_DATA_ROOT`
3. 仓库根的 `moondata.toml` 中的 `[data] root`

都没有给则为「未设置」。这在库层面不是异常——文档渲染、统计快照分析本来就不需要
数据根。但 `moondata doctor` 会以退出码 1 结束：它的职责是回答「数据在不在」，
而未设置时它答不上来。

`moondata.toml` 写的是本机路径，因此它不入库；仓库里提交的是 `moondata.toml.example`。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from moondata.errors import ConfigUnreadable

ENV_VAR = "MOONDATA_DATA_ROOT"
CONFIG_FILENAME = "moondata.toml"
REPO_MARKER = ".git"
SNAPSHOT_RELPATH = Path("stats") / "snapshot.json"


class DataRootSource(Enum):
    """数据根最终由哪一层给出。自检命令要报告它——否则「为什么是这个路径」无从回答。"""

    CLI = "命令行 --data-root"
    ENV = f"环境变量 {ENV_VAR}"
    CONFIG_FILE = f"配置文件 {CONFIG_FILENAME}"
    UNSET = "未设置"


@dataclass(frozen=True)
class Config:
    data_root: Path | None
    data_root_source: DataRootSource
    data_root_origin: str | None
    """给出该值的具体位置：配置文件的绝对路径、或环境变量名。未设置时为 None。"""
    repo_root: Path | None
    snapshot_path: Path


def load_config(
    *,
    cli_data_root: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    start: Path | None = None,
) -> Config:
    """按优先级解析配置。`start` 是向上搜索 `moondata.toml` 的起点，默认当前工作目录。"""
    if env is None:
        env = os.environ
    start = Path(start) if start is not None else Path.cwd()

    repo_root = find_repo_root(start)
    config_path = find_config_file(start)
    file_root = _read_config_root(config_path) if config_path is not None else None

    # 每层各带自己的相对路径基准：命令行与环境变量是当场敲的，按工作目录解析；
    # 配置文件里写的路径按该文件所在目录解析，这样仓库整个搬走也不失效。
    root, source, origin, base = _first_non_empty(
        (cli_data_root, DataRootSource.CLI, None, start),
        (env.get(ENV_VAR), DataRootSource.ENV, ENV_VAR, start),
        (
            file_root,
            DataRootSource.CONFIG_FILE,
            str(config_path) if config_path else None,
            config_path.parent if config_path else start,
        ),
    )

    return Config(
        data_root=_normalise(root, base) if root is not None else None,
        data_root_source=source,
        data_root_origin=origin,
        repo_root=repo_root,
        snapshot_path=(repo_root or start) / SNAPSHOT_RELPATH,
    )


def find_repo_root(start: Path) -> Path | None:
    """从 `start` 向上找带 `.git` 的目录。"""
    for directory in (start, *start.parents):
        if (directory / REPO_MARKER).exists():
            return directory
    return None


def find_config_file(start: Path) -> Path | None:
    """从 `start` 向上找 `moondata.toml`，**搜索到仓库根为止**。

    不越过仓库根，否则把仓库挪到一个恰好有同名文件的父目录下，行为就悄悄变了。
    """
    repo_root = find_repo_root(start)
    for directory in (start, *start.parents):
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
        if repo_root is not None and directory == repo_root:
            return None
    return None


def _read_config_root(config_path: Path) -> str | None:
    try:
        with config_path.open("rb") as stream:
            document = tomllib.load(stream)
    except (tomllib.TOMLDecodeError, OSError) as error:
        raise ConfigUnreadable(f"配置文件读不动：{config_path}（{error}）") from error

    data = document.get("data", {})
    if not isinstance(data, dict):
        raise ConfigUnreadable(f"配置文件 {config_path} 的 [data] 不是一个表")
    root = data.get("root")
    if root is not None and not isinstance(root, str):
        raise ConfigUnreadable(f"配置文件 {config_path} 的 [data] root 不是字符串")
    return root


def _first_non_empty(
    *candidates: tuple[str | Path | None, DataRootSource, str | None, Path],
) -> tuple[str | Path | None, DataRootSource, str | None, Path]:
    for value, source, origin, base in candidates:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue  # 空环境变量按「没设」处理，而不是按「设成了空路径」
        return value, source, origin, base
    return None, DataRootSource.UNSET, None, Path.cwd()


def _normalise(value: str | Path, base: Path) -> Path:
    """展开 `~`，并把相对路径按其来源所在目录解析。"""
    path = Path(str(value).strip()).expanduser()
    return path if path.is_absolute() else (base / path).resolve()
