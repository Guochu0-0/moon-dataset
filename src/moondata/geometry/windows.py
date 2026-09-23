"""窗口生成：光学窗口怎么铺、SAR 窗口落在哪、哪些窗口在几何上就站不住。

规则取自当年真正产出数据集的脚本（`image_patch_cropping.py` 的
`generate_aligned_patches`），在全部验证/测试 ROI 上与窗口清单逐条核对过：

1. 光学窗口从原点起、步长等于 patch 边长，**边缘余量直接丢弃**，不补边、不回挪；
2. SAR 窗口：光学窗口四角经全局变换，**各自截断成整数**，取平均得中心，减半个
   patch 后**再截断一次**；
3. SAR 窗口出界的丢弃；变换后的四边形与 SAR 窗口的重叠比例低于阈值的丢弃。

两处「截断」是 Python `int()` 的语义——**向零取整**，不是向下取整。二者只在负数上
有区别：中心算出 −0.5 时截断得 0，窗口照样留下。这里照原样复现，一个像素都不能改。

本模块只管几何；窗口还要过一道像素检查（含不含 nodata），那要读影像，
见 `moondata.patches`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

from moondata.geometry.transforms import apply_transform


def grid_windows(width: int, height: int, size: int) -> list[tuple[int, int]]:
    """铺满 `width × height` 的光学窗口左上角 (列, 行)，逐行、行内从左到右。"""
    if size <= 0:
        raise ValueError(f"patch 边长必须为正，实际为 {size}")
    return [
        (x, y)
        for y in range(0, height - size + 1, size)
        for x in range(0, width - size + 1, size)
    ]


def sar_window(optical: tuple[int, int], size: int, matrix) -> tuple[int, int]:
    """光学窗口 `optical`（左上角）对应的 SAR 窗口左上角。

    四角取 `x` 与 `x + size`（不是 `x + size − 1`），与当年一致。
    """
    return _place(_warped_corners(optical, size, matrix), size)


def _warped_corners(optical: tuple[int, int], size: int, matrix) -> np.ndarray:
    """变换后各自向零截断的四角，`(4, 2)` 整数。"""
    x, y = optical
    corners = np.array([[x, y], [x + size, y], [x + size, y + size], [x, y + size]], float)
    return np.trunc(apply_transform(corners, matrix)).astype(np.int64)


def _place(corners: np.ndarray, size: int) -> tuple[int, int]:
    cx, cy = corners.mean(axis=0)
    return int(cx - size / 2), int(cy - size / 2)


MIN_OVERLAP = 0.7
"""变换后的四边形至少要盖住 SAR 窗口的多大比例。当年的值，分母是 patch 面积。"""


class WindowPair(NamedTuple):
    optical: tuple[int, int]
    sar: tuple[int, int]


@dataclass(frozen=True)
class WindowPlan:
    windows: list[WindowPair]
    """几何上站得住的窗口，按铺窗顺序。还没过像素检查，所以还没有编号。"""
    out_of_bounds: int
    low_overlap: int


def plan_windows(
    optical_size: tuple[int, int],
    sar_size: tuple[int, int],
    matrix,
    size: int,
    *,
    min_overlap: float = MIN_OVERLAP,
) -> WindowPlan:
    """铺光学窗口、定 SAR 窗口、丢掉几何上站不住的。尺寸都是 `(宽, 高)`。"""
    sar_width, sar_height = sar_size
    windows, out_of_bounds, low_overlap = [], 0, 0
    for optical in grid_windows(*optical_size, size):
        corners = _warped_corners(optical, size, matrix)
        x, y = _place(corners, size)
        if x < 0 or y < 0 or x + size > sar_width or y + size > sar_height:
            out_of_bounds += 1
        elif _clipped_area(corners, x, y, size) / size**2 < min_overlap:
            low_overlap += 1
        else:
            windows.append(WindowPair(optical, (x, y)))
    return WindowPlan(windows, out_of_bounds, low_overlap)


def _clipped_area(polygon: np.ndarray, x: int, y: int, size: int) -> float:
    """多边形被轴对齐正方形 `[x, x+size] × [y, y+size]` 裁剪后的面积。

    Sutherland–Hodgman 逐条边裁剪，再用鞋带公式求面积。当年用的是 shapely，这里只有
    「四边形 ∩ 正方形」一种情形，犯不上为它多引一个依赖。
    """
    points = [(float(px), float(py)) for px, py in polygon]
    for axis, bound, keep_greater in (
        (0, x, True), (0, x + size, False), (1, y, True), (1, y + size, False)
    ):
        points = _clip(points, axis, bound, keep_greater)
        if not points:
            return 0.0
    xs, ys = np.array(points).T
    return float(abs(np.dot(xs, np.roll(ys, -1)) - np.dot(ys, np.roll(xs, -1))) / 2)


def _clip(
    points: list[tuple[float, float]], axis: int, bound: float, keep_greater: bool
) -> list[tuple[float, float]]:
    def inside(point: tuple[float, float]) -> bool:
        return point[axis] >= bound if keep_greater else point[axis] <= bound

    clipped = []
    for current, following in zip(points, points[1:] + points[:1]):
        if inside(current):
            clipped.append(current)
        if inside(current) != inside(following):
            t = (bound - current[axis]) / (following[axis] - current[axis])
            clipped.append(
                (current[0] + t * (following[0] - current[0]),
                 current[1] + t * (following[1] - current[1]))
            )
    return clipped
