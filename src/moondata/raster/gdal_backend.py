"""GDAL/pyproj 的全部调用。只经 `moondata.raster.backend()` 取用，见包 docstring。"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

import numpy as np
from osgeo import gdal
from pyproj import CRS, Transformer

from moondata.errors import GridMismatch, RasterUnreadable
from moondata.geometry import LonLatBox, PixelGrid
from moondata.sources import corrected_lat_ts
from moondata.tiff import recompress_deflate

gdal.UseExceptions()

MOON_LONLAT = CRS.from_proj4("+proj=longlat +a=1737400 +b=1737400 +no_defs")
"""求重叠区所在的月球经纬度（球体）。与当年一致。"""
DENSIFY_POINTS = 21
"""投影范围换算到经纬度时每条边加密的点数。取 rasterio `transform_bounds` 的默认值——
当年就是用它算的，范围差一丝，网格原点就差一丝。"""
CREATION_OPTIONS = ["COMPRESS=DEFLATE", "TILED=YES"]


@dataclass(frozen=True)
class Footprint:
    path: Path
    crs_wkt: str
    """读取时要用的坐标系。CE-2 分幅头若写错了 `lat_ts`，这里已是纠正后的。"""
    corrected: bool
    """`crs_wkt` 是否与文件头里写的不同。"""
    lonlat: LonLatBox


def gdal_version() -> str:
    return gdal.__version__


def read_footprint(path: Path, *, ce2_tile: bool) -> Footprint:
    dataset = _open(path)
    wkt = dataset.GetProjection()
    if not wkt:
        raise RasterUnreadable(f"{path} 没有坐标系")
    corrected = False
    if ce2_tile:
        params = CRS.from_wkt(wkt).to_dict()
        fixed = corrected_lat_ts(path.name, float(params.get("lat_ts", 0.0)))
        if params.get("proj") == "merc" and fixed is not None:
            params["lat_ts"] = fixed
            wkt, corrected = CRS.from_dict(params).to_wkt(), True
    bounds = _bounds(dataset)
    west, south, east, north = Transformer.from_crs(
        CRS.from_wkt(wkt), MOON_LONLAT, always_xy=True
    ).transform_bounds(*bounds, densify_pts=DENSIFY_POINTS)
    return Footprint(path, wkt, corrected, LonLatBox.from_bounds(west, south, east, north))


def project_box(box: LonLatBox, crs_wkt: str) -> tuple[float, float, float, float]:
    """经纬度范围 → 目标投影坐标里的外包矩形。"""
    return Transformer.from_crs(MOON_LONLAT, CRS.from_wkt(crs_wkt), always_xy=True).transform_bounds(
        *box, densify_pts=DENSIFY_POINTS
    )


def same_crs(a_wkt: str, b_wkt: str) -> bool:
    """两份 WKT 是否指同一个坐标系。墨卡托 `lat_ts` 只差正负号也算同一个——投影只取
    它的余弦（见来源文档），盘上有北半球分幅写成负值。"""
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
) -> None:
    """一次 `gdal.Warp` 把 `sources` 镶嵌、重投影、裁切、重采样到 `grid` 上。

    **只插值一次。** 当年先把分幅镶嵌成 `merged.tif`、SAR 先重投影落盘再裁切，
    连着插值两三次，这是历史产物里规则矩形网纹的来源之一。`gdal.Warp` 的输入本来就
    接受文件列表，一次调用能把四件事做完。

    同时钉住范围与宽高、不给分辨率：只给分辨率时 GDAL 可能因浮点舍入把宽高算差一个
    像素，而差一个像素就意味着全部窗口整体错位。

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
        options = gdal.WarpOptions(
            format="GTiff",
            dstSRS=grid.crs_wkt,
            outputBounds=grid.bounds,
            width=grid.width,
            height=grid.height,
            resampleAlg=resample,
            dstNodata=nodata,
            creationOptions=CREATION_OPTIONS,
        )
        gdal.Warp(str(output), inputs, options=options)


def warp_twice_onto(source: Footprint, grid: PixelGrid, output: Path, *, nodata: float) -> None:
    """当年 SAR 的对齐做法，**两次**最近邻：先重投影到网格的坐标系、分辨率由 GDAL 自定，
    落临时文件；再从临时文件裁切降采样到 `grid` 上。

    产 patch 不用它（多插值一次，有网纹）。它只用来重现当年哪些像素是 nodata——
    单次 warp 的 nodata 边缘与它差一两个像素，贴边的窗口就会判得不一样。
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="moondata_twice_") as tmp:
        reprojected = Path(tmp) / "reprojected.tif"
        gdal.Warp(
            str(reprojected), str(source.path),
            options=gdal.WarpOptions(dstSRS=grid.crs_wkt, resampleAlg="near", dstNodata=nodata),
        )
        options = gdal.WarpOptions(
            format="GTiff",
            outputBounds=grid.bounds,
            width=grid.width,
            height=grid.height,
            resampleAlg="near",
            dstNodata=nodata,
            creationOptions=CREATION_OPTIONS,
        )
        gdal.Warp(str(output), str(reprojected), options=options)


def read_blocks(path: Path, origins: Sequence[tuple[int, int]], size: int) -> Iterator[np.ndarray]:
    """逐个读 `size × size` 的块，左上角为 `origins`（列, 行）；形状 `(波段, 行, 列)`。

    只读用得到的块，不把整幅读进内存——一幅四波段 float32 的 SAR 对齐影像动辄几个 GB。
    """
    dataset = _open(path)
    for x, y in origins:
        block = dataset.ReadAsArray(x, y, size, size)
        yield block if block.ndim == 3 else block[np.newaxis]


PATCH_CREATION_OPTIONS = ["COMPRESS=DEFLATE"]
"""现有 patch 的写法（当年经 rasterio：Deflate、条带式、不分块）。多波段另加像素交错。"""


def write_patches(
    source: Path, origins: Sequence[tuple[int, int]], size: int, outputs: Sequence[Path]
) -> None:
    """从 `source` 上按左上角 `origins`（列, 行）切 `size × size` 的块，逐个写成 GeoTIFF。

    坐标系、nodata 照抄 `source`，地理变换平移到块的左上角。写法与现有 patch 一致到字节：
    文件头与目录由 GDAL 写，条带的压缩流再交给标准库 zlib 重压一遍——不同构建的 GDAL
    压出的字节不一样，理由见 `moondata.tiff.recompress_deflate`。
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
        output.write_bytes(recompress_deflate(output.read_bytes()))


def assert_on_grid(path: Path, grid: PixelGrid) -> None:
    """写出的影像必须恰好落在规划的网格上。

    两幅对齐影像错开一个像素在下游完全不报错，只会让所有窗口、所有标签系统性偏移——
    那种问题查起来极贵，所以写完立刻读回来逐项核对。
    """
    written = read_grid(path)
    problems = grid.differences(written)
    if not same_crs(grid.crs_wkt, written.crs_wkt):
        problems.append("坐标系不同")
    if problems:
        raise GridMismatch(f"{path} 没有落在规划的网格上：{'；'.join(problems)}")


def _open(path: Path) -> gdal.Dataset:
    try:
        return gdal.Open(str(path))
    except RuntimeError as error:
        raise RasterUnreadable(f"{path} 打不开：{error}") from error


def _bounds(dataset: gdal.Dataset) -> tuple[float, float, float, float]:
    x0, dx, _, y0, _, dy = dataset.GetGeoTransform()
    x1, y1 = x0 + dx * dataset.RasterXSize, y0 + dy * dataset.RasterYSize
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
