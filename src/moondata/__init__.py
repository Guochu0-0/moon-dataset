"""moondata —— CE-2 7 m DOM × Mini-RF SAR 配准数据集的处理与自检工具。

顶层结构即流程图。四步流程各占一个子包：

    overlap    算重叠区
    tiepoints  人工标注的对齐控制点
    transform  估计全局变换
    patches    切分 patch

其下两个支撑层：

    raster     唯一依赖 GDAL/pyproj 的地方
    geometry   纯 numpy，无地理库，可被完整单测

这条分界线是有意画的：安装 GDAL 的困难只应拦住真正需要重跑数据的人。
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
