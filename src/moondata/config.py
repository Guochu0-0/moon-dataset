"""读 `config.toml`——全部参数的唯一来源。

只有这一层：没有环境变量、没有命令行开关、没有本机私有的配置文件。两个编号脚本的
唯一命令行参数是 ROI 列表，所以「换一台机器要改哪里」只有一个答案——仓库根的
`config.toml`。它入库，因此配置的改动也有历史。

数据根写的是本机挂载点，换机器要改它。相对路径按 `config.toml` 所在目录解析，
整个仓库搬走也不失效。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from moondata.errors import ConfigUnreadable, DataRootUnavailable

CONFIG_FILENAME = "config.toml"
REPO_ROOT = Path(__file__).resolve().parents[2]
"""本包随仓库走（`pip install -e .`），所以仓库根由模块位置定出，不必再配一遍。"""


@dataclass(frozen=True)
class Config:
    repo_root: Path
    """`config.toml` 所在的目录。控制点、元数据表、文档素材都在它下面。"""
    data_root: Path
    """原始输入与既有成品所在的盘。**代码只读它。**"""
    work_root: Path
    """两个脚本的产物写在这里。"""
    patch_size: int
    resample: str
    grid_crs: dict[str, str]
    """ROI（补零写法）→ 网格坐标系取自谁。只列出例外，其余取光学分幅的投影。"""

    def overlap_dir(self, roi: str) -> Path:
        return self.work_root / "01_overlap" / roi

    def patches_dir(self, split: str, roi: str) -> Path:
        return self.work_root / "02_patches" / split / roi

    def require_data_root(self) -> Path:
        """读影像之前调用：盘没挂上就干净地报一句，而不是让 GDAL 抛一串英文。"""
        if not self.data_root.is_dir():
            raise DataRootUnavailable(
                f"数据根不是一个目录：{self.data_root}（改 {self.repo_root / CONFIG_FILENAME} 里的 data_root）"
            )
        return self.data_root


def load_config(path: Path | None = None) -> Config:
    path = path if path is not None else REPO_ROOT / CONFIG_FILENAME
    try:
        with path.open("rb") as stream:
            document = tomllib.load(stream)
    except (tomllib.TOMLDecodeError, OSError) as error:
        raise ConfigUnreadable(f"配置文件读不动：{path}（{error}）") from error

    base = path.parent
    grid_crs = _table(document, path, "grid_crs")
    for roi, value in grid_crs.items():
        if value != "sar":
            raise ConfigUnreadable(f"{path} 的 [grid_crs] {roi} 只能是 \"sar\"，实际是 {value!r}")
    return Config(
        repo_root=base,
        data_root=_path(document, path, "data_root", base),
        work_root=_path(document, path, "work_root", base),
        patch_size=_int(document, path, "patch_size"),
        resample=_str(document, path, "resample"),
        grid_crs=grid_crs,
    )


def _value(document: dict[str, object], path: Path, key: str) -> object:
    try:
        return document[key]
    except KeyError:
        raise ConfigUnreadable(f"{path} 里缺少 {key}") from None


def _str(document: dict[str, object], path: Path, key: str) -> str:
    value = _value(document, path, key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigUnreadable(f"{path} 的 {key} 应为非空字符串，实际是 {value!r}")
    return value


def _int(document: dict[str, object], path: Path, key: str) -> int:
    value = _value(document, path, key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigUnreadable(f"{path} 的 {key} 应为正整数，实际是 {value!r}")
    return value


def _path(document: dict[str, object], path: Path, key: str, base: Path) -> Path:
    value = Path(_str(document, path, key)).expanduser()
    return value if value.is_absolute() else (base / value).resolve()


def _table(document: dict[str, object], path: Path, key: str) -> dict[str, str]:
    value = document.get(key, {})
    if not isinstance(value, dict):
        raise ConfigUnreadable(f"{path} 的 {key} 不是一个表")
    return dict(value)
