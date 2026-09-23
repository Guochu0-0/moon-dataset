"""第二步：对齐控制点——读取人工在 ENVI 中标注的 `.pts`。

**对齐控制点（alignment tie points）** 标在整幅对齐影像上，每 ROI 约 30 对，
用于解算全局变换、决定 patch 切在何处。它与 patch 旁边的 **评测真值点
（evaluation ground truth）** 是两种东西，本包只管前者。

读的是仓库里 `data/tie-points/` 的副本，不是数据盘上的原件——所以这一步和下一步
（估计变换）不需要插盘，也不需要 GDAL。

`.pts` 的 y 不取负（见术语表的坐标符号约定），读进来就是向下为正的行号，不做任何翻转。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from moondata.errors import MetadataUnreadable, TiePointsUnreadable
from moondata.metadata import padded_roi, raw_roi_name

TIE_POINTS_RELDIR = Path("data") / "tie-points"
TIE_POINTS_FILENAME = "opt_tie.pts"
GENERATIONS = ("cropped_2", "cropped")
"""按优先级。`cropped` 是当年真正用来切 patch 的那一代；`cropped_2` 是事后在修正过的
影像上重标的一代（目前只有 ROI_73），有它就以它为准。`cropped_1` 是公认坏掉的一代
（光学与 SAR 不在同一网格上），**永远不用**，所以不在这里。"""


@dataclass(frozen=True)
class TiePoints:
    roi: str
    """补零写法，如 `ROI_035`。"""
    path: Path
    optical: np.ndarray
    """`(n, 2)`，对齐光学影像上的 (列, 行)。ENVI 里的 base。"""
    sar: np.ndarray
    """`(n, 2)`，对齐 SAR 影像上的 (列, 行)。ENVI 里的 warp。"""


def load_tie_points(repo_root: Path, roi: str) -> TiePoints:
    """读仓库里某个 ROI 用于生产的那一代对齐控制点。"""
    try:
        padded, raw = padded_roi(roi), raw_roi_name(roi)
    except MetadataUnreadable as error:
        raise TiePointsUnreadable(str(error)) from error
    roi_dir = repo_root / TIE_POINTS_RELDIR / raw
    for generation in GENERATIONS:
        path = roi_dir / generation / TIE_POINTS_FILENAME
        if path.is_file():
            optical, sar = read_envi_pts(path)
            return TiePoints(padded, path, optical, sar)
    raise TiePointsUnreadable(
        f"{raw} 没有可用的对齐控制点：{roi_dir} 下找不到 "
        + " 或 ".join(f"{g}/{TIE_POINTS_FILENAME}" for g in GENERATIONS)
    )


def read_envi_pts(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """ENVI Image-to-Image Tie Points：`;` 开头是注释，数据行为
    `base_x base_y warp_x warp_y [score]`。返回 (base, warp)。"""
    # 头部注释里的文件路径是 ENVI 按系统代码页写的（中文 Windows 上是 GBK），按 UTF-8
    # 硬解码会在第一行就失败。数据行是纯 ASCII，注释行反正丢弃，所以降级解码即可。
    text = path.read_text(encoding="utf-8", errors="replace")
    rows = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        try:
            values = [float(token) for token in line.split()]
        except ValueError:
            raise TiePointsUnreadable(f"{path}:{lineno} 不是数值行：{line!r}") from None
        if len(values) < 4:
            raise TiePointsUnreadable(f"{path}:{lineno} 不足 4 列：{line!r}")
        rows.append(values[:4])
    if not rows:
        raise TiePointsUnreadable(f"{path} 里一对点也没有")
    data = np.asarray(rows, dtype=np.float64)
    return data[:, :2], data[:, 2:4]
