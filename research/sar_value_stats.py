"""SAR patch 的数值概况：各极化量的非正值比例与 dB 分位数（issue #35 调研用）。

用法：python research/sar_value_stats.py <Processed_Data 根> [每个划分抽样的 patch 数]
只读数据盘，不写任何文件；结果打印到标准输出。
"""

import sys
from pathlib import Path

import numpy as np
from osgeo import gdal

gdal.UseExceptions()


def quantities(b):
    b1, b2, b3, b4 = b.astype(np.float64)
    s1 = b1 + b2
    s4 = -2 * b4
    return {
        "b1 (H)": b1,
        "b2 (V)": b2,
        "b3 (Re)": b3,
        "b4 (Im)": b4,
        "S1": s1,
        "SC": 0.5 * (s1 - s4),
        "OC": 0.5 * (s1 + s4),
    }


def main():
    root = Path(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    rng = np.random.default_rng(0)
    for split in ("Train", "Val", "Test"):
        files = sorted((root / split).glob("ROI_*/SAR/patch_*.tif"))
        if not files:
            continue
        pick = rng.choice(len(files), size=min(n, len(files)), replace=False)
        acc = {}
        per_patch_p99 = []
        for i in pick:
            q = quantities(gdal.Open(str(files[i])).ReadAsArray())
            for k, v in q.items():
                acc.setdefault(k, []).append(v.ravel())
            s1 = q["S1"]
            per_patch_p99.append(np.percentile(s1, 99) / max(np.percentile(s1, 1), 1e-12))
        print(f"== {split}: {len(pick)} / {len(files)} patches")
        for k, parts in acc.items():
            v = np.concatenate(parts)
            p = np.percentile(v, [0.1, 1, 50, 99, 99.9])
            print(
                f"{k:8s} <=0: {np.mean(v <= 0):7.4%}  <0: {np.mean(v < 0):7.4%}  "
                f"p0.1/1/50/99/99.9 = {p[0]:.4g} {p[1]:.4g} {p[2]:.4g} {p[3]:.4g} {p[4]:.4g}"
            )
        s1 = np.concatenate(acc["S1"])
        pos = s1[s1 > 0]
        db = 10 * np.log10(pos)
        pd = np.percentile(db, [0.1, 1, 2, 50, 98, 99, 99.9])
        print("S1 dB   p0.1/1/2/50/98/99/99.9 = " + " ".join(f"{x:.2f}" for x in pd))
        r = np.array(per_patch_p99)
        print(
            "S1 per-patch p99/p1 ratio (linear): median %.2f, p5 %.2f, p95 %.2f"
            % (np.median(r), np.percentile(r, 5), np.percentile(r, 95))
        )


if __name__ == "__main__":
    main()
