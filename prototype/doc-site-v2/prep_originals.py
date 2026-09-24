"""PROTOTYPE（一次性）：「原型：ROI 页内容与版式」第三轮——原始产品与对齐影像的缩略图。

  assets/orig/<ROI>/ce2_<幅号>.jpg   CE-2 原始分幅缩略图（高 1600 像素）
  assets/orig/<ROI>/minirf.jpg       Mini-RF 原始条带缩略图（S1 dB，高 2400 像素）
  assets/orig.json                   各图尺寸、像元、投影，以及对齐影像范围在各图上的轮廓（0–1 相对坐标）

用法（newest 环境）：python prep_originals.py <data_root>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.warp import transform

import prep_assets as pa
from prep_roi_page import frame_proj

ROIS = {"ROI_054": "ROI_54", "ROI_066": "ROI_66", "ROI_003": "ROI_3"}


def outline(aligned, dst) -> list[list[float]]:
    """对齐影像的边框（每边 40 个点）换到 dst 的像素坐标，再除以宽高。"""
    W, H, t = aligned.width, aligned.height, aligned.transform
    edge = np.linspace(0, 1, 40)
    cols = np.concatenate([edge * W, np.full(40, W), (1 - edge) * W, np.zeros(40)])
    rows = np.concatenate([np.zeros(40), edge * H, np.full(40, H), (1 - edge) * H])
    xs, ys = t * (cols, rows)
    xs, ys = transform(aligned.crs, dst.crs, list(xs), list(ys))
    inv = ~dst.transform
    return [[round(c / dst.width, 4), round(r / dst.height, 4)] for c, r in (inv * (x, y) for x, y in zip(xs, ys))]


def thumb(d, height, bands=(1,)):
    h = height
    w = max(1, round(d.width * h / d.height))
    a = d.read(list(bands), out_shape=(len(bands), h, w), resampling=Resampling.average).astype(np.float32)
    return a


def main() -> None:
    data = Path(sys.argv[1])
    out = {}
    for roi, raw in ROIS.items():
        od = pa.OUT / "orig" / roi
        od.mkdir(parents=True, exist_ok=True)
        base = data / "raw" / raw
        with rasterio.open(base / "cropped/ce2/opt.tif") as al:
            frames = []
            for tif in sorted((base / "ce2").glob("CE2_*.tif")):
                tile = tif.stem.split("_")[4]
                m = re.search(r"(\d+)([NS])(\d+)([EW])", tif.stem.split("_")[5])
                with rasterio.open(tif) as d:
                    a = thumb(d, 1600)[0]
                    Image.fromarray(pa.stretch(a, a > 0)).save(od / f"ce2_{tile}.jpg", quality=80)
                    frames.append(dict(id=tif.stem, tile=tile, w=d.width, h=d.height, res=round(d.res[0], 4),
                                       proj=frame_proj(tif), lat=int(m[1]) * (1 if m[2] == "N" else -1),
                                       lon=int(m[3]) * (1 if m[4] == "E" else -1), outline=outline(al, d)))
            sar_tif = next(p for p in sorted((base / "minirf").glob("*.tif")) if p.name.lower().startswith("lsz"))
            with rasterio.open(sar_tif) as d:
                b = thumb(d, 2400, (1, 2))
                s1 = b[0] + b[1]
                valid = s1 > 0
                db = np.where(valid, 10 * np.log10(np.where(valid, s1, 1)), 0)
                Image.fromarray(np.where(valid, pa.stretch(db, valid), 0).astype(np.uint8)).save(od / "minirf.jpg", quality=80)
                sar = dict(w=d.width, h=d.height, res=round(d.res[0], 4), outline=outline(al, d))
            p = al.crs.to_dict()
            aligned = dict(w=al.width, h=al.height, res=round(al.res[0], 4), proj=f"Mercator，标准纬线 {p.get('lat_ts', 0):g}°")
        out[roi] = dict(frames=frames, sar=sar, aligned=aligned)
        print(roi, len(frames), sar["w"], sar["h"], aligned)
    (pa.OUT / "orig.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
