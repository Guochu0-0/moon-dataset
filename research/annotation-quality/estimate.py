"""评测真值点的标注误差：三种估计方法，写出「标注质量」页上的全部数字。

    PYTHONPATH=src python research/annotation-quality/estimate.py

只读仓库：`data/ground-truth/` 的评测真值点、`data/tie-points/` 的控制点、元数据表，
以及 `windows.py` 写出的 `windows.csv`。产出写到本目录：`tables.md`（人读）与
`results.json`（`figures.py` 画图用）。

记号：一对评测真值点，光学 p、SAR q，patch 内像素 (列, 行)，y 向下为正（文件里 y 取负
存储，读入时翻回）；错位 d = q − p。放回重叠区影像坐标后记作 P、Q。σ 是一对点合成的
标注误差在一个坐标轴上的标准差，单位像素。

1. 最小二乘拟合残差：每个 patch 每个坐标轴拟合 d = a·x + b·y + c，残差平方和跨 patch
   汇总 σ̂² = ΣRSS / Σ(N − 3)；学生化残差超过 3 的点逐个剔除后重拟合。
2. 变异函数：同一 ROI 内点对的 ½(rᵢ − rⱼ)² 按光学侧距离分档，r = Q − G(P) 是对该 ROI
   控制点全局仿射 G 的残差；短距离段线性、二次加权外推到 0，截距即块金值。
3. 重复测量：评测真值点与控制点落在同一处地物上的配对，两次偏差之差的方差是 2σ² 加
   控制点坐标取整的量化方差。

统计量只用 numpy：χ² 分位用 Wilson–Hilferty 近似（自由度数千，误差远小于报告的位数），
Spearman 秩相关的 p 值用 t 分布的闭式。
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from moondata.config import REPO_ROOT
from moondata.geometry import apply_transform, estimate_affine
from moondata.sources import ground_truth_file, load_metadata, load_tie_points

HERE = Path(__file__).resolve().parent
OUTLIER_Z = 3.0
LAG_EDGES = np.array([0, 15, 30, 45, 60, 80, 100, 130, 160, 200, 250, 320, 400, 500, 650, 800, 1000], dtype=float)
"""变异函数的距离分档（像素）。外推只用到 150 像素以内，更远的档只为画出 γ 的走势。"""
MIN_PAIRS = 30
"""点对少于这个数的档不报：γ 的相对标准误约为 √(2/n)。"""
NUGGET_FITS = [(power, hmax) for power in (1, 2) for hmax in (60, 100, 150)]
"""外推块金值的 6 种方式：(1 线性 / 2 二次, 只用 h ≤ hmax 的档)。"""
REPEAT_RADIUS = 5.0
REPEAT_THRESHOLDS = (1.0, 2.0, 3.0, 5.0)
QUANTISATION = 2 / 12
"""控制点光学、SAR 坐标都取整到像素，各带 1/12 像素² 的均匀量化方差。"""
SHUFFLES = 200
Z975 = 1.959963984540054


# ---------------------------------------------------------------------------
# 读入


@dataclass
class Patch:
    split: str
    roi: str
    index: int
    opt_window: np.ndarray
    sar_window: np.ndarray
    p: np.ndarray
    q: np.ndarray
    keep: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.keep = np.ones(len(self.p), dtype=bool)


def load_patches() -> list[Patch]:
    patches = []
    with (HERE / "windows.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            a = np.loadtxt(ground_truth_file(REPO_ROOT, row["split"], row["roi"], int(row["patch"])), ndmin=2)
            a[:, [1, 3]] *= -1
            patches.append(Patch(
                row["split"], row["roi"], int(row["patch"]),
                np.array([row["opt_col"], row["opt_row"]], dtype=float),
                np.array([row["sar_col"], row["sar_row"]], dtype=float),
                a[:, 0:2], a[:, 2:4],
            ))
    return patches


# ---------------------------------------------------------------------------
# 1. 最小二乘拟合残差


def fit_affine(p: np.ndarray, d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """p：光学点 (N, 2)；d：偏差 q − p (N, 2)。返回残差与杠杆值。"""
    x = np.column_stack([p, np.ones(len(p))])
    coef, *_ = np.linalg.lstsq(x, d, rcond=None)
    hat = np.einsum("ij,jk,ik->i", x, np.linalg.pinv(x.T @ x), x)
    return d - x @ coef, hat


def fit_all(patches: list[Patch]) -> list[tuple[np.ndarray, np.ndarray]]:
    return [fit_affine(pt.p[pt.keep], (pt.q - pt.p)[pt.keep]) for pt in patches]


def pooled(fits: list[tuple[np.ndarray, np.ndarray]]) -> tuple[np.ndarray, int]:
    """每轴的 σ̂² 与每轴的自由度。"""
    rss = sum((r**2).sum(axis=0) for r, _ in fits)
    dof = sum(len(r) - 3 for r, _ in fits)
    return rss / dof, dof


def remove_outliers(patches: list[Patch], fits: list) -> list[dict]:
    """每轮在全部 patch 里找学生化残差最大的一个分量，超过 3 就剔除该点、重拟合该 patch。"""
    removed = []
    while True:
        s2, _ = pooled(fits)
        worst, worst_z = None, OUTLIER_Z
        for i, (resid, hat) in enumerate(fits):
            z = np.abs(resid) / np.sqrt(s2 * (1 - hat)[:, None])
            j = np.unravel_index(np.argmax(z), z.shape)
            if z[j] > worst_z:
                worst, worst_z = (i, *j), z[j]
        if worst is None:
            return removed
        i, j, _ = worst
        pt = patches[i]
        row = np.flatnonzero(pt.keep)[j]
        resid, hat = fits[i]
        z = np.abs(resid[j]) / np.sqrt(s2 * (1 - hat[j]))
        removed.append({"roi": pt.roi, "patch": pt.index, "row": int(row), "z": z.tolist()})
        pt.keep[row] = False
        fits[i] = fit_affine(pt.p[pt.keep], (pt.q - pt.p)[pt.keep])


def chi2_ppf(prob: float, dof: int) -> float:
    z = Z975 if prob > 0.5 else -Z975
    return dof * (1 - 2 / (9 * dof) + z * math.sqrt(2 / (9 * dof))) ** 3


def sigma_ci(s2: float, dof: int) -> list[float]:
    return [math.sqrt(s2 * dof / chi2_ppf(0.975, dof)), math.sqrt(s2 * dof / chi2_ppf(0.025, dof))]


def excess_kurtosis(fits: list) -> list[float]:
    scaled = np.vstack([r / np.sqrt(1 - h)[:, None] for r, h in fits])
    dev = scaled - scaled.mean(axis=0)
    return ((dev**4).mean(axis=0) / (dev**2).mean(axis=0) ** 2 - 3).tolist()


def spearman(a: list[float], b: list[float]) -> tuple[float, float]:
    """秩相关与双侧 p 值（t = ρ√((n−2)/(1−ρ²))，自由度 n − 2）。"""
    ra, rb = _ranks(np.asarray(a)), _ranks(np.asarray(b))
    rho = float(np.corrcoef(ra, rb)[0, 1])
    dof = len(a) - 2
    t = abs(rho) * math.sqrt(dof / (1 - rho**2))
    return rho, 1 - _t_central(t, dof)


def _ranks(v: np.ndarray) -> np.ndarray:
    """并列取平均秩。"""
    order = np.argsort(v, kind="stable")
    ranks = np.empty(len(v))
    ranks[order] = np.arange(1, len(v) + 1)
    for value in np.unique(v):
        tied = v == value
        ranks[tied] = ranks[tied].mean()
    return ranks


def _t_central(t: float, dof: int) -> float:
    """P(|T| < t)，T 服从自由度为整数 dof 的 t 分布。"""
    theta = math.atan(t / math.sqrt(dof))
    c, s = math.cos(theta), math.sin(theta)
    if dof % 2:
        term, total = c, 0.0
        for k in range(1, (dof - 1) // 2 + 1):
            total += term
            term *= c * c * (2 * k) / (2 * k + 1)
        return 2 / math.pi * (theta + s * total) if dof > 1 else 2 * theta / math.pi
    term, total = 1.0, 0.0
    for k in range(1, dof // 2 + 1):
        total += term
        term *= c * c * (2 * k - 1) / (2 * k)
    return s * total


def least_squares(patches: list[Patch], metadata: dict) -> dict:
    points_per_patch = [len(pt.p) for pt in patches]
    fits = fit_all(patches)
    s2_before, dof_before = pooled(fits)
    kurt_before = excess_kurtosis(fits)
    removed = remove_outliers(patches, fits)
    s2, dof = pooled(fits)

    rois = []
    groups = defaultdict(list)
    for pt, fit in zip(patches, fits):
        groups[pt.roi].append(fit)
    for roi, members in sorted(groups.items()):
        s2_roi, _ = pooled(members)
        rois.append({"roi": roi, "incidence": float(metadata[roi]["入射角_deg"]),
                     "sigma_x": float(np.sqrt(s2_roi[0])), "sigma_y": float(np.sqrt(s2_roi[1]))})
    incidence = [r["incidence"] for r in rois]
    return {
        "patches": len(patches), "points": int(sum(points_per_patch)),
        "points_per_patch": [min(points_per_patch), max(points_per_patch)],
        "before": {"sigma": np.sqrt(s2_before).tolist(), "dof": dof_before, "kurtosis": kurt_before},
        "after": {"sigma": np.sqrt(s2).tolist(), "dof": dof, "kurtosis": excess_kurtosis(fits),
                  "ci_x": sigma_ci(s2[0], dof), "ci_y": sigma_ci(s2[1], dof)},
        "removed": len(removed), "removed_by_y": sum(r["z"][1] > OUTLIER_Z for r in removed),
        "rois": rois,
        "spearman_x": spearman(incidence, [r["sigma_x"] for r in rois]),
        "spearman_y": spearman(incidence, [r["sigma_y"] for r in rois]),
    }


# ---------------------------------------------------------------------------
# 2. 变异函数


def variogram(patches: list[Patch], globals_: dict[str, np.ndarray]) -> dict:
    """同一 ROI 内的全部点对（只用剔除粗差后的点），13 个 ROI 合并后分档。"""
    nb = len(LAG_EDGES) - 1
    acc = {k: np.zeros(nb) for k in ("n", "h", "gx", "gy", "n_same", "gx_same", "gy_same")}
    shortest = np.inf
    nearest = []
    by_roi = defaultdict(list)
    for pt in patches:
        by_roi[pt.roi].append(pt)
    for roi, members in sorted(by_roi.items()):
        P = np.vstack([pt.opt_window + pt.p[pt.keep] for pt in members])
        Q = np.vstack([pt.sar_window + pt.q[pt.keep] for pt in members])
        ids = np.concatenate([np.full(pt.keep.sum(), k) for k, pt in enumerate(members)])
        r = Q - apply_transform(P, globals_[roi])
        i, j = np.triu_indices(len(P), 1)
        h = np.hypot(*(P[i] - P[j]).T)
        shortest = min(shortest, float(h.min()))
        dist = np.full((len(P), len(P)), np.inf)
        dist[i, j] = dist[j, i] = h
        nearest.append(dist.min(axis=1))
        half_sq = 0.5 * (r[i] - r[j]) ** 2
        same = ids[i] == ids[j]
        b = np.digitize(h, LAG_EDGES) - 1
        ok = b < nb
        for mask, suffix in ((ok, ""), (ok & same, "_same")):
            acc["n" + suffix] += np.bincount(b[mask], minlength=nb)
            acc["gx" + suffix] += np.bincount(b[mask], weights=half_sq[mask, 0], minlength=nb)
            acc["gy" + suffix] += np.bincount(b[mask], weights=half_sq[mask, 1], minlength=nb)
        acc["h"] += np.bincount(b[ok], weights=h[ok], minlength=nb)

    n = acc["n"]
    n_same, n_cross = acc["n_same"], acc["n"] - acc["n_same"]
    good = n >= MIN_PAIRS
    with np.errstate(invalid="ignore", divide="ignore"):
        bins = {
            "h": acc["h"] / n, "n": n, "gx": acc["gx"] / n, "gy": acc["gy"] / n,
            "n_same": n_same, "gx_same": acc["gx_same"] / n_same, "gy_same": acc["gy_same"] / n_same,
            "n_cross": n_cross, "gx_cross": (acc["gx"] - acc["gx_same"]) / n_cross,
            "gy_cross": (acc["gy"] - acc["gy_same"]) / n_cross,
        }
    bins = {k: v[good] for k, v in bins.items()}
    fits = [{"power": power, "hmax": hmax, **nugget(bins, "gy", power, hmax)} for power, hmax in NUGGET_FITS]
    fits_x = [{"power": power, "hmax": hmax, **nugget(bins, "gx", power, hmax)} for power, hmax in NUGGET_FITS]
    return {"points": int(sum(pt.keep.sum() for pt in patches)), "shortest": shortest,
            "nearest_q": np.percentile(np.concatenate(nearest), [5, 50, 95]).tolist(),
            "bins": {k: v.tolist() for k, v in bins.items()}, "fits_y": fits, "fits_x": fits_x}


def nugget(bins: dict, key: str, power: int, hmax: float) -> dict:
    """γ(h) ≈ c₀ + b·hᵖ，按 1/(γ/√n)² 加权最小二乘，c₀ ≥ 0。"""
    m = bins["h"] <= hmax
    h, g, n = bins["h"][m] ** power, bins[key][m], bins["n"][m]
    w = n / g**2
    a = np.column_stack([np.ones(len(h)), h]) * np.sqrt(w)[:, None]
    c0, b = np.linalg.lstsq(a, g * np.sqrt(w), rcond=None)[0]
    if c0 < 0:
        c0, b = 0.0, float((w * h * g).sum() / (w * h * h).sum())
    return {"c0": float(c0), "b": float(b)}


# ---------------------------------------------------------------------------
# 3. 重复测量


def repeat(patches: list[Patch]) -> dict:
    """评测真值点（全部点，不剔粗差）与控制点在光学侧相距 r 以内的配对。"""
    gt: dict[str, list[np.ndarray]] = {}
    for pt in patches:
        gt.setdefault(pt.roi, []).append(np.hstack([pt.opt_window + pt.p, pt.sar_window + pt.q]))
    gt = {roi: np.vstack(v) for roi, v in gt.items()}
    ties = {roi: np.hstack(load_tie_points(REPO_ROOT, roi)) for roi in gt}

    def match(g: np.ndarray, t: np.ndarray) -> list[tuple[int, int, float]]:
        r = np.hypot(g[:, None, 0] - t[None, :, 0], g[:, None, 1] - t[None, :, 1])
        return [(i, j, float(r[i, j])) for i, j in zip(*np.nonzero(r < REPEAT_RADIUS))]

    pairs = []
    for roi in sorted(gt):
        for i, j, r in match(gt[roi], ties[roi]):
            g, t = gt[roi][i], ties[roi][j]
            delta = (g[2:] - g[:2]) - (t[2:] - t[:2])
            pairs.append({"roi": roi, "gt_index": int(i), "tie_index": int(j), "r": r,
                          "optical_offset": (g[:2] - t[:2]).tolist(), "delta": delta.tolist()})

    # 偶然重合：控制点整体随机平移（每轴 ±50–300 像素）后，同样半径内还有多少配对。
    rng = np.random.default_rng(0)
    chance = []
    for _ in range(SHUFFLES):
        count = 0
        for roi in gt:
            moved = ties[roi].copy()
            moved[:, :2] += rng.uniform(50, 300, 2) * rng.choice([-1, 1], 2)
            count += len(match(gt[roi], moved))
        chance.append(count)

    rows = []
    r = np.array([p["r"] for p in pairs])
    deltas = np.array([p["delta"] for p in pairs])
    for thr in REPEAT_THRESHOLDS:
        delta = deltas[r < thr]
        dev = delta - np.median(delta, axis=0)
        mad = 1.4826 * np.median(np.abs(dev), axis=0)
        keep = np.all(np.abs(dev) < 3 * mad, axis=1)
        s2 = delta[keep].var(axis=0, ddof=1)
        sigma = np.sqrt((s2 - QUANTISATION) / 2)
        rows.append({"r": thr, "pairs": len(delta), "removed": int((~keep).sum()), "sigma": sigma.tolist(),
                     "se": (sigma / np.sqrt(2 * (keep.sum() - 1))).tolist(),
                     "median": np.median(delta, axis=0).tolist()})
    return {"tie_points": sum(len(t) for t in ties.values()), "points": sum(len(g) for g in gt.values()),
            "chance_mean": float(np.mean(chance)), "chance_max": int(max(chance)), "rows": rows, "pairs": pairs}


# ---------------------------------------------------------------------------
# 报告


def report(ls: dict, vg: dict, rp: dict) -> str:
    b, a = ls["before"], ls["after"]
    bins = vg["bins"]
    nuggets = [f["c0"] for f in vg["fits_y"]]
    lines = [
        "# 标注误差：三种估计方法", "",
        "由 `estimate.py` 生成，勿手改。σ 为一对评测真值点合成的标注误差在一个坐标轴上的标准差，单位像素。", "",
        "## 1. 最小二乘拟合残差", "",
        f"{ls['patches']} 个 patch、{ls['points']} 个点，每个 patch {ls['points_per_patch'][0]}–{ls['points_per_patch'][1]} 个点。"
        f"剔除 {ls['removed']} 个点，其中 {ls['removed_by_y']} 个由 y 残差超限触发。", "",
        "| | 每轴自由度 | σ̂x | σ̂y | 超额峰度 x | 超额峰度 y |", "|---|---|---|---|---|---|",
        f"| 剔除前 | {b['dof']} | {b['sigma'][0]:.2f} | {b['sigma'][1]:.2f} | {b['kurtosis'][0]:.2f} | {b['kurtosis'][1]:.2f} |",
        f"| 剔除后 | {a['dof']} | {a['sigma'][0]:.2f}（{a['ci_x'][0]:.2f}–{a['ci_x'][1]:.2f}） "
        f"| {a['sigma'][1]:.2f}（{a['ci_y'][0]:.2f}–{a['ci_y'][1]:.2f}） | {a['kurtosis'][0]:.2f} | {a['kurtosis'][1]:.2f} |",
        "", "括号内为 95% 置信区间。", "",
        "### 逐 ROI（剔除后）", "", "| ROI | 入射角 | σ̂x | σ̂y |", "|---|---|---|---|",
    ]
    lines += [f"| {r['roi']} | {r['incidence']:.1f} | {r['sigma_x']:.2f} | {r['sigma_y']:.2f} |" for r in ls["rois"]]
    sx, sy = ls["spearman_x"], ls["spearman_y"]
    lines += [
        "", f"σ̂x 范围 {min(r['sigma_x'] for r in ls['rois']):.2f}–{max(r['sigma_x'] for r in ls['rois']):.2f}，"
        f"σ̂y 范围 {min(r['sigma_y'] for r in ls['rois']):.2f}–{max(r['sigma_y'] for r in ls['rois']):.2f}。"
        f"与入射角的 Spearman 秩相关：σ̂x {sx[0]:.2f}（p = {sx[1]:.2f}），σ̂y {sy[0]:.2f}（p = {sy[1]:.2f}）。", "",
        "## 2. 变异函数", "",
        f"使用剔除粗差后的 {vg['points']} 个点。同一 ROI 内最近的点对相距 {vg['shortest']:.1f} 像素；"
        f"每个点到最近邻点的距离，5 / 50 / 95 分位为 {' / '.join(f'{v:.0f}' for v in vg['nearest_q'])} 像素。"
        f"h < {LAG_EDGES[1]:g} 像素的点对不足 {MIN_PAIRS} 对，不成一档。", "",
        "| h 均值 | 点对 | γx | γy | 同 patch 点对 | 同 patch γx | 同 patch γy | 跨 patch 点对 | 跨 patch γx | 跨 patch γy |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for k in range(len(bins["h"])):
        cells = [f"{bins['h'][k]:.0f}", f"{bins['n'][k]:.0f}", f"{bins['gx'][k]:.2f}", f"{bins['gy'][k]:.2f}"]
        for part in ("same", "cross"):
            n = bins[f"n_{part}"][k]
            ok = n >= MIN_PAIRS
            cells += [f"{n:.0f}", f"{bins[f'gx_{part}'][k]:.2f}" if ok else "—", f"{bins[f'gy_{part}'][k]:.2f}" if ok else "—"]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", f"同 patch、跨 patch 两列点对少于 {MIN_PAIRS} 时不报。", "",
              "| 外推 | h ≤ | y 块金值（像素²） | 开方 | x 块金值（像素²） |", "|---|---|---|---|---|"]
    for fy, fx in zip(vg["fits_y"], vg["fits_x"]):
        lines.append(f"| {'线性' if fy['power'] == 1 else '二次'} | {fy['hmax']} | {fy['c0']:.2f} | {math.sqrt(fy['c0']):.2f} | {fx['c0']:.2f} |")
    lines += ["", f"y：块金值 {min(nuggets):.2f}–{max(nuggets):.2f} 像素²，σ̂y = {math.sqrt(min(nuggets)):.2f}–{math.sqrt(max(nuggets)):.2f} 像素。", "",
              "## 3. 重复测量", "",
              f"{rp['tie_points']} 个控制点、{rp['points']} 个评测真值点，光学侧相距 {REPEAT_RADIUS:g} 像素以内的配对 {len(rp['pairs'])} 对。"
              f"控制点整体随机平移后，同样半径内平均 {rp['chance_mean']:.1f} 对（{SHUFFLES} 次，最多 {rp['chance_max']} 对）。", "",
              "| r | 配对 | 剔除 | σ̂x | σ̂y | δ 中位数 x | δ 中位数 y |", "|---|---|---|---|---|---|---|"]
    for row in rp["rows"]:
        (sx_, sy_), (ex, ey), (mx, my) = row["sigma"], row["se"], row["median"]
        lines.append(f"| < {row['r']:g} | {row['pairs']} | {row['removed']} | {sx_:.2f} ± {ex:.2f} | {sy_:.2f} ± {ey:.2f} | {mx:.2f} | {my:.2f} |")
    lines += ["", "± 为标准误 σ̂ / √(2(n − 1))。", ""]
    return "\n".join(lines)


def main() -> None:
    patches = load_patches()
    metadata = load_metadata(REPO_ROOT)
    rois = sorted({pt.roi for pt in patches})
    globals_ = {roi: estimate_affine(*load_tie_points(REPO_ROOT, roi)) for roi in rois}
    rp = repeat(patches)
    ls = least_squares(patches, metadata)
    vg = variogram(patches, globals_)
    text = report(ls, vg, rp)
    (HERE / "tables.md").write_text(text, encoding="utf-8")
    (HERE / "results.json").write_text(
        json.dumps({"least_squares": ls, "variogram": vg, "repeat": rp}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print("已写出", HERE / "tables.md", HERE / "results.json")


if __name__ == "__main__":
    main()
