"""原型（一次性）：候选 SAR 单通道表示与光学并排对比（issue #37，地图 #34）。

    python research/sar-repr-prototype/make.py [输出目录]

默认输出到仓库下 `work/research/sar-repr-prototype/`：每个 patch × 每种表示一张 JPEG，
外加 `index.html`（双击打开）。行是 patch，列是表示；鼠标悬停时同一行所有图上画同一个
像素位置的十字，用来对照同名地物。每张图下写截断到上下限的像素比例。

全局截断常数取自 `research/value-distribution/tables.md`（Train，issue #36）。
"""

from __future__ import annotations

import csv
import html
import sys
from pathlib import Path

import numpy as np
from osgeo import gdal
from PIL import Image

gdal.UseExceptions()

DATASET_ROOT = Path("G:/Lunar_Optical_SAR_Registration_Dataset/Processed_Data")
REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "work" / "research" / "sar-repr-prototype"

# (划分, ROI, 为什么选它)
ROIS = (
    ("Train", "ROI_021", "月海（风暴洋），光学极暗、IQR 4"),
    ("Train", "ROI_057", "月海（雨海），S1 最暗的 ROI 之一"),
    ("Test", "ROI_059", "月海，光学低对比"),
    ("Train", "ROI_079", "亮高地，S1 最亮，右视"),
    ("Train", "ROI_008", "背面高地，入射角 46.4°"),
    ("Train", "ROI_048", "入射角最小 45.5°"),
    ("Train", "ROI_047", "入射角最大 54.9°"),
    ("Train", "ROI_016", "高纬 66°S，阴影最多，右视"),
    ("Train", "ROI_027", "高纬 63°S，阴影多，右视"),
    ("Train", "ROI_003", "高纬 57°N，右视，光学对比强"),
    ("Test", "ROI_007", "右视，测试集"),
    ("Val", "ROI_035", "左视，验证集"),
)

EPS = 1e-6


def db(x: np.ndarray) -> np.ndarray:
    return 10 * np.log10(np.maximum(x, EPS))


def fixed(lo: float, hi: float):
    return lambda v: (lo, hi)


def per_patch(plo: float, phi: float):
    return lambda v: tuple(np.percentile(v, (plo, phi)))


# (键, 列标题, 取值, 截断方式, 说明)
REPRS = (
    ("s1_lin", "S1 线性 · 全局", lambda q: q["S1"], fixed(0.0194, 0.627), "Train p0.5–p99.5 = [0.019, 0.627]"),
    ("s1_amp", "S1 振幅 √S1 · 全局", lambda q: np.sqrt(np.maximum(q["S1"], 0)), fixed(0.0194**0.5, 0.627**0.5), "√ of Train p0.5–p99.5"),
    ("s1_db", "S1 dB · 全局", lambda q: db(q["S1"]), fixed(-17.1, -2.0), "Train p0.5–p99.5 = [−17.1, −2.0] dB"),
    ("s1_db_wide", "S1 dB · 固定宽窗", lambda q: db(q["S1"]), fixed(-25.0, 0.0), "SEN12MS 式 [−25, 0] dB"),
    ("s1_db_patch", "S1 dB · 逐 patch", lambda q: db(q["S1"]), per_patch(1, 99), "本 patch p1–p99"),
    ("s1_lin_patch", "S1 线性 · 逐 patch 2–98%", lambda q: q["S1"], per_patch(2, 98), "传统配准数据集的 8 位拉伸"),
    ("sc_db", "SC dB · 全局", lambda q: db(q["SC"]), fixed(-22.9, -5.85), "同向圆极化，Train p0.5–p99.5"),
    ("oc_db", "OC dB · 全局", lambda q: db(q["OC"]), fixed(-19.9, -4.04), "反向圆极化，Train p0.5–p99.5"),
    ("h_db", "H 路 b1 dB · 全局", lambda q: db(q["b1"]), fixed(-21.5, -4.72), "Train p0.5–p99.5"),
    ("v_db", "V 路 b2 dB · 全局", lambda q: db(q["b2"]), fixed(-20.6, -5.03), "Train p0.5–p99.5"),
)
OPTICAL = (
    ("opt", "光学 原值", fixed(0, 255), "uint8 原样"),
    ("opt_patch", "光学 · 逐 patch", per_patch(1, 99), "本 patch p1–p99"),
)


def quantities(bands: np.ndarray) -> dict[str, np.ndarray]:
    b1, b2, b3, b4 = bands.astype(np.float64)
    s1 = b1 + b2
    s4 = -2 * b4
    return {"b1": b1, "b2": b2, "S1": s1, "SC": 0.5 * (s1 - s4), "OC": 0.5 * (s1 + s4)}


def to_u8(value: np.ndarray, lo: float, hi: float) -> tuple[np.ndarray, float, float]:
    low, high = float((value <= lo).mean()), float((value >= hi).mean())
    scaled = np.clip((value - lo) / (hi - lo), 0, 1)
    return (scaled * 255 + 0.5).astype(np.uint8), low, high


def pick_patches(roi_dir: Path) -> list[tuple[int, str]]:
    """光学标准差最大的一个（结构最强）与居中的一个。"""
    stds = []
    for path in (roi_dir / "Optical").glob("patch_*.tif"):
        optical = gdal.Open(str(path)).ReadAsArray()
        stds.append((float(optical.std()), int(path.stem.split("_")[1])))
    stds.sort()
    return [(stds[-1][1], "光学起伏最强"), (stds[len(stds) // 2][1], "光学起伏居中")]


def main() -> None:
    meta = {}
    with open(REPO_ROOT / "data" / "metadata" / "minirf_metadata.csv", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            meta["ROI_%03d" % int(row["ROI"].split("_")[1])] = row

    img_dir = OUT_DIR / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    columns = [(k, t, n) for k, t, _, n in OPTICAL] + [(k, t, n) for k, t, _, _, n in REPRS]
    rows_html = []

    for split, roi, why in ROIS:
        roi_dir = DATASET_ROOT / split / roi
        m = meta[roi]
        for number, which in pick_patches(roi_dir):
            optical = gdal.Open(str(roi_dir / "Optical" / f"patch_{number}.tif")).ReadAsArray().astype(np.float64)
            q = quantities(gdal.Open(str(roi_dir / "SAR" / f"patch_{number}.tif")).ReadAsArray())
            cells = []
            items = [(k, optical, clip) for k, _, clip, _ in OPTICAL]
            items += [(k, value(q), clip) for k, _, value, clip, _ in REPRS]
            for key, value, clip in items:
                lo, hi = clip(value)
                u8, low, high = to_u8(value, lo, hi)
                name = f"{roi}_{number}_{key}.jpg"
                Image.fromarray(u8).save(img_dir / name, quality=90)
                cells.append(
                    f'<td data-k="{key}"><div class="w"><img src="img/{name}"><i class="h"></i><i class="v"></i></div>'
                    f"<small>[{lo:.3g}, {hi:.3g}] 压到下限 {low:.1%}，上限 {high:.1%}</small></td>"
                )
            label = (
                f"<b>{split} {roi} patch_{number}</b><br>{html.escape(why)}<br>{which}<br>"
                f"入射角 {m['入射角_deg']}°，{'左' if m['视向'] == 'LEFT' else '右'}视<br>"
                f"光学 std {optical.std():.1f}，S1 dB 中位 {np.median(db(q['S1'])):.1f}"
            )
            rows_html.append(f'<tr><th class="lab">{label}</th>{"".join(cells)}</tr>')
            print(split, roi, number, which, flush=True)

    head = "".join(f'<th data-k="{k}">{html.escape(t)}<br><small>{html.escape(n)}</small></th>' for k, t, n in columns)
    toggles = "".join(
        f'<label><input type="checkbox" checked data-k="{k}">{html.escape(t)}</label>' for k, t, _ in columns
    )
    (OUT_DIR / "index.html").write_text(PAGE.format(toggles=toggles, head=head, rows="\n".join(rows_html)), encoding="utf-8")
    print("写出", OUT_DIR / "index.html")


PAGE = """<!doctype html><html lang="zh"><meta charset="utf-8">
<title>原型：候选 SAR 单通道表示与光学并排对比</title>
<style>
body{{font:13px sans-serif;margin:0;background:#222;color:#ddd}}
header{{position:sticky;top:0;background:#111;padding:6px 10px;z-index:3}}
header label{{margin-right:10px;white-space:nowrap}}
table{{border-collapse:collapse}} td,th{{padding:3px;vertical-align:top;text-align:left}}
thead th{{position:sticky;top:64px;background:#111;z-index:2;font-weight:normal}}
th.lab{{width:170px;font-weight:normal;position:sticky;left:0;background:#222;z-index:1}}
.w{{position:relative;width:var(--s);height:var(--s)}} img{{width:100%;height:100%;image-rendering:pixelated;display:block}}
.w i{{position:absolute;background:#f33;pointer-events:none;display:none}} .h{{height:1px;left:0;right:0}} .v{{width:1px;top:0;bottom:0}}
tr.x .w i{{display:block}} small{{color:#999;display:block;width:var(--s)}}
</style>
<header><b>PROTOTYPE，可删</b>（issue #37）。尺寸
<select id=sz><option>192</option><option selected>256</option><option>384</option><option>512</option></select>
悬停：同一行画同一像素位置的十字。 列：{toggles}</header>
<table><thead><tr><th class="lab"></th>{head}</tr></thead><tbody>
{rows}
</tbody></table>
<script>
const root=document.documentElement,set=s=>root.style.setProperty('--s',s+'px');set(256);
sz.onchange=()=>set(sz.value);
document.querySelectorAll('header input').forEach(c=>c.onchange=()=>document.querySelectorAll(`[data-k="${{c.dataset.k}}"]`).forEach(e=>e.style.display=c.checked?'':'none'));
document.querySelectorAll('.w').forEach(w=>{{w.onmousemove=e=>{{const r=w.getBoundingClientRect(),fx=(e.clientX-r.left)/r.width,fy=(e.clientY-r.top)/r.height,tr=w.closest('tr');
tr.classList.add('x');tr.querySelectorAll('.w').forEach(o=>{{o.querySelector('.h').style.top=fy*100+'%';o.querySelector('.v').style.left=fx*100+'%'}})}};
w.onmouseleave=()=>w.closest('tr').classList.remove('x')}});
</script></html>
"""

if __name__ == "__main__":
    main()
