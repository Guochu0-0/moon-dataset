"""几何层：重叠区与网格、铺窗、仿射、SAR 窗口映射、窗口剔除与编号。

纯 numpy，不 import 任何地理库——坐标系之间的换算在 `moondata.raster`。这条界线是
为了测试：窗口位置与编号是整个数据集的骨架（评测真值点按编号绑在 patch 上），把它
做成无 IO 的纯函数，才能不接数据盘就完整覆盖。

为复现历史而保留的实现，本模块里有三处，都不要「顺手改正」：

1. **1.2 倍外扩**（`HISTORICAL_EXPAND`）。当年把光学与 SAR 的交集宽高各放大到 1.2 倍
   再定网格，放大出来的边缘只有一侧有数据、全是 nodata。它决定网格原点，改了它全部
   窗口一起移位、评测真值点全部作废，所以它是常数而不是参数。
2. **两次向零截断**（`sar_window`）。SAR 窗口由光学窗口四角经仿射映射后**各自截断**取
   平均、减半个 patch 后**再截断一次**得到。两处都是 Python `int()` 的语义——向零，
   不是向下。二者只在负数上有区别：中心算出 −0.5 时截断得 0，窗口照样留下；改成向下
   取整会得 −1、窗口出界被丢，其后全部编号错位。
3. **边缘余量直接丢弃**（`tile_windows`）。不补边、不把最后一窗往回挪去贴边。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Collection, NamedTuple, Sequence

import numpy as np
import numpy.typing as npt

from moondata.errors import DegeneratePoints, InsufficientPoints, NoOverlap

TARGET_RESOLUTION = 7.5
"""重叠区影像的像元大小（米）。CE-2 原生 7 m、Mini-RF 约 7.4 m，统一到 7.5 m。"""
HISTORICAL_EXPAND = 1.2
"""交集外扩系数，见模块 docstring 第 1 条。"""
MIN_OVERLAP = 0.7
"""变换后的四边形至少要盖住 SAR 窗口的多大比例。分母是 patch 面积。"""
MIN_TIE_POINTS = 3
"""仿射有 6 个自由度，每对点给两个方程。"""


# ---------------------------------------------------------------------------
# 仿射变换


def estimate_affine(src: npt.ArrayLike, dst: npt.ArrayLike) -> np.ndarray:
    """最小二乘解出把 `src` 映到 `dst` 的仿射变换，返回 `3×3`（末行恒为 `[0, 0, 1]`）。

    点集是 `(n, 2)`，列序 `(x, y)` = (列号, 行号)，y 向下为正——控制点 `.pts` 读进来
    就是这样，本层从不见到取负的 y。

    全部控制点参与，不剔点：剔点等于悄悄换了一个 ROI 的变换。点不够或退化就报错，
    **从不静默降级**成平移或相似——少一个自由度解出来的是另一个问题的答案。
    """
    source, target = _points(src, "src"), _points(dst, "dst")
    if len(source) != len(target):
        raise ValueError(f"两侧点数不一致：{len(source)} 对 {len(target)}")
    if len(source) < MIN_TIE_POINTS:
        raise InsufficientPoints(
            f"仿射变换至少需要 {MIN_TIE_POINTS} 对控制点，实际只有 {len(source)} 对"
        )
    # lstsq 而不是正规方程 inv(PᵀP)Pᵀ：后者把条件数平方，而像素坐标动辄上万。
    design = np.column_stack([source, np.ones(len(source))])
    solution, _, rank, _ = np.linalg.lstsq(design, target, rcond=None)
    if rank < 3:
        raise DegeneratePoints("仿射变换要求控制点不全共线")
    return np.vstack([solution.T, [0.0, 0.0, 1.0]])


def apply_transform(points: npt.ArrayLike, matrix: npt.ArrayLike) -> np.ndarray:
    """把 `(n, 2)` 的点按 `3×3` 矩阵变换，返回 `(n, 2)`。"""
    pts = _points(points, "points")
    m = np.asarray(matrix, dtype=np.float64)
    if m.shape != (3, 3):
        raise ValueError(f"变换矩阵应为 3×3，实际为 {m.shape}")
    homo = np.column_stack([pts, np.ones(len(pts))]) @ m.T
    return homo[:, :2] / homo[:, 2:3]


def rmse(matrix: npt.ArrayLike, src: npt.ArrayLike, dst: npt.ArrayLike) -> float:
    """拟合残差（像素）。脚本把它打出来：残差突然变大就是控制点标错了。"""
    residuals = apply_transform(src, matrix) - _points(dst, "dst")
    return float(np.sqrt((residuals**2).sum(axis=1).mean()))


def _points(points: npt.ArrayLike, name: str) -> np.ndarray:
    array = np.asarray(points, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 2:
        raise ValueError(f"{name} 应为 (n, 2) 的点集，实际为 {array.shape}")
    return array


# ---------------------------------------------------------------------------
# 铺窗、SAR 窗口映射、剔除与编号


class WindowPair(NamedTuple):
    optical: tuple[int, int]
    """光学窗口左上角 (列, 行)。"""
    sar: tuple[int, int]


@dataclass(frozen=True)
class Window:
    index: int
    """`patch_<index>` 里的那个数。评测真值点按它绑在 patch 上。"""
    optical: tuple[int, int]
    sar: tuple[int, int]


@dataclass(frozen=True)
class WindowPlan:
    pairs: list[WindowPair]
    """几何上站得住的窗口，按铺窗顺序。还没过像素检查，所以还没有编号。"""
    out_of_bounds: int
    low_overlap: int


def tile_windows(width: int, height: int, size: int) -> list[tuple[int, int]]:
    """铺满 `width × height` 的光学窗口左上角 (列, 行)，逐行、行内从左到右。

    从原点起、步长等于边长，边缘余量直接丢弃（见模块 docstring 第 3 条）。
    """
    if size <= 0:
        raise ValueError(f"patch 边长必须为正，实际为 {size}")
    return [
        (x, y)
        for y in range(0, height - size + 1, size)
        for x in range(0, width - size + 1, size)
    ]


def sar_window(optical: tuple[int, int], size: int, matrix: npt.ArrayLike) -> tuple[int, int]:
    """光学窗口 `optical`（左上角）对应的 SAR 窗口左上角，两次向零截断（第 2 条）。"""
    return _place(_warped_corners(optical, size, matrix), size)


def candidate_windows(
    optical_size: tuple[int, int],
    sar_size: tuple[int, int],
    matrix: npt.ArrayLike,
    size: int,
    *,
    min_overlap: float = MIN_OVERLAP,
) -> WindowPlan:
    """铺光学窗口、定 SAR 窗口，丢掉几何上站不住的。尺寸都是 `(宽, 高)`。

    两条几何判据：SAR 窗口出界；变换后的四边形与 SAR 窗口的重叠比例低于 `min_overlap`。
    """
    sar_width, sar_height = sar_size
    pairs, out_of_bounds, low_overlap = [], 0, 0
    for optical in tile_windows(*optical_size, size):
        corners = _warped_corners(optical, size, matrix)
        x, y = _place(corners, size)
        if x < 0 or y < 0 or x + size > sar_width or y + size > sar_height:
            out_of_bounds += 1
        elif _clipped_area(corners, x, y, size) / size**2 < min_overlap:
            low_overlap += 1
        else:
            pairs.append(WindowPair(optical, (x, y)))
    return WindowPlan(pairs, out_of_bounds, low_overlap)


def number_windows(
    pairs: Sequence[WindowPair],
    *,
    usable: Callable[[WindowPair], bool],
    excluded: Collection[tuple[int, int]] = (),
) -> list[Window]:
    """过像素检查与剔除表，留下的按铺窗顺序从 0 连续编号。

    `usable` 判一对窗口的像素能不能用（`usable_pair`，要读影像，所以由调用方注入）；
    `excluded` 是光学窗口左上角的剔除表。**丢错一个，其后全部编号错位**，所以这里
    只做「按顺序编号」这一件事，不做任何重排。
    """
    excluded = set(excluded)
    kept: list[Window] = []
    for pair in pairs:
        if pair.optical in excluded or not usable(pair):
            continue
        kept.append(Window(len(kept), pair.optical, pair.sar))
    return kept


NODATA = 0
"""光学与 SAR 都按 0 判。SAR 有大量负值，那是真实数据；只有恰好等于 0 才是 nodata。"""


def usable_pair(optical: np.ndarray, sar: np.ndarray) -> bool:
    """一对 patch 能不能进数据集：任一边、任一波段、任一像素等于 0 就不能。"""
    return not (np.any(optical == NODATA) or np.any(sar == NODATA))


def _warped_corners(optical: tuple[int, int], size: int, matrix: npt.ArrayLike) -> np.ndarray:
    """变换后各自向零截断的四角，`(4, 2)` 整数。四角取 `x` 与 `x + size`（不是
    `x + size − 1`），与当年一致。"""
    x, y = optical
    corners = np.array([[x, y], [x + size, y], [x + size, y + size], [x, y + size]], float)
    return np.trunc(apply_transform(corners, matrix)).astype(np.int64)


def _place(corners: np.ndarray, size: int) -> tuple[int, int]:
    cx, cy = corners.mean(axis=0)
    return int(cx - size / 2), int(cy - size / 2)


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


# ---------------------------------------------------------------------------
# 重叠区与像素网格


class LonLatBox(NamedTuple):
    """月球经纬度范围（度）。经度是**连续的**：`east > west`，可以超出 ±180。

    跨 180° 经线时在 0–360 与 ±180 之间来回取模，会得到空交集或「绕月一圈」的范围。
    这里只允许整体平移 360° 的整数倍，从不取模。
    """

    west: float
    south: float
    east: float
    north: float

    @classmethod
    def from_bounds(cls, west: float, south: float, east: float, north: float) -> LonLatBox:
        """接受坐标变换直接给出的范围：跨 180° 时 `east <= west`，补上 360°。"""
        if east <= west:
            east += 360.0
        return cls(west, south, east, north)

    @property
    def centre_lon(self) -> float:
        return (self.west + self.east) / 2.0

    def shifted_near(self, lon: float) -> LonLatBox:
        """整体平移 360° 的整数倍，使中心经度落在 `lon` 附近。"""
        shift = round((lon - self.centre_lon) / 360.0) * 360.0
        return self._replace(west=self.west + shift, east=self.east + shift)

    def intersection(self, other: LonLatBox) -> LonLatBox | None:
        other = other.shifted_near(self.centre_lon)
        box = LonLatBox(
            max(self.west, other.west),
            max(self.south, other.south),
            min(self.east, other.east),
            min(self.north, other.north),
        )
        return box if box.west < box.east and box.south < box.north else None

    def area(self) -> float:
        """经纬度平面上的面积，只用来比大小。"""
        return (self.east - self.west) * (self.north - self.south)

    def expanded(self, factor: float) -> LonLatBox:
        dx = (self.east - self.west) * (factor - 1.0) / 2.0
        dy = (self.north - self.south) * (factor - 1.0) / 2.0
        return LonLatBox(self.west - dx, self.south - dy, self.east + dx, self.north + dy)


def overlap_region(
    optical_tiles: Sequence[LonLatBox], sar: LonLatBox, *, expand: float = HISTORICAL_EXPAND
) -> LonLatBox:
    """光学分幅并集与 SAR 条带的交集，再按 `expand` 外扩。

    结果的中心经度归一到 [−180°, 180°)：同一块地只有一种写法，下游投到投影坐标时
    不必再猜它是哪一圈。
    """
    if not optical_tiles:
        raise ValueError("没有光学分幅")
    tiles = [tile.shifted_near(sar.centre_lon) for tile in optical_tiles]
    union = LonLatBox(
        min(t.west for t in tiles),
        min(t.south for t in tiles),
        max(t.east for t in tiles),
        max(t.north for t in tiles),
    )
    common = sar.intersection(union)
    if common is None:
        raise NoOverlap(f"光学 {union} 与 SAR {sar} 没有公共范围")
    return common.expanded(expand).shifted_near(0.0)


def reference_tile(optical_tiles: Sequence[LonLatBox], sar: LonLatBox) -> int:
    """网格沿用哪一幅光学分幅的投影：与 SAR 重叠面积最大的那幅，并列取靠前的。

    CE-2 按纬度带分幅、每带一套墨卡托，一个 ROI 横跨两带时两幅的投影不同，必须挑一个。
    按重叠面积挑，网格落在条带主体所在的那一带上，形变最小。
    """
    areas = []
    for tile in optical_tiles:
        common = sar.intersection(tile)
        areas.append(common.area() if common is not None else 0.0)
    return max(range(len(areas)), key=lambda i: (areas[i], -i))


ORIGIN_TOLERANCE_M = 1e-6
"""两个网格的原点差多少米以内算同一个。GDAL 往返一次的浮点误差在 1e-9 m 量级；
真正的偏差哪怕只有几厘米也要报出来——整幅差零点几个像素，窗口就不在原处了。"""
RESOLUTION_TOLERANCE_M = 1e-9


class PixelGrid(NamedTuple):
    """一幅重叠区影像的像素网格：坐标系、左上角原点、正方形像元、宽高。

    `crs_wkt` 原样携带、不在本层比较——两份 WKT 是否指同一个坐标系要 pyproj 才判得了，
    那是栅格层的事。
    """

    crs_wkt: str
    origin_x: float
    origin_y: float
    resolution: float
    width: int
    height: int

    @classmethod
    def covering(
        cls, crs_wkt: str, bounds: tuple[float, float, float, float], resolution: float
    ) -> PixelGrid:
        """覆盖投影坐标范围 `(minx, miny, maxx, maxy)` 的网格。原点钉在左上角，宽高按
        像元数**四舍五入**——这是 GDAL 只给范围与分辨率时的做法，当年没有显式写出来。
        这里写成显式计算、再把宽高一并交给 GDAL，免得换个版本悄悄变成向下取整。
        """
        min_x, min_y, max_x, max_y = bounds
        return cls(
            crs_wkt,
            origin_x=min_x,
            origin_y=max_y,
            resolution=resolution,
            width=round((max_x - min_x) / resolution),
            height=round((max_y - min_y) / resolution),
        )

    @property
    def geotransform(self) -> tuple[float, float, float, float, float, float]:
        """GDAL 顺序：`(原点 x, 像元宽, 0, 原点 y, 0, −像元高)`。"""
        return (self.origin_x, self.resolution, 0.0, self.origin_y, 0.0, -self.resolution)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (
            self.origin_x,
            self.origin_y - self.height * self.resolution,
            self.origin_x + self.width * self.resolution,
            self.origin_y,
        )

    def differences(self, other: PixelGrid) -> list[str]:
        """两个网格在几何上的全部差异，每条一句中文；空列表即同一网格（坐标系除外）。"""
        found = []
        if (self.width, self.height) != (other.width, other.height):
            found.append(f"宽高 {self.width}×{self.height} 对 {other.width}×{other.height}")
        dx, dy = other.origin_x - self.origin_x, other.origin_y - self.origin_y
        if abs(dx) > ORIGIN_TOLERANCE_M or abs(dy) > ORIGIN_TOLERANCE_M:
            found.append(f"原点偏差 x {dx:+.3f} m、y {dy:+.3f} m")
        if abs(other.resolution - self.resolution) > RESOLUTION_TOLERANCE_M:
            found.append(f"像元 {self.resolution} m 对 {other.resolution} m")
        return found
