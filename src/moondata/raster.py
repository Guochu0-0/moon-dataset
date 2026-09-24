"""栅格层：唯一依赖 GDAL/pyproj 的地方——读范围、warp、按窗口切块写 TIFF。

**所有地理库调用都必须收在这里。** 其余模块不得 import GDAL 或 pyproj：几何是全部
窗口位置的来源，它必须能不装地理库、不接数据盘地被单测覆盖（见 `moondata.geometry`）。

本层不设单测：它是对 GDAL 的薄封装，正确性由「重叠区影像落在规划的网格上」这条写完
立刻回读的断言，以及一次性验收体现。
"""

from __future__ import annotations

import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
from osgeo import gdal
from pyproj import CRS, Transformer

from moondata.errors import GridMismatch, RasterUnreadable
from moondata.geometry import LonLatBox, PixelGrid
from moondata.sources import corrected_lat_ts

gdal.UseExceptions()

MOON_LONLAT = CRS.from_proj4("+proj=longlat +a=1737400 +b=1737400 +no_defs")
"""求重叠区所在的月球经纬度（球体）。"""
DENSIFY_POINTS = 21
"""投影范围换算到经纬度时每条边加密的点数。范围差一丝，网格原点就差一丝，所以取当年
算出这批网格的那个默认值（rasterio `transform_bounds`）。"""
CREATION_OPTIONS = ["COMPRESS=DEFLATE", "TILED=YES"]
PATCH_CREATION_OPTIONS = ["COMPRESS=DEFLATE"]
"""patch 按条带式写（不分块），与数据盘上现有 patch 的写法一致；多波段另加像素交错。"""


@dataclass(frozen=True)
class Footprint:
    path: Path
    crs_wkt: str
    """读取时要用的坐标系。CE-2 分幅头里 `lat_ts` 写错的，这里已是纠正后的。"""
    corrected: bool
    lonlat: LonLatBox


def read_footprint(path: Path, *, ce2_tile: bool) -> Footprint:
    """读一幅影像的坐标系与月面经纬度范围。只读文件头，不读像素。"""
    dataset = _open(path)
    wkt = dataset.GetProjection()
    if not wkt:
        raise RasterUnreadable(f"{path} 没有坐标系")
    corrected = False
    if ce2_tile:
        fixed = corrected_lat_ts(path)
        if fixed is not None:
            params = CRS.from_wkt(wkt).to_dict()
            params["lat_ts"] = fixed
            wkt, corrected = CRS.from_dict(params).to_wkt(), True
    west, south, east, north = Transformer.from_crs(
        CRS.from_wkt(wkt), MOON_LONLAT, always_xy=True
    ).transform_bounds(*_bounds(dataset), densify_pts=DENSIFY_POINTS)
    # ROI_034 的那幅分幅（K236，名字写的是东经 175°）跨 180° 经线，换算回来的 east 是
    # −179.98：不是分幅错了，是经度在 ±180 处断开。`from_bounds` 把它接成连续区间。
    return Footprint(path, wkt, corrected, LonLatBox.from_bounds(west, south, east, north))


def project_box(box: LonLatBox, crs_wkt: str) -> tuple[float, float, float, float]:
    """经纬度范围 → 目标投影坐标里的外包矩形。"""
    return Transformer.from_crs(
        MOON_LONLAT, CRS.from_wkt(crs_wkt), always_xy=True
    ).transform_bounds(*box, densify_pts=DENSIFY_POINTS)


def same_crs(a_wkt: str, b_wkt: str) -> bool:
    """两份 WKT 是否指同一个坐标系。墨卡托 `lat_ts` 只差正负号也算同一个——投影只取
    它的余弦，盘上有北半球分幅写成负值。"""
    a, b = CRS.from_wkt(a_wkt), CRS.from_wkt(b_wkt)
    if a.equals(b):
        return True
    da, db = a.to_dict(), b.to_dict()
    for params in (da, db):
        if "lat_ts" in params:
            params["lat_ts"] = abs(float(params["lat_ts"]))
    return CRS.from_dict(da).equals(CRS.from_dict(db))


def read_grid(path: Path) -> PixelGrid:
    dataset = _open(path)
    x0, dx, rx, y0, ry, dy = dataset.GetGeoTransform()
    if rx != 0 or ry != 0 or abs(dx + dy) > 1e-9:
        raise RasterUnreadable(f"{path} 不是北向上的正方形像元：{(x0, dx, rx, y0, ry, dy)}")
    return PixelGrid(dataset.GetProjection(), x0, y0, dx, dataset.RasterXSize, dataset.RasterYSize)


def warp_onto(
    sources: Sequence[Footprint],
    grid: PixelGrid,
    output: Path,
    *,
    resample: str,
    nodata: float,
    keep_nodata_values: bool,
) -> None:
    """一次 `gdal.Warp` 把 `sources` 镶嵌、重投影、裁切、重采样到 `grid` 上。

    **只插值一次。** 先镶嵌成中间文件、或先重投影再裁切，会连着插值两三次，历史产物里
    的规则矩形网纹就是这么来的。`gdal.Warp` 的输入本来就接受文件列表。

    同时钉住范围与宽高、不给分辨率：只给分辨率时 GDAL 可能因浮点舍入把宽高算差一个
    像素，而差一个像素就意味着全部窗口整体错位。

    `keep_nodata_values` 决定「算出来正好等于 nodata」的有效像素怎么办。交给
    `dstNodata` 时，GDAL 会把它挪开一点（Byte 挪成 1，float32 挪成 1.4e-45），免得它被
    误当作 nodata；为真时改为先把目标填成 `nodata`（`INIT_DEST`）、warp 完再写文件头，
    值原样保留。两边要的恰好相反，都是为了与现有数据集的窗口一致：

    - SAR 要保留。Mini-RF 条带自己的填充值就是 0，挪开之后那片区域不再等于 0，下一步的
      「含不含 nodata」就漏判，贴边的窗口会多留下来。
    - 光学要挪开。CE-2 暗区里 cubic 偶尔插出 0，当年的对齐影像把它写成 1；留着 0，
      ROI_007 光学窗口 (2048, 17920) 会因为这一个像素被当作含 nodata 剔掉，其后编号全部错位。

    `lat_ts` 被纠正过的分幅包一层临时 VRT（几 KB 的 XML）带上正确的坐标系，
    **源文件全程只读**。
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="moondata_vrt_") as tmp:
        inputs = []
        for index, source in enumerate(sources):
            if not source.corrected:
                inputs.append(str(source.path))
                continue
            vrt = Path(tmp) / f"{index}_{source.path.stem}.vrt"
            gdal.Translate(str(vrt), str(source.path), format="VRT", outputSRS=source.crs_wkt)
            inputs.append(str(vrt))
        gdal.Warp(
            str(output),
            inputs,
            options=gdal.WarpOptions(
                format="GTiff",
                dstSRS=grid.crs_wkt,
                outputBounds=grid.bounds,
                width=grid.width,
                height=grid.height,
                resampleAlg=resample,
                **(
                    {"warpOptions": [f"INIT_DEST={nodata}"]}
                    if keep_nodata_values
                    else {"dstNodata": nodata}
                ),
                creationOptions=CREATION_OPTIONS,
            ),
        )
    if keep_nodata_values:
        _set_nodata(output, nodata)


def _set_nodata(path: Path, nodata: float) -> None:
    """只改文件头。不给 `dstNodata` 时 GDAL 会把源的 nodata（Mini-RF 是 −3.4e38）抄进
    输出，而输出里没有数据的地方写的是 `INIT_DEST` 的 0。"""
    dataset = gdal.Open(str(path), gdal.GA_Update)
    for band in range(1, dataset.RasterCount + 1):
        dataset.GetRasterBand(band).SetNoDataValue(nodata)
    dataset = None


def assert_on_grid(path: Path, grid: PixelGrid) -> None:
    """写出的影像必须恰好落在规划的网格上。

    两幅重叠区影像错开一个像素在下游完全不报错，只会让所有窗口系统性偏移——那种问题
    查起来极贵，所以写完立刻读回来逐项核对。
    """
    written = read_grid(path)
    problems = grid.differences(written)
    if not same_crs(grid.crs_wkt, written.crs_wkt):
        problems.append("坐标系不同")
    if problems:
        raise GridMismatch(f"{path} 没有落在规划的网格上：{'；'.join(problems)}")


class Blocks:
    """按窗口随机读块。打开一次、反复读：一幅四波段 float32 的重叠区 SAR 影像动辄几个
    GB，整幅读进内存是不行的。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._dataset = _open(path)

    def read(self, origin: tuple[int, int], size: int) -> np.ndarray:
        """左上角 `origin`（列, 行）、边长 `size` 的块，形状 `(波段, 行, 列)`。"""
        x, y = origin
        block = self._dataset.ReadAsArray(x, y, size, size)
        return block if block.ndim == 3 else block[np.newaxis]

    def close(self) -> None:
        self._dataset = None

    def __enter__(self) -> "Blocks":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def write_patches(
    source: Path, origins: Sequence[tuple[int, int]], size: int, outputs: Sequence[Path]
) -> None:
    """从 `source` 上按左上角 `origins`（列, 行）切 `size × size` 的块，逐个写成 GeoTIFF。

    坐标系、nodata 照抄 `source`，地理变换平移到块的左上角——patch 因此自带地理位置，
    拼回原图不必再查窗口表。
    """
    dataset = _open(source)
    projection = dataset.GetProjection()
    x0, dx, rx, y0, ry, dy = dataset.GetGeoTransform()
    bands = dataset.RasterCount
    data_type = dataset.GetRasterBand(1).DataType
    nodata = dataset.GetRasterBand(1).GetNoDataValue()
    options = PATCH_CREATION_OPTIONS + (["INTERLEAVE=PIXEL"] if bands > 1 else [])
    driver = gdal.GetDriverByName("GTiff")
    for (x, y), output in zip(origins, outputs, strict=True):
        block = dataset.ReadAsArray(x, y, size, size)
        block = block if block.ndim == 3 else block[np.newaxis]
        output.parent.mkdir(parents=True, exist_ok=True)
        patch = driver.Create(str(output), size, size, bands, data_type, options)
        patch.SetGeoTransform((x0 + x * dx, dx, rx, y0 + y * dy, ry, dy))
        patch.SetProjection(projection)
        if nodata is not None:
            for band in range(1, bands + 1):
                patch.GetRasterBand(band).SetNoDataValue(nodata)
        for band in range(bands):
            patch.GetRasterBand(band + 1).WriteArray(block[band])
        patch = None  # 关掉才落盘


def _open(path: Path) -> gdal.Dataset:
    try:
        return gdal.Open(str(path))
    except RuntimeError as error:
        raise RasterUnreadable(f"{path} 打不开：{error}") from error


def _bounds(dataset: gdal.Dataset) -> tuple[float, float, float, float]:
    x0, dx, _, y0, _, dy = dataset.GetGeoTransform()
    x1, y1 = x0 + dx * dataset.RasterXSize, y0 + dy * dataset.RasterYSize
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


# ---------------------------------------------------------------------------
# 文档素材（`moondata.assets`）用到的读取与重投影。只求看得清，不进数据集。


def projection_params(crs_wkt: str) -> dict[str, float | str]:
    """坐标系的投影名与决定它的几个参数，供文档写成一句话。"""
    with warnings.catch_warnings():
        # to_dict 经由 PROJ 字符串，会丢掉 WKT 里的名字等信息——这里只要投影参数
        warnings.simplefilter("ignore", UserWarning)
        params = CRS.from_wkt(crs_wkt).to_dict()
    found: dict[str, float | str] = {"name": params.get("proj", "?")}
    for key in ("lat_ts", "lat_0", "lon_0"):
        if key in params:
            found[key] = float(params[key])
    return found


def bounds_in(path: Path, source_wkt: str, target_wkt: str) -> tuple[float, float, float, float]:
    """一幅影像的范围换到另一个坐标系里的外包矩形。`source_wkt` 显式给出，`lat_ts`
    纠正过的分幅要用纠正后的坐标系。"""
    return Transformer.from_crs(
        CRS.from_wkt(source_wkt), CRS.from_wkt(target_wkt), always_xy=True
    ).transform_bounds(*_bounds(_open(path)), densify_pts=DENSIFY_POINTS)


def preview(path: Path, width: int, height: int, bands: Sequence[int] = (1,)) -> tuple[np.ndarray, tuple]:
    """降采样读整幅，返回 `(波段, 行, 列)` 的 float32 与对应的地理变换。

    按最近邻隔行隔列取：GDAL 只读用到的行，文件有金字塔时直接读金字塔。Mini-RF 条带
    是逐行存储的几 GB 到几十 GB，按均值降采样要把整幅读一遍。
    """
    dataset = _open(path)
    width, height = min(width, dataset.RasterXSize), min(height, dataset.RasterYSize)
    array = dataset.ReadAsArray(
        0, 0, dataset.RasterXSize, dataset.RasterYSize,
        buf_xsize=width, buf_ysize=height, band_list=list(bands),
    ).astype(np.float32)
    array = array if array.ndim == 3 else array[np.newaxis]
    x0, dx, rx, y0, ry, dy = dataset.GetGeoTransform()
    sx, sy = dataset.RasterXSize / width, dataset.RasterYSize / height
    return array, (x0, dx * sx, rx, y0, ry, dy * sy)


def warp_array(
    array: np.ndarray, geotransform: tuple, source_wkt: str, grid: PixelGrid, *, resample: str = "average"
) -> np.ndarray:
    """把内存里的单波段影像（NaN 为无数据）重投影到 `grid` 上，返回 `(行, 列)`，无数据为 NaN。"""
    driver = gdal.GetDriverByName("MEM")
    source = driver.Create("", array.shape[1], array.shape[0], 1, gdal.GDT_Float32)
    source.SetGeoTransform(geotransform)
    source.SetProjection(source_wkt)
    band = source.GetRasterBand(1)
    band.SetNoDataValue(float("nan"))
    band.WriteArray(array)
    target = driver.Create("", grid.width, grid.height, 1, gdal.GDT_Float32)
    target.SetGeoTransform(grid.geotransform)
    target.SetProjection(grid.crs_wkt)
    target.GetRasterBand(1).SetNoDataValue(float("nan"))
    target.GetRasterBand(1).Fill(float("nan"))
    gdal.Warp(target, source, options=gdal.WarpOptions(resampleAlg=resample, srcNodata="nan", dstNodata="nan"))
    return target.GetRasterBand(1).ReadAsArray()
