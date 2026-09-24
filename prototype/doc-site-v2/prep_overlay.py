"""PROTOTYPE（一次性）：「原型：ROI 页内容与版式」第四轮——原始产品叠合图。

把各 CE-2 分幅与 Mini-RF 条带重投影到重叠区影像的坐标系，画到同一张画布上：

  assets/overlay/<ROI>/ce2_<幅号>.png  各 CE-2 分幅（灰度 + 透明，各幅同一拉伸）
  assets/overlay/<ROI>/sar.png   Mini-RF 条带 S1 dB（灰度 + 透明）
  assets/overlay.json            画布尺寸、重叠区在画布上的矩形、各分幅与条带的外框（0–1 相对坐标）

只做 ROI_054、ROI_066、ROI_003（这三个 ROI 不涉及 lat_ts 纠正）。
用法（newest 环境）：python prep_overlay.py <data_root>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from PIL import Image
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds

import prep_assets as pa

ROIS = {"ROI_054": "ROI_54", "ROI_066": "ROI_66", "ROI_003": "ROI_3"}
MAX = 1400


def small(d, h, bands):
    w = max(1, round(d.width * h / d.height))
    a = d.read(bands, out_shape=(len(bands), h, w), resampling=Resampling.average, masked=True).astype(np.float32)
    return a.filled(np.nan), d.transform * Affine.scale(d.width / w, d.height / h)


def to_canvas(arr, src_t, src_crs, dst_t, dst_crs, shape):
    out = np.full(shape, np.nan, np.float32)
    reproject(arr, out, src_transform=src_t, src_crs=src_crs, dst_transform=dst_t, dst_crs=dst_crs,
              src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.bilinear)
    return out


def la(a, lo=None, hi=None):
    valid = np.isfinite(a)
    if lo is None:
        g = pa.stretch(np.where(valid, a, 0), valid)
    else:
        g = (np.clip((np.where(valid, a, lo) - lo) / (hi - lo + 1e-9), 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(np.dstack([g, np.where(valid, 255, 0).astype(np.uint8)]), "LA")


def main() -> None:
    data = Path(sys.argv[1])
    meta = {}
    for roi, raw in ROIS.items():
        base = data / "raw" / raw
        frames = sorted((base / "ce2").glob("CE2_*.tif"))
        sar_tif = next(p for p in sorted((base / "minirf").glob("*.tif")) if p.name.lower().startswith("lsz"))
        with rasterio.open(base / "cropped/ce2/opt.tif") as ov:
            crs, ob = ov.crs, ov.bounds
        boxes = {}
        for p in frames + [sar_tif]:
            with rasterio.open(p) as d:
                boxes[p] = transform_bounds(d.crs, crs, *d.bounds, densify_pts=50)
        L = min(b[0] for b in boxes.values()); B = min(b[1] for b in boxes.values())
        R = max(b[2] for b in boxes.values()); T = max(b[3] for b in boxes.values())
        res = max(R - L, T - B) / MAX
        W, H = round((R - L) / res), round((T - B) / res)
        dst_t = Affine(res, 0, L, 0, -res, T)
        rel = lambda b: [round((b[0] - L) / (R - L), 4), round((T - b[3]) / (T - B), 4),
                         round((b[2] - b[0]) / (R - L), 4), round((b[3] - b[1]) / (T - B), 4)]

        ce2 = np.full((H, W), np.nan, np.float32)
        layers = []
        for p in frames:
            with rasterio.open(p) as d:
                a, t = small(d, 2000, [1])
                a[0][a[0] == 0] = np.nan
                c = to_canvas(a[0], t, d.crs, dst_t, crs, (H, W))
            ce2 = np.where(np.isfinite(c), c, ce2)
            layers.append((p.stem.split("_")[4], c))
        with rasterio.open(sar_tif) as d:
            a, t = small(d, 3000, [1, 2])
            s1 = a[0] + a[1]
            db = np.where(s1 > 0, 10 * np.log10(np.where(s1 > 0, s1, 1)), np.nan)
            sar = to_canvas(db, t, d.crs, dst_t, crs, (H, W))
        od = pa.OUT / "overlay" / roi
        od.mkdir(parents=True, exist_ok=True)
        la(ce2).save(od / "ce2.png", optimize=True)
        lo, hi = np.nanpercentile(ce2, [2, 98])
        for tile, c in layers:
            la(c, lo, hi).save(od / f"ce2_{tile}.png", optimize=True)
        la(sar).save(od / "sar.png", optimize=True)
        meta[roi] = dict(w=W, h=H, km=[round((R - L) / 1000), round((T - B) / 1000)], overlap=rel(ob),
                         frames=[dict(id=p.stem, tile=p.stem.split("_")[4], box=rel(boxes[p])) for p in frames], sar=rel(boxes[sar_tif]))
        print(roi, W, H, meta[roi]["km"])
    (pa.OUT / "overlay.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
