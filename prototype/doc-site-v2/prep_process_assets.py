"""PROTOTYPE（一次性）：流程篇原型的配图素材。

从 ROI_054 的重叠区影像上截一段（光学行 9216–14848，含 7 个控制点和一个剔除窗口），
输出两张 PNG 与一份 JSON（控制点、保留窗口、剔除窗口）。读主仓库 work/ 与 data/。
用法：<newest 环境的 python> prep_process_assets.py
"""

import json
from pathlib import Path

import numpy as np
from osgeo import gdal
from PIL import Image

MAIN = Path(r"D:\Code\moon-dataset")
OUT = Path(__file__).resolve().parent / "assets" / "process"
ROI, Y0, Y1, K, P = "ROI_054", 9216, 14848, 4, 512   # 行范围、降采样倍数、patch 边长
REMOVED = [(512, 8192), (2048, 11776)]


def read(name):
    ds = gdal.Open(str(MAIN / "work/aligned" / ROI / f"{name}.tif"))
    return ds.GetRasterBand(1).ReadAsArray(0, Y0, ds.RasterXSize, Y1 - Y0).astype("float64")


def to_png(a, path):
    valid = a != 0
    lo, hi = np.percentile(a[valid], [1, 99])
    g = np.clip((a - lo) / (hi - lo), 0, 1) * 255
    g[~valid] = 0
    h, w = g.shape
    g = g[: h // K * K, : w // K * K].reshape(h // K, K, w // K, K).mean(axis=(1, 3))
    Image.fromarray(g.astype("uint8")).save(path)
    return w // K, h // K


OUT.mkdir(parents=True, exist_ok=True)
opt, sar = read("opt"), read("sar")
w, h = to_png(opt, OUT / "opt.png")
to_png(sar, OUT / "sar.png")

pts = []
for line in (MAIN / "data/tie-points/ROI_54/cropped/opt_tie.pts").read_text().splitlines():
    if line.startswith(";") or not line.strip():
        continue
    ox, oy, sx, sy = map(float, line.split()[:4])
    if Y0 <= oy < Y1:
        pts.append([ox, oy - Y0, sx, sy - Y0])

man = json.load(open(MAIN / "data/windows/windows.json", encoding="utf-8"))["rois"][ROI]
kept = [{"i": p["index"], "o": [p["optical"][0], p["optical"][1] - Y0], "s": [p["sar"][0], p["sar"][1] - Y0]}
        for p in man["patches"] if Y0 <= p["optical"][1] and p["optical"][1] + P <= Y1]
kept_set = {tuple(p["optical"]) for p in man["patches"]}
W = man["grid"]["width"]
rejected = [[x, y - Y0] for y in range(Y0, Y1 - P + 1, P) for x in range(0, W - P + 1, P)
            if (x, y) not in kept_set and (x, y) not in REMOVED]
json.dump({"roi": ROI, "y0": Y0, "k": K, "w": w, "h": h, "full_w": opt.shape[1], "full_h": opt.shape[0], "patch": P,
           "points": pts, "kept": kept, "rejected": rejected, "removed": [[x, y - Y0] for x, y in REMOVED]},
          open(OUT / "roi054.json", "w", encoding="utf-8"))
print(w, h, len(pts), "points", len(kept), "kept", len(rejected), "rejected")
