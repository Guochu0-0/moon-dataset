"""窗口清单（`data/windows/*.json`）的读取。

窗口清单记的是**历史产物的位置**。按正向复现的要求，生产路径上的代码一概不读它；
它只出现在验收里：拿正向算出的东西去对照它。本模块因此只被各步的 `--verify` 与测试用到。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from moondata.errors import WindowManifestUnreadable
from moondata.geometry import PixelGrid


@dataclass(frozen=True)
class ManifestWindow:
    index: int
    optical: tuple[int, int]
    """光学窗口左上角 (列, 行)。"""
    sar: tuple[int, int]


@dataclass(frozen=True)
class ManifestRoi:
    roi: str
    """补零写法，如 `ROI_006`。"""
    split: str
    patch_size: int
    grid: PixelGrid
    """当年切 patch 的那幅对齐影像的网格。"""
    windows: list[ManifestWindow]


def load_window_manifests(paths: Iterable[Path]) -> dict[str, ManifestRoi]:
    """把若干份清单合成一张 `ROI → 记录` 的表。"""
    rois: dict[str, ManifestRoi] = {}
    for path in paths:
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
            patch_size = int(document["patch_size"])
            for roi, record in document["rois"].items():
                rois[roi] = ManifestRoi(
                    roi=roi,
                    split=record["split"],
                    patch_size=patch_size,
                    grid=_grid(record["grid"]),
                    windows=[
                        ManifestWindow(int(w["index"]), tuple(w["optical"]), tuple(w["sar"]))
                        for w in record["patches"]
                    ],
                )
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise WindowManifestUnreadable(f"窗口清单读不动：{path}（{error}）") from error
    return rois


def _grid(record: dict) -> PixelGrid:
    # 清单里的 transform 是 rasterio 的 Affine 顺序 (a, b, c, d, e, f)，不是 GDAL 的 geotransform
    a, b, c, d, e, f = record["transform"]
    if b != 0 or d != 0 or a != -e:
        raise ValueError(f"网格不是北向上的正方形像元：{record['transform']}")
    return PixelGrid(record["crs"], c, f, a, int(record["width"]), int(record["height"]))
