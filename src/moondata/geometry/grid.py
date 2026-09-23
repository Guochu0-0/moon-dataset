"""对齐影像的像素网格：光学与 SAR 在哪块范围上、按什么网格重采样。

规则取自当年实际产出 `raw/ROI_*/cropped/` 的那一版脚本，并在全部 68 个 ROI 上与盘上
的既有网格逐项核对过（`moondata overlap --verify`）：

1. 光学分幅取并集，与 SAR 条带求交——在月球经纬度（球体）下求；
2. 交集以中心为基准，宽高各放大到 1.2 倍（`HISTORICAL_EXPAND`）；
3. 投到网格所用的投影坐标系，以左上角为原点、7.5 m 为像元，宽高**四舍五入**取整。

第 3 步的「四舍五入」是 GDAL 在只给范围与分辨率时的做法，当年没有显式写出来；
这里把它写成显式计算、再把宽高一并交给 GDAL，免得换个 GDAL 版本悄悄变成向下取整。

本模块只管经纬度与平面坐标里的数；坐标系之间的换算（要 pyproj）在栅格层。
"""

from __future__ import annotations

from typing import NamedTuple, Sequence

from moondata.errors import NoOverlap

HISTORICAL_EXPAND = 1.2
"""交集外扩系数。放大后的边缘只有一侧有数据，全是 nodata，但**网格原点由它决定**，
改了它全部窗口都会移位——所以它是一个必须原样保留的历史常数，而不是可调的参数。"""
TARGET_RESOLUTION = 7.5
"""对齐影像的像元大小（米）。CE-2 原生 7 m、Mini-RF 约 7.4 m，统一到 7.5 m。"""


class LonLatBox(NamedTuple):
    """月球经纬度范围（度）。经度是**连续的**：`east > west`，可以超出 ±180。

    跨 180° 经线时用 0–360 与 ±180 来回换算，是旧代码求出空交集或「绕月一圈」
    范围的原因。这里只允许整体平移 360° 的整数倍，从不取模。
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
    当年是镶嵌脚本碰巧取了「目录里第二幅」的投影；按重叠面积挑在全部既有网格上给出
    同样的结果，且说得出道理——网格落在条带主体所在的那一带上，形变最小。
    """
    areas = []
    for tile in optical_tiles:
        common = sar.intersection(tile)
        areas.append(common.area() if common is not None else 0.0)
    return max(range(len(areas)), key=lambda i: (areas[i], -i))


ORIGIN_TOLERANCE_M = 1e-6
"""两个网格的原点差多少米以内算同一个。GDAL 往返一次的浮点误差在 1e-9 m 量级；
真正的偏差哪怕只有几厘米也要报出来——整幅差零点几个像素，patch 就不再逐字节相同。"""
RESOLUTION_TOLERANCE_M = 1e-9


class PixelGrid(NamedTuple):
    """一幅对齐影像的像素网格：坐标系、左上角原点、正方形像元、宽高。

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
        """覆盖投影坐标范围 `(minx, miny, maxx, maxy)` 的网格。原点钉在左上角，
        宽高按像元数四舍五入——右边与下边因此可能比 `bounds` 多出或少掉不到半个像元。"""
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
