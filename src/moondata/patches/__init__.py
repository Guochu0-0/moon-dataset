"""第四步：正向算出窗口并切分 patch。

**正向**是本项目的核心技术要求：不读取任何历史产物的位置信息，独立地从对齐控制点
算出变换、算出窗口、切出 patch。验收分两级——窗口坐标与 `data/windows/` 中的既有
窗口清单逐条相等（第一级，本模块）；切出的 patch 与现有产物逐字节一致（第二级，issue #10）。

窗口怎么来
----------
1. **几何**（`moondata.geometry.plan_windows`，不读影像）：从原点铺光学窗口、按全局变换
   定 SAR 窗口、丢掉出界与重叠不足的。
2. **像素**（`usable_pair`，要读影像）：两块 patch 里只要有一个像素是 0，这一对就丢掉。
3. 留下的按铺窗顺序从 0 编号——编号就是 `patch_<n>` 的 n，评测真值点绑在它上面。
   **第 2 步丢错一个，其后全部编号错位。**

第 2 步看的是哪一版影像
-----------------------
**当年切片时的那一版**：光学一次最近邻 warp，SAR 两次最近邻 warp（先重投影落临时文件，
再裁切降采样）。数据盘上现在的对齐影像已按 cubic 重做过（去网纹），nodata 边缘与当年
差一两个像素，拿它判「有没有 0」，贴边的窗口就会多留几个（验证/测试集上实测 11 个），
编号随之错位。所以像素检查用 `overlap.align_selection` 按当年做法从原始输入重做一版
**筛选影像**——它只用来决定窗口留不留，patch 的像素仍取 cubic 那版（issue #10）。
这不是按 ROI 写的特例：全部 ROI 走同一套做法。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from moondata import raster
from moondata.geometry import WindowPlan
from moondata.manifest import ManifestRoi, ManifestWindow

NODATA = 0
"""两边都按 0 判。光学是当年硬写的 `nodata = 0`（不看文件头）；SAR 是文件头里的 nodata，
当年的对齐影像写的就是 0。"""


PATCH_SIZE = 512
WINDOWS_RELDIR = Path("work") / "windows"
"""正向算出的窗口写在这里（相对仓库根，不入库），每 ROI 一个 `<ROI>.json`，格式同窗口清单。"""
SELECTION_RELDIR = Path("work") / "selection"
"""筛选影像的默认位置（相对仓库根，不入库）。每 ROI 约 1 GB，做一次约一两分钟，之后复用。"""


def select_windows(
    plan: WindowPlan, optical_path: Path, sar_path: Path, size: int = PATCH_SIZE
) -> list[ManifestWindow]:
    """几何上站得住的窗口逐个过像素检查，留下的按顺序编号。读的是筛选影像。"""
    backend = raster.backend()
    optical_blocks = backend.read_blocks(optical_path, [w.optical for w in plan.windows], size)
    sar_blocks = backend.read_blocks(sar_path, [w.sar for w in plan.windows], size)
    kept: list[ManifestWindow] = []
    for pair, optical, sar in zip(plan.windows, optical_blocks, sar_blocks):
        if usable_pair(optical, sar):
            kept.append(ManifestWindow(len(kept), pair.optical, pair.sar))
    return kept


def usable_pair(optical: np.ndarray, sar: np.ndarray) -> bool:
    """一对 patch 能不能进数据集：任一边、任一波段、任一像素等于 0 就不能。

    SAR 有大量负值，那是真实数据；只有恰好等于 0 才算 nodata。
    """
    return not (np.any(optical == NODATA) or np.any(sar == NODATA))


@dataclass(frozen=True)
class WindowMismatch:
    index: int
    optical_offset: tuple[int, int]
    sar_offset: tuple[int, int]
    """正向减清单（像素）。"""


@dataclass(frozen=True)
class WindowComparison:
    roi: str
    windows: int
    """清单里的窗口数。"""
    forward_windows: int
    grid_differences: list[str]
    mismatches: list[WindowMismatch] = field(default_factory=list)
    """同一编号、位置不同。"""
    only_forward: list[ManifestWindow] = field(default_factory=list)
    """光学位置在清单里找不到的正向窗口（带正向编号）。"""
    only_manifest: list[ManifestWindow] = field(default_factory=list)
    renumbered: list[tuple[int, int]] = field(default_factory=list)
    """同一光学位置、编号不同：(清单编号, 正向编号)。"""
    first_divergence: int | None = None
    """第一个对不上的编号；`None` 即逐条相等。"""

    @property
    def consistent(self) -> bool:
        return self.windows > 0 and self.first_divergence is None and not self.grid_differences


def compare_windows(forward: ManifestRoi, manifest: ManifestRoi) -> WindowComparison:
    """第一级验收：正向结果与窗口清单逐条比对。

    按编号比位置（编号是评测真值点的钥匙）；另按光学位置配对，把多出来、少掉、改了编号的
    窗口单独点名——多出一个窗口会让其后全部编号错位，按编号比出来的一长串偏差只是它的
    回声，读报告要先看这几项。反过来，网格原点差一个像素时光学位置一个也配不上，
    那时按编号比出来的偏差（整齐的一个像素）才是线索。
    """
    ours = {w.index: w for w in forward.windows}
    theirs = {w.index: w for w in manifest.windows}
    mismatches, divergent = [], []
    for index in sorted(ours.keys() | theirs.keys()):
        a, b = ours.get(index), theirs.get(index)
        if a is None or b is None:
            divergent.append(index)
        elif (a.optical, a.sar) != (b.optical, b.sar):
            divergent.append(index)
            mismatches.append(WindowMismatch(index, _offset(a.optical, b.optical), _offset(a.sar, b.sar)))

    ours_by_position = {w.optical: w for w in forward.windows}
    theirs_by_position = {w.optical: w for w in manifest.windows}
    renumbered = sorted(
        (w.index, ours_by_position[w.optical].index)
        for w in manifest.windows
        if w.optical in ours_by_position and ours_by_position[w.optical].index != w.index
    )
    return WindowComparison(
        roi=manifest.roi,
        windows=len(manifest.windows),
        forward_windows=len(forward.windows),
        grid_differences=forward.grid.differences(manifest.grid),
        mismatches=mismatches,
        only_forward=[w for w in forward.windows if w.optical not in theirs_by_position],
        only_manifest=[w for w in manifest.windows if w.optical not in ours_by_position],
        renumbered=renumbered,
        first_divergence=divergent[0] if divergent else None,
    )


def _offset(a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int]:
    return (a[0] - b[0], a[1] - b[1])
