"""PROTOTYPE（一次性）：「原型：文档站的视觉设计」的素材准备。

读数据盘与仓库，输出 assets/：
  moon-4k.jpg / moon-2k.jpg   LROC 全月拼图（NASA SVS 4720），灰度，经度 -180..180
  rois.json                   67 个 ROI：划分、数量、经纬范围、条带参数、已知问题
  samples/                    带评测真值点的 patch 配对样例（PNG + 点）
  grids/<ROI>.json            各 patch 在 ROI 缩略图上的位置

需要 rasterio（用 newest 环境）。用法：
  python prep_assets.py <data_root> <lroc_color_poles_4k.tif>
"""

from __future__ import annotations

import csv
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import transform_bounds

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "assets"
MOON_GEO = "+proj=longlat +R=1737400 +no_defs"
SPLIT_DIR = {"Train": "Train", "Val": "Val", "Test": "Test"}


def moon_basemap(src: Path) -> None:
    with rasterio.open(src) as d:
        rgb = d.read().transpose(1, 2, 0)
    img = Image.fromarray(rgb).convert("L")
    img.save(OUT / "moon-4k.jpg", quality=82)
    img.resize((2048, 1024), Image.LANCZOS).save(OUT / "moon-2k.jpg", quality=85)


def roi_table() -> list[dict]:
    index = (REPO / "docs/rois/index.md").read_text(encoding="utf-8")
    rows = {}
    for m in re.finditer(r"^\| \[(ROI_\d+)\]\([^)]*\) \| (\S+) \| (\d+) \| (\S+) \| ([\d.]+)° \| (\w+) \| (.*?) \|$", index, re.M):
        roi, split_zh, n, truth, inc, look, issues = m.groups()
        rows[roi] = dict(roi=roi, split_zh=split_zh, patches=int(n), truth_patches=None if truth == "—" else int(truth),
                         incidence=float(inc), look=look, issues=[s for s in issues.split("；") if s])
    with open(REPO / "data/metadata/minirf_metadata.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            key = f"ROI_{int(r['ROI'].split('_')[1]):03d}"
            if key in rows:
                rows[key].update(split=r["划分"], raw=r["ROI"], product_id=r["PRODUCT_ID"], time=r["成像时刻UTC"],
                                 width_px=int(r["条带宽_px"]), length_px=int(r["条带长_px"]))
    return [rows[k] for k in sorted(rows)]


def roi_bounds(data: Path, row: dict) -> None:
    with rasterio.open(data / "raw" / row["raw"] / "cropped/ce2/sar.tif") as d:
        w, s, e, n = transform_bounds(d.crs, MOON_GEO, *d.bounds, densify_pts=50)
    row["bbox"] = [round(w, 4), round(s, 4), round(e, 4), round(n, 4)]
    row["center"] = [round((w + e) / 2, 3), round((s + n) / 2, 3)]


def patch_grid(data: Path, row: dict) -> None:
    """每个 patch 的 SAR 范围，换算到 ROI 缩略图的像素坐标（缩略图与对齐影像同范围）。"""
    with rasterio.open(data / "raw" / row["raw"] / "cropped/ce2/sar.tif") as d:
        inv, W, H = ~d.transform, d.width, d.height
    thumb = Image.open(REPO / f"docs/rois/thumbnails/{row['roi']}_sar.png")
    sx, sy = thumb.width / W, thumb.height / H
    base = data / "Processed_Data" / row["split"] / row["roi"]
    label = base / "Label"

    def one(p: Path):
        k = int(p.stem.split("_")[1])
        with rasterio.open(p) as t:
            b = t.bounds
        c0, r0 = inv * (b.left, b.top)
        c1, r1 = inv * (b.right, b.bottom)
        return dict(i=k, x=round(c0 * sx, 2), y=round(r0 * sy, 2), w=round((c1 - c0) * sx, 2), h=round((r1 - r0) * sy, 2),
                    truth=(label / f"patch_{k}.txt").exists())

    with ThreadPoolExecutor(16) as ex:
        cells = sorted(ex.map(one, (base / "SAR").glob("patch_*.tif")), key=lambda c: c["i"])
    (OUT / "grids").mkdir(exist_ok=True)
    (OUT / "grids" / f"{row['roi']}.json").write_text(json.dumps(dict(w=thumb.width, h=thumb.height, cells=cells)), encoding="utf-8")


def stretch(a: np.ndarray, valid: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(a[valid], [2, 98]) if valid.any() else (0, 1)
    return (np.clip((a - lo) / (hi - lo + 1e-9), 0, 1) * 255).astype(np.uint8)


def render_pair(data: Path, row: dict, k: int, name: str) -> dict:
    base = data / "Processed_Data" / row["split"] / row["roi"]
    with rasterio.open(base / f"Optical/patch_{k}.tif") as d:
        opt = d.read(1).astype(np.float32)
        ob = d.bounds
    with rasterio.open(base / f"SAR/patch_{k}.tif") as d:
        b = d.read().astype(np.float32)
        sb = d.bounds
    s1 = b[0] + b[1]
    valid = s1 > 0
    db = np.where(valid, 10 * np.log10(np.where(valid, s1, 1)), 0)
    (OUT / "samples").mkdir(exist_ok=True)
    Image.fromarray(stretch(opt, opt > 0)).save(OUT / "samples" / f"{name}_opt.png", optimize=True)
    Image.fromarray(stretch(db, valid)).save(OUT / "samples" / f"{name}_sar.png", optimize=True)
    pts = []
    for line in (base / f"Label/patch_{k}.txt").read_text().split("\n"):
        if line.strip():
            x1, y1, x2, y2 = map(float, line.split())
            pts.append([round(x1, 1), round(-y1, 1), round(x2, 1), round(-y2, 1)])
    return dict(name=name, roi=row["roi"], split=row["split"], patch=k, points=pts,
                offset_m=[round(ob.left - sb.left), round(ob.top - sb.top)])


def pick_samples(data: Path, rows: list[dict], per_roi: int = 1) -> list[dict]:
    """每个带评测真值点的 ROI 挑一对：真值点多、有效像素全、光学纹理丰富。"""
    out = []
    for row in rows:
        if row["split"] == "Train":
            continue
        base = data / "Processed_Data" / row["split"] / row["roi"]
        best = None
        for txt in sorted(base.glob("Label/patch_*.txt"))[:80]:
            k = int(txt.stem.split("_")[1])
            n = len([l for l in txt.read_text().split("\n") if l.strip()])
            with rasterio.open(base / f"Optical/patch_{k}.tif") as d:
                a = d.read(1, out_shape=(128, 128))
            if (a == 0).mean() > 0.001:
                continue
            score = n * 5 + a.std()
            if best is None or score > best[0]:
                best = (score, k)
        if best:
            out.append(render_pair(data, row, best[1], f"{row['roi']}_p{best[1]}"))
    return out


def render_bands(data: Path, split: str, roi: str, k: int) -> None:
    """一对 SAR patch 的 4 个波段与 S1、CPR，给「数据来源」的波段一节配图。"""
    with rasterio.open(data / "Processed_Data" / split / roi / f"SAR/patch_{k}.tif") as d:
        b = d.read().astype(np.float64)
    valid = (b[0] + b[1]) > 0
    s1, s4 = b[0] + b[1], -2 * b[3]
    sc, oc = 0.5 * (s1 - s4), 0.5 * (s1 + s4)
    cpr = np.where(valid & (oc > 0), sc / np.where(oc > 0, oc, 1), 0)
    out = OUT / "bands"
    out.mkdir(exist_ok=True)
    for name, a in [("b1", b[0]), ("b2", b[1]), ("b3", b[2]), ("b4", b[3]), ("s1", 10 * np.log10(np.where(valid, s1, 1))), ("cpr", cpr)]:
        Image.fromarray(stretch(a, valid)).resize((256, 256), Image.LANCZOS).save(out / f"{name}.png", optimize=True)
    stats = {n: [float(np.percentile(a[valid], 2)), float(np.percentile(a[valid], 98))] for n, a in [("b3", b[2]), ("b4", b[3]), ("cpr", cpr)]}
    (out / "bands.json").write_text(json.dumps(dict(roi=roi, patch=k, stats=stats)), encoding="utf-8")


def main() -> None:
    data, lroc = Path(sys.argv[1]), Path(sys.argv[2])
    OUT.mkdir(exist_ok=True)
    if len(sys.argv) > 3 and sys.argv[3] == "bands":
        render_bands(data, "Test", "ROI_007", 138)
        return
    moon_basemap(lroc)
    rows = roi_table()
    for r in rows:
        roi_bounds(data, r)
    (OUT / "rois.json").write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")
    samples = pick_samples(data, rows)
    (OUT / "samples.json").write_text(json.dumps(samples), encoding="utf-8")
    for r in rows:
        if r["roi"] in ("ROI_006", "ROI_008", "ROI_054"):
            patch_grid(data, r)
    print(len(rows), "rois;", len(samples), "samples")


if __name__ == "__main__":
    main()
