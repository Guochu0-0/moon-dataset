"""第二级验收：切出来的 patch 与现有产物比，回答三个问题，**次序固定、不可颠倒**。

1. **位置有没有变？** 新 patch 的地理坐标是否仍落在窗口清单记录的窗口上。变了就意味着
   人工评测真值点全部作废，是最严重的失败。
2. **有没有丢数据？** 历史对齐影像有效、新对齐影像却是无效值的像素占比。不为零说明
   源影像不全——旧工具实测抓到过一例：某 ROI 当年用的光学分幅已不在盘上，现存分幅
   只覆盖六成，而**单看「跑完没报错」完全看不出来**。
3. **网纹消了没有？** 逐行梯度的自相关最强周期。最近邻把 7.0 m 重采样到 7.5 m 会锁在
   14 像素；干净的产物落在 2 附近。

前两项是正确性，第三项是改进目标——网纹修得再干净，位置错了或数据丢了都是白搭。
三项之后才是本票的门槛：光学与 SAR 两个文件都与现有产物**逐字节一致**。

判据继承自旧代码里的新旧产物比对工具（`lunar_benchmark/tools/compare_to_legacy.py`），
没有重新设计：位置容差 1e-6 像素、丢数据超过 0.1% 算失败、网纹看光学第 1 波段且
每 8 个 patch 抽 1 个、周期 14 的占比超过 5% 算「网纹仍在」、相关系数低于 0.90 算
「内容不符」。改动只有三处，都不动判据本身：

- 位置换算用窗口清单里的网格（就是当年那幅对齐影像的网格），不再打开旧对齐影像；
  光学与 SAR 两侧都查，旧工具只查光学。
- 丢数据逐像素算全幅，不再抽 40 段——抽样当年只为省时间。
- 网纹**只记录、不判失败**：本轮不因它修改数据（数据集已冻结），而逐字节一致的产物
  必然带着与现有产物一样的网纹。

只读，不要 GDAL：patch 与对齐影像都经 `moondata.tiff` 读。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from moondata.errors import GridMismatch
from moondata.geometry import PixelGrid
from moondata.manifest import ManifestRoi
from moondata.patches import OPTICAL_DIRNAME, SAR_DIRNAME
from moondata.tiff import TiffInfo, iter_blocks, read_info, read_tiff

LATTICE_PERIOD = 14
"""7.0 m → 7.5 m 最近邻重采样的固有周期（行）。"""
LATTICE_SAMPLE_EVERY = 8
"""网纹每几个 patch 抽一个算——逐行自相关不便宜，旧工具就这么抽。"""
MAX_LATTICE_SHARE = 0.05
"""抽到的 patch 里周期为 14 的超过这个比例，就报「网纹仍在」。"""
MAX_LOST = 0.001
"""丢数据的像素占比超过它算失败。"""
MIN_CORRELATION = 0.90
"""字节不同的 patch 与旧 patch 的像素相关系数低于它，计入「内容不符」。"""
POSITION_TOLERANCE = 1e-6
"""像素。"""


def lattice_period(patch: np.ndarray) -> int:
    """逐行梯度剖面的自相关最强周期（在 2–59 行里找）。常数块返回 0。"""
    profile = np.abs(np.diff(patch.astype(np.float64), axis=0)).mean(axis=1)
    profile -= profile.mean()
    auto = np.correlate(profile, profile, "full")[len(profile) - 1 :]
    if auto[0] == 0:
        return 0
    auto /= auto[0]
    lags = np.arange(2, 60)
    return int(lags[np.argmax(auto[2:60])])


def lost_coverage(legacy: Path, new: Path) -> tuple[int, int]:
    """(历史有效、新图无效的像素数, 历史有效的像素数)。看第 1 波段，「有效」即 > 0。

    两幅对齐影像落在同一网格、同样分块，逐块对着比，不整幅进内存。
    """
    lost = valid = 0
    for (top, left, old), (top2, left2, fresh) in zip(iter_blocks(legacy), iter_blocks(new), strict=True):
        if (top, left, old.shape) != (top2, left2, fresh.shape):
            raise GridMismatch(f"两幅对齐影像的分块对不上，无从逐像素比：{legacy} 与 {new}")
        a, b = old[:, :, 0] > 0, fresh[:, :, 0] > 0
        valid += int(a.sum())
        lost += int((a & ~b).sum())
    return lost, valid


def patch_position(info: TiffInfo, grid: PixelGrid) -> tuple[float, float]:
    """patch 左上角在 `grid` 上的像素位置 (列, 行)，由它自带的地理坐标算出。"""
    if info.origin is None:
        return (math.nan, math.nan)
    x, y = info.origin
    return ((x - grid.origin_x) / grid.resolution, (grid.origin_y - y) / grid.resolution)


@dataclass
class ProductComparison:
    roi: str
    split: str
    patches: int
    """窗口清单里的窗口数。"""
    missing: list[int] = field(default_factory=list)
    """新产物缺了光学或 SAR 的编号。"""
    misplaced: list[int] = field(default_factory=list)
    lost_pixels: int | None = None
    """`None`：两幅对齐影像缺了一幅，无从比对。"""
    valid_pixels: int = 0
    old_periods: list[int] = field(default_factory=list)
    new_periods: list[int] = field(default_factory=list)
    identical: int = 0
    """光学与 SAR 两个文件都逐字节相同的 patch 对数。"""
    mismatched: list[int] = field(default_factory=list)
    """字节不同、且相关系数低于 `MIN_CORRELATION` 的编号。"""

    @property
    def lost(self) -> float:
        if self.lost_pixels is None:
            return math.nan
        return self.lost_pixels / max(self.valid_pixels, 1)

    @property
    def old_lattice_share(self) -> float:
        return _share(self.old_periods)

    @property
    def new_lattice_share(self) -> float:
        return _share(self.new_periods)

    @property
    def lattice_remains(self) -> bool:
        return self.new_lattice_share > MAX_LATTICE_SHARE

    def problems(self) -> list[str]:
        """不通过的理由，按检查次序排。网纹不在其中——它只记录。"""
        found = []
        if self.missing:
            found.append(f"缺 {len(self.missing)} 个")
        if self.misplaced:
            found.append(f"位置错 {len(self.misplaced)} 个")
        if self.lost_pixels is None:
            found.append("对齐影像不全，无从查丢数据")
        elif self.lost > MAX_LOST:
            found.append(f"丢数据 {self.lost:.1%}")
        if self.mismatched:
            found.append(f"内容不符 {len(self.mismatched)} 个")
        if self.identical < self.patches:
            found.append(f"{self.patches - self.identical} 对不是逐字节一致")
        return found


def compare_products(
    manifest: ManifestRoi,
    legacy_dir: Path,
    new_dir: Path,
    legacy_aligned: Path,
    new_aligned: Path,
) -> ProductComparison:
    """一个 ROI 的新产物（`new_dir`）对照现有产物（`legacy_dir`），两者都是
    `<划分>/<ROI>/` 那一层，下面有 `Optical/` 与 `SAR/`。"""
    result = ProductComparison(manifest.roi, manifest.split, len(manifest.windows))
    present = []

    # 1. 位置
    for position, window in enumerate(manifest.windows):
        name = f"patch_{window.index}.tif"
        pairs = [(legacy_dir / kind / name, new_dir / kind / name, corner)
                 for kind, corner in ((OPTICAL_DIRNAME, window.optical), (SAR_DIRNAME, window.sar))]
        if not all(new.is_file() for _, new, _ in pairs):
            result.missing.append(window.index)
            continue
        present.append((position, window, pairs))
        for _, new, corner in pairs:
            col, row = patch_position(read_info(new), manifest.grid)
            if not (abs(col - corner[0]) <= POSITION_TOLERANCE and abs(row - corner[1]) <= POSITION_TOLERANCE):
                result.misplaced.append(window.index)
                break

    # 2. 数据完整性
    if legacy_aligned.is_file() and new_aligned.is_file():
        result.lost_pixels, result.valid_pixels = lost_coverage(legacy_aligned, new_aligned)

    # 3. 网纹，以及逐字节
    for position, window, pairs in present:
        same = [old.is_file() and old.read_bytes() == new.read_bytes() for old, new, _ in pairs]
        if all(same):
            result.identical += 1
        sample = position % LATTICE_SAMPLE_EVERY == 0
        if not sample and all(same):
            continue
        old_optical, new_optical = (_band1(p) for p in pairs[0][:2])
        if sample:
            if old_optical is not None:
                result.old_periods.append(lattice_period(old_optical))
            result.new_periods.append(lattice_period(new_optical))
        if not all(same) and _correlation(old_optical, new_optical) < MIN_CORRELATION:
            result.mismatched.append(window.index)
    return result


def _band1(path: Path) -> np.ndarray | None:
    if not path.is_file():
        return None
    return read_tiff(path)[1][:, :, 0]


def _correlation(a: np.ndarray | None, b: np.ndarray | None) -> float:
    """旧工具只在两块都不是常数时算相关；算不了的不计入「内容不符」。"""
    if a is None or b is None or a.shape != b.shape:
        return 0.0
    if a.std() == 0 or b.std() == 0:
        return 1.0
    return float(np.corrcoef(a.ravel().astype(float), b.ravel().astype(float))[0, 1])


def _share(periods: list[int]) -> float:
    return float(np.mean(np.array(periods) == LATTICE_PERIOD)) if periods else 0.0
