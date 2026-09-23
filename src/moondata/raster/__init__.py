"""栅格层：唯一依赖 GDAL/pyproj 的地方——读写、镶嵌、重投影、裁切。

**所有地理库调用都必须收在这里。** 其余模块不得 import GDAL 或 pyproj，否则
「文档档不装 GDAL 也能完整工作」这条就破了。

地理库也不在 import 本包时加载：调用方经 `backend()` 取用，装不上 GDAL 的机器上
`import moondata.raster` 照样成功，只有真正要读影像的那一刻才报一句干净的中文。

本层不单独设测试接缝：它是对外部库的薄封装，正确性由命令行端到端结果体现。
"""

from __future__ import annotations

from types import ModuleType

from moondata.errors import GeoLibraryUnavailable


def backend() -> ModuleType:
    """返回 `moondata.raster.gdal_backend`。没装 GDAL/pyproj 时抛 `GeoLibraryUnavailable`。"""
    try:
        from moondata.raster import gdal_backend
    except ImportError as error:
        raise GeoLibraryUnavailable(
            f"本命令要读写影像，需要 GDAL 与 pyproj（{error}）。"
            "请用数据处理档环境：conda env create -f environment-data.yml"
        ) from error
    return gdal_backend
