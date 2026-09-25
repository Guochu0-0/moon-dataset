```python
import numpy as np

def variogram(xy, r, edges):
    """点位 xy (N, 2)、残差 r (N,) → 各距离档的平均距离、点对数、γ。"""
    i, j = np.triu_indices(len(r), k=1)
    h = np.hypot(*(xy[i] - xy[j]).T)
    k = np.digitize(h, edges) - 1
    ok = (k >= 0) & (k < len(edges) - 1)
    k, h, half_sq = k[ok], h[ok], 0.5 * (r[i] - r[j])[ok] ** 2
    n = np.bincount(k, minlength=len(edges) - 1)
    return (np.bincount(k, h, len(edges) - 1) / n, n,
            np.bincount(k, half_sq, len(edges) - 1) / n)

def nugget(h, n, g, h_max, power=1):
    """γ ≈ c₀ + c₁·h^power 在 h ≤ h_max 上加权拟合，返回 c₀。"""
    m = h <= h_max
    w = np.sqrt(n[m]) / g[m]
    a = np.column_stack([np.ones(m.sum()), h[m] ** power])
    return np.linalg.lstsq(a * w[:, None], g[m] * w, rcond=None)[0][0]
```
