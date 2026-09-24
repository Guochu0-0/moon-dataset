"""重叠区提取：从原始输入做出一对重叠区影像。

    python scripts/01_overlap.py [ROI_054 ...]

不带 ROI 就跑元数据表里的全部 67 个。已有产物直接覆盖。参数全部来自 `config.toml`。

一个 ROI 的输入是数据根下 `raw/ROI_<n>/` 里的若干幅 CE-2 分幅与一条 Mini-RF 条带；
输出是 `work/01_overlap/ROI_<nnn>/` 下落在同一像素网格上的 `opt.tif` 与 `sar.tif`。
下一步（人工标控制点）就在这对影像上做。

网格的坐标系默认取与 SAR 重叠最多的那幅分幅的投影；`config.toml` 的 `[grid_crs]` 里
列出的 ROI 取 SAR 的等距圆柱投影——那几个 ROI 的控制点当年就标在那个网格上，换一个
坐标系，控制点与它们算出的窗口全部作废。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from moondata import raster
from moondata.config import load_config
from moondata.errors import MoonDataError
from moondata.geometry import TARGET_RESOLUTION, PixelGrid, overlap_region, reference_tile
from moondata.raster import Footprint
from moondata.sources import load_roi_table, locate_inputs, padded_roi

OPTICAL_NAME = "opt.tif"
SAR_NAME = "sar.tif"
NODATA = 0.0
"""光学与 SAR 都写 0。下一步按它判一个窗口有没有缺数据。"""


def main(argv: list[str]) -> int:
    config = load_config()
    data_root = config.require_data_root()
    rois = [padded_roi(name) for name in argv] or [
        row.roi for row in load_roi_table(config.repo_root)
    ]
    for roi in rois:
        inputs = locate_inputs(data_root, roi)
        # 只读文件头：范围与坐标系，不读像素，秒级。
        tiles = [raster.read_footprint(path, ce2_tile=True) for path in inputs.optical_tiles]
        sar = raster.read_footprint(inputs.sar, ce2_tile=False)
        print(f"{roi}：{len(tiles)} 幅 CE-2 分幅 + {inputs.sar.name}", flush=True)
        for tile in tiles:
            if tile.corrected:
                print(f"  {tile.path.name} 头里的 lat_ts 写错，读取时已纠正（源文件未改动）")

        use_sar_crs = config.grid_crs.get(roi) == "sar"
        if use_sar_crs:
            print("  网格坐标系取自 SAR（config.toml 的 [grid_crs]）")
        grid = plan_grid(tiles, sar, use_sar_crs=use_sar_crs)
        print(
            f"  网格 {grid.width}×{grid.height}，像元 {grid.resolution} m，"
            f"原点 ({grid.origin_x:.3f}, {grid.origin_y:.3f})",
            flush=True,
        )
        out_dir = config.overlap_dir(roi)
        write_pair(tiles, sar, grid, out_dir, resample=config.resample)
        print(f"  已写出 {out_dir / OPTICAL_NAME}、{out_dir / SAR_NAME}", flush=True)
    return 0


def plan_grid(
    tiles: Sequence[Footprint], sar: Footprint, *, use_sar_crs: bool
) -> PixelGrid:
    """公共覆盖区外扩 1.2 倍，投到参考影像的坐标系，按 7.5 m 定网格。"""
    region = overlap_region([tile.lonlat for tile in tiles], sar.lonlat)
    reference = sar if use_sar_crs else tiles[reference_tile([t.lonlat for t in tiles], sar.lonlat)]
    return PixelGrid.covering(
        reference.crs_wkt, raster.project_box(region, reference.crs_wkt), TARGET_RESOLUTION
    )


def write_pair(
    tiles: Sequence[Footprint], sar: Footprint, grid: PixelGrid, out_dir: Path, *, resample: str
) -> None:
    """两边各一次 warp（光学顺带镶嵌），写完立刻回读、核对落在规划的网格上。"""
    for name, footprints, keep in ((OPTICAL_NAME, list(tiles), False), (SAR_NAME, [sar], True)):
        raster.warp_onto(
            footprints, grid, out_dir / name, resample=resample, nodata=NODATA, keep_nodata_values=keep
        )
        raster.assert_on_grid(out_dir / name, grid)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except MoonDataError as error:
        print(f"错误：{error}", file=sys.stderr)
        sys.exit(1)
