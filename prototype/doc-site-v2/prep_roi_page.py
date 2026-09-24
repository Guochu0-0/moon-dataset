"""PROTOTYPE（一次性）：「原型：ROI 页内容与版式」的额外素材，只做 ROI_027、ROI_054。

  assets/roi-extra.json          CE-2 分幅、对齐控制点对数、评测真值点对数
  assets/grids/<ROI>.json        补 ROI_027 的 patch 网格
  assets/patches/<ROI>/p<k>_*.jpg  每对 patch 的光学、SAR 小图（C 版点格子看 patch 用）

用法（newest 环境）：python prep_roi_page.py <data_root>
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image

import prep_assets as pa

ROIS = ("ROI_027", "ROI_054")
SIZE = 192


def tie_count(raw: str) -> tuple[int, str]:
    for gen in ("cropped_2", "cropped"):
        p = pa.REPO / "data/tie-points" / raw / gen / "opt_tie.pts"
        if p.is_file():
            rows = [l for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip() and not l.startswith(";")]
            return len(rows), gen
    return 0, ""


def patch_pngs(data: Path, row: dict) -> dict:
    base = data / "Processed_Data" / row["split"] / row["roi"]
    out = pa.OUT / "patches" / row["roi"]
    out.mkdir(parents=True, exist_ok=True)

    def one(p: Path):
        k = int(p.stem.split("_")[1])
        with rasterio.open(base / f"Optical/patch_{k}.tif") as d:
            opt = d.read(1, out_shape=(SIZE, SIZE)).astype(np.float32)
        with rasterio.open(p) as d:
            b = d.read(out_shape=(d.count, SIZE, SIZE)).astype(np.float32)
        s1 = b[0] + b[1]
        valid = s1 > 0
        db = np.where(valid, 10 * np.log10(np.where(valid, s1, 1)), 0)
        Image.fromarray(pa.stretch(opt, opt > 0)).save(out / f"p{k}_opt.jpg", quality=82)
        Image.fromarray(pa.stretch(db, valid)).save(out / f"p{k}_sar.jpg", quality=82)
        pts = []
        lab = base / f"Label/patch_{k}.txt"
        if lab.exists():
            for line in lab.read_text().split("\n"):
                if line.strip():
                    x1, y1, x2, y2 = map(float, line.split())
                    pts.append([round(x1, 1), round(-y1, 1), round(x2, 1), round(-y2, 1)])
        return k, pts

    with ThreadPoolExecutor(16) as ex:
        return {k: pts for k, pts in ex.map(one, (base / "SAR").glob("patch_*.tif"))}


def main() -> None:
    data = Path(sys.argv[1])
    rows = {r["roi"]: r for r in json.loads((pa.OUT / "rois.json").read_text(encoding="utf-8"))}
    extra = {}
    for roi in ROIS:
        r = rows[roi]
        frames = sorted(p.stem for p in (data / "raw" / r["raw"] / "ce2").glob("CE2_*.tif"))
        ties, gen = tie_count(r["raw"])
        if roi not in {p.stem for p in (pa.OUT / "grids").glob("*.json")}:
            pa.patch_grid(data, r)
        pts = patch_pngs(data, r)
        extra[roi] = dict(ce2_frames=frames, tie_points=ties, tie_gen=gen,
                          truth_points=sum(len(v) for v in pts.values()), points={str(k): v for k, v in sorted(pts.items()) if v})
        print(roi, len(frames), "frames,", ties, "ties,", len(pts), "patches")
    (pa.OUT / "roi-extra.json").write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
