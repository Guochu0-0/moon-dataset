"""第一步：算重叠区，并把光学与 SAR 对齐到同一像素网格上。

一个 ROI 的原始输入是若干幅 CE-2 分幅与一条 Mini-RF 条带（数据根下 `raw/ROI_<n>/`）。
本步求两者的公共范围、定出网格（规则见 `moondata.geometry.grid`），再各用**一次**
`gdal.Warp` 把两边重采样到这个网格上，写出一对对齐影像。

全程正向：网格只从原始输入算出，不读数据盘上任何既有对齐产物。`--verify` 才拿算出的
网格去对照窗口清单里记的历史网格——那是验收，不影响产出。

网格的坐标系
------------
默认沿用光学分幅的投影（与 SAR 重叠最多的那幅，见 `reference_tile`）。但历史上有
ROI_34、ROI_57、ROI_58、ROI_70 四个 ROI 的对齐影像是在 **SAR 的等距圆柱投影**下做的
（当年的脚本把 SAR 当作参考图传了进去），它们的对齐控制点也就标在那个网格上。复现它们
要显式传 `grid_crs=GridCrs.SAR`（命令行 `--grid-crs sar`）。这是一个参数而不是按 ROI 号
写死的分支：选哪个坐标系是做数据的人的决定，代码不替人记。

已知对不上的两个 ROI
--------------------
- **ROI_65**：历史网格原点差 0.27 m、多一行。当年的输入是一幅中间镶嵌 `merged.tif`，
  它是在其中一幅分幅的坐标系已被旧脚本改坏之后生成的，范围比分幅并集少了 3 m。
  正向算不出一幅被改坏的中间文件的范围——记为「历史产物，来源不可复现」。
- **ROI_73**：历史网格只在用**未纠正**的 E215 坐标系时才对得上，即当年就是按错误的
  位置做的（见 data/README.md）。同样不可复现。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from moondata import raster
from moondata.errors import MetadataUnreadable, RawInputsUnavailable
from moondata.geometry import PixelGrid, overlap_region, reference_tile
from moondata.geometry.grid import TARGET_RESOLUTION
from moondata.metadata import padded_roi, raw_roi_name
from moondata.sources import decode_product_id, parse_ce2_tile

RAW_DIRNAME = "raw"
OPTICAL_NAME = "opt.tif"
SAR_NAME = "sar.tif"
GRID_RECORD_NAME = "grid.json"
DEFAULT_RESAMPLE = "cubic"
"""数据盘上现有的对齐影像是用 cubic 重做过的（旧的最近邻有 14 px 网纹），跟它一致。"""
NODATA = 0.0


class GridCrs(Enum):
    OPTICAL = "optical"
    SAR = "sar"


@dataclass(frozen=True)
class RoiSources:
    roi: str
    """补零写法，如 `ROI_035`。"""
    optical_tiles: list[Path]
    sar: Path


@dataclass(frozen=True)
class AlignmentPlan:
    sources: RoiSources
    grid: PixelGrid
    grid_crs: GridCrs
    reference: Path
    """网格坐标系取自哪幅影像。"""
    optical_footprints: list[Any]
    sar_footprint: Any
    """栅格层的 `Footprint`：规划时读到的坐标系（已纠正）与范围，对齐时原样沿用，
    不再读一遍文件头。类型不写死，免得本模块在 import 时就牵出地理库。"""

    @property
    def corrected_tiles(self) -> list[Path]:
        """头里 `lat_ts` 写错、读取时纠正了的分幅。"""
        return [f.path for f in self.optical_footprints if f.corrected]


def locate_sources(data_root: Path, roi: str) -> RoiSources:
    """找出一个 ROI 的原始输入。

    `ce2/` 下只认名字是 CE-2 分幅号的 `.tif`：历史上的镶嵌脚本往这里写过 `merged.tif`，
    把它当分幅就又多镶嵌、多插值一次。`minirf/` 下有多幅时只认名字是 Mini-RF 产品 ID
    的那幅（ROI_54 另有一份同样大小的 `sar.tif` 副本）。
    """
    try:
        padded, raw_name = padded_roi(roi), raw_roi_name(roi)
    except MetadataUnreadable as error:
        raise RawInputsUnavailable(str(error)) from error
    roi_dir = data_root / RAW_DIRNAME / raw_name
    tiles = sorted(p for p in (roi_dir / "ce2").glob("*.tif") if _is_ce2_tile(p))
    if not tiles:
        raise RawInputsUnavailable(f"{roi_dir / 'ce2'} 下没有 CE-2 分幅")
    strips = sorted((roi_dir / "minirf").glob("*.tif"))
    if len(strips) > 1:
        strips = [p for p in strips if _is_minirf_product(p)]
    if len(strips) != 1:
        raise RawInputsUnavailable(
            f"{roi_dir / 'minirf'} 下应恰有一条 Mini-RF 条带，实际认出 {len(strips)} 条"
        )
    return RoiSources(padded, tiles, strips[0])


def plan_alignment(sources: RoiSources, grid_crs: GridCrs = GridCrs.OPTICAL) -> AlignmentPlan:
    """只读原始输入的文件头，定出对齐网格。不读像素，秒级完成。"""
    backend = raster.backend()
    tiles = [backend.read_footprint(p, ce2_tile=True) for p in sources.optical_tiles]
    sar = backend.read_footprint(sources.sar, ce2_tile=False)
    region = overlap_region([t.lonlat for t in tiles], sar.lonlat)
    reference = sar if grid_crs is GridCrs.SAR else tiles[reference_tile([t.lonlat for t in tiles], sar.lonlat)]
    grid = PixelGrid.covering(
        reference.crs_wkt, backend.project_box(region, reference.crs_wkt), TARGET_RESOLUTION
    )
    return AlignmentPlan(sources, grid, grid_crs, reference.path, tiles, sar)


def align(plan: AlignmentPlan, out_dir: Path, *, resample: str = DEFAULT_RESAMPLE) -> None:
    """写出 `out_dir/opt.tif`、`out_dir/sar.tif`，并留一份 `grid.json` 记下怎么来的。"""
    backend = raster.backend()
    for name, inputs in ((OPTICAL_NAME, plan.optical_footprints), (SAR_NAME, [plan.sar_footprint])):
        backend.warp_onto(inputs, plan.grid, out_dir / name, resample=resample, nodata=NODATA)
        backend.assert_on_grid(out_dir / name, plan.grid)
    _write_record(plan, out_dir, resample)


SELECTION_RECIPE = "selection"
"""`grid.json` 里 `resample` 一栏的值，标明这是一对筛选影像。"""


def align_selection(plan: AlignmentPlan, out_dir: Path) -> None:
    """按当年切片时的做法重做一对对齐影像——**筛选影像**，只用来判窗口留不留。

    光学一次最近邻 warp；SAR 两次最近邻（先重投影、再裁切降采样，见
    `gdal_backend.warp_twice_onto`）。为什么非得这样，见 `moondata.patches`。
    """
    backend = raster.backend()
    backend.warp_onto(plan.optical_footprints, plan.grid, out_dir / OPTICAL_NAME, resample="near", nodata=NODATA)
    backend.warp_twice_onto(plan.sar_footprint, plan.grid, out_dir / SAR_NAME, nodata=NODATA)
    for name in (OPTICAL_NAME, SAR_NAME):
        backend.assert_on_grid(out_dir / name, plan.grid)
    _write_record(plan, out_dir, SELECTION_RECIPE)


def has_selection(plan: AlignmentPlan, out_dir: Path) -> bool:
    """`out_dir` 里是否已有一对落在 `plan` 网格上、由同样输入做出的筛选影像，可以直接复用。"""
    try:
        record = json.loads((out_dir / GRID_RECORD_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    expected = _record(plan, SELECTION_RECIPE)
    keys = ("resample", "optical_tiles", "sar", "grid_crs", "width", "height", "geotransform")
    return all(record.get(k) == expected[k] for k in keys) and all(
        (out_dir / name).is_file() for name in (OPTICAL_NAME, SAR_NAME)
    )


def _record(plan: AlignmentPlan, resample: str) -> dict[str, Any]:
    return {
        "roi": plan.sources.roi,
        "grid_crs": plan.grid_crs.value,
        "reference": plan.reference.name,
        "optical_tiles": [p.name for p in plan.sources.optical_tiles],
        "corrected_tiles": [p.name for p in plan.corrected_tiles],
        "sar": plan.sources.sar.name,
        "resample": resample,
        "nodata": NODATA,
        "width": plan.grid.width,
        "height": plan.grid.height,
        "geotransform": list(plan.grid.geotransform),
        "crs_wkt": plan.grid.crs_wkt,
    }


def _write_record(plan: AlignmentPlan, out_dir: Path, resample: str) -> None:
    record = _record(plan, resample)
    record["gdal"] = raster.backend().gdal_version()
    (out_dir / GRID_RECORD_NAME).write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def grid_differences(planned: PixelGrid, historical: PixelGrid) -> list[str]:
    """正向规划的网格与窗口清单里记的历史网格之间的差异；空列表即一致。"""
    problems = planned.differences(historical)
    if not raster.backend().same_crs(planned.crs_wkt, historical.crs_wkt):
        problems.append("坐标系不同")
    return problems


def _is_ce2_tile(path: Path) -> bool:
    try:
        parse_ce2_tile(path.name)
    except MetadataUnreadable:
        return False
    return True


def _is_minirf_product(path: Path) -> bool:
    try:
        decode_product_id(path.stem)
    except MetadataUnreadable:
        return False
    return True
