"""PROTOTYPE：核对 numpy 加权最小二乘能否复现研究分支的短距离 nugget。"""
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
v = json.loads((HERE.parent / "ground-truth-residuals" / "summary.json").read_text(encoding="utf-8"))["variogram"]
print(v.keys())
p = v["pooled"]
print(p.keys())
h, n, gy = (np.array(p[k]) for k in ("h", "n", "gy"))
for pw, name in ((1, "线性"), (2, "二次")):
    for hm in (60, 100, 150):
        m = h <= hm
        w = np.sqrt(n[m]) / gy[m]
        A = np.column_stack([np.ones(m.sum()), h[m] ** pw])
        c = np.linalg.lstsq(A * w[:, None], gy[m] * w, rcond=None)[0]
        print(name, hm, m.sum(), round(c[0], 3), round(float(np.sqrt(c[0])), 3), "研究分支", v["nugget_y"][name][str(hm)])
