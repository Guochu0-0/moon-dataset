"""第三步：由对齐控制点估计该 ROI 的全局变换（光学像素 → SAR 像素）。

算法本身是纯几何，实现落在 `moondata.geometry`；本包只负责「哪个 ROI 用哪些点、
解出什么、与既有结果是否一致」这一层编排。

数据集当年用的是**最小二乘仿射**（6 自由度），所以默认就是它。另外三种模型供研究对比，
选了它们，求出来的就不再是产出现有数据集的那个变换。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from moondata.geometry import TransformModel, apply_transform, estimate_transform
from moondata.manifest import ManifestRoi
from moondata.tiepoints import TiePoints

DEFAULT_MODEL = TransformModel.AFFINE

ROUNDING_BAND_PX = (0.0, 2.0)
"""连续预测减去清单坐标的容许区间（像素，含左不含右）。

清单里的 SAR 窗口是整数，当年由「四角变换后先各自截断、取平均、再截断」得到——两次
截断各贡献 [0, 1) 的偏差，合起来落在 [0, 2)。变换若与当年不同，偏差会随位置漂移、
很快跑出这个区间；落在区间里只说明「在取整误差以内一致」。逐像素相等的取整见
`moondata.geometry.plan_windows`，逐条验收见 `moondata verify-windows`。下界放一点浮点余量。"""
_FLOAT_SLACK = 1e-6


@dataclass(frozen=True)
class GlobalTransform:
    roi: str
    model: TransformModel
    matrix: np.ndarray
    """`3×3`，把对齐光学影像的 (列, 行) 映到对齐 SAR 影像的 (列, 行)。"""
    tie_points: TiePoints

    @property
    def residuals(self) -> np.ndarray:
        """逐点拟合残差（像素）。"""
        predicted = apply_transform(self.tie_points.optical, self.matrix)
        return np.linalg.norm(predicted - self.tie_points.sar, axis=1)

    @property
    def rmse(self) -> float:
        return float(np.sqrt((self.residuals**2).mean()))


def solve(tie_points: TiePoints, model: TransformModel = DEFAULT_MODEL) -> GlobalTransform:
    matrix = estimate_transform(tie_points.optical, tie_points.sar, model)
    return GlobalTransform(tie_points.roi, model, matrix, tie_points)


@dataclass(frozen=True)
class WindowDeviation:
    index: int
    dx: float
    dy: float
    """连续预测减去清单坐标（像素）。"""


@dataclass(frozen=True)
class ManifestComparison:
    roi: str
    split: str
    windows: int
    dx_range: tuple[float, float]
    dy_range: tuple[float, float]
    outliers: list[WindowDeviation]
    """偏差落在 `ROUNDING_BAND_PX` 之外的窗口，按清单顺序。"""

    @property
    def consistent(self) -> bool:
        return self.windows > 0 and not self.outliers


def compare_with_manifest(solved: GlobalTransform, manifest: ManifestRoi) -> ManifestComparison:
    """用求出的变换重算清单里每个窗口的 SAR 位置，看与清单是否只差取整。

    SAR 窗口的定法：光学窗口四角经变换后取平均得中心，再减去半个 patch。四角取的是
    `x` 与 `x + patch_size`（不是 `x + patch_size − 1`），与当年一致。
    """
    size = manifest.patch_size
    deviations = []
    for window in manifest.windows:
        x, y = window.optical
        corners = np.array([[x, y], [x + size, y], [x + size, y + size], [x, y + size]], float)
        centre = apply_transform(corners, solved.matrix).mean(axis=0)
        dx, dy = centre - size / 2 - np.asarray(window.sar, float)
        deviations.append(WindowDeviation(window.index, float(dx), float(dy)))

    low, high = ROUNDING_BAND_PX
    outliers = [
        d for d in deviations
        if not (low - _FLOAT_SLACK <= d.dx < high and low - _FLOAT_SLACK <= d.dy < high)
    ]
    dxs = [d.dx for d in deviations] or [float("nan")]
    dys = [d.dy for d in deviations] or [float("nan")]
    return ManifestComparison(
        roi=manifest.roi,
        split=manifest.split,
        windows=len(deviations),
        dx_range=(min(dxs), max(dxs)),
        dy_range=(min(dys), max(dys)),
        outliers=outliers,
    )
