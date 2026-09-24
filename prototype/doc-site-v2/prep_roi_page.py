"""PROTOTYPE（一次性）：「原型：ROI 页内容与版式」的素材——ROI 页左侧信息栏要的逐 ROI 事实。

  assets/roi-facts.json   每个 ROI：CE-2 分幅与各自投影、对齐控制点对数、评测真值点对数、缺号
  assets/grids/<ROI>.json 补 ROI_027 的 patch 网格

用法（newest 环境）：python prep_roi_page.py <data_root>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import rasterio

import prep_assets as pa

# lat_ts 被抄错的 5 幅，按幅名纠正（与流程代码一致）
LAT_TS_FIX = {"E215": 35.0, "E218": 35.0, "E219": 35.0, "I219": -21.0, "I236": -21.0}


def frame_proj(tif: Path) -> str:
    with rasterio.open(tif) as d:
        p = d.crs.to_dict()
    tile = tif.stem.split("_")[4]
    lat_ts = LAT_TS_FIX.get(tile, p.get("lat_ts"))
    if p.get("proj") == "merc":
        return f"Mercator，标准纬线 {lat_ts:g}°"
    if p.get("proj") == "stere":
        return f"极射赤面，{'北' if p['lat_0'] > 0 else '南'}极，标准纬线 {lat_ts:g}°"
    return p.get("proj", "?")


def tie_count(raw: str) -> int:
    for gen in ("cropped_2", "cropped"):
        p = pa.REPO / "data/tie-points" / raw / gen / "opt_tie.pts"
        if p.is_file():
            return len([l for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip() and not l.startswith(";")])
    return 0


def main() -> None:
    data = Path(sys.argv[1])
    rows = json.loads((pa.OUT / "rois.json").read_text(encoding="utf-8"))
    facts = {}
    for r in rows:
        frames = [dict(id=t.stem, proj=frame_proj(t)) for t in sorted((data / "raw" / r["raw"] / "ce2").glob("CE2_*.tif"))]
        base = data / "Processed_Data" / r["split"] / r["roi"]
        ids = sorted(int(p.stem.split("_")[1]) for p in (base / "SAR").glob("patch_*.tif"))
        missing = sorted(set(range(ids[-1] + 1)) - set(ids))
        truth = sum(len([l for l in p.read_text().split("\n") if l.strip()]) for p in (base / "Label").glob("patch_*.txt"))
        facts[r["roi"]] = dict(frames=frames, tie_points=tie_count(r["raw"]), truth_points=truth or None,
                               last_id=ids[-1], missing=missing)
        if r["roi"] == "ROI_027" and not (pa.OUT / "grids/ROI_027.json").exists():
            pa.patch_grid(data, r)
        print(r["roi"], len(frames), facts[r["roi"]]["tie_points"], truth, missing)
    (pa.OUT / "roi-facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=0), encoding="utf-8")


if __name__ == "__main__":
    main()
