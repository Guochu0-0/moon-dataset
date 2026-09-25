"""评测真值点在 patch 内的偏移与拟合残差（issue #40，地图 #34）。

    python research/ground-truth-residuals/analyze.py

输入只有仓库里的东西：`data/ground-truth/` 的评测真值点、`data/tie-points/` 的控制点、
元数据表，以及 `collect.py` 写出的 `windows.csv`（窗口位置）。不接数据盘，几十秒跑完。
产出写到本目录：`tables.md`、`summary.json`、`patches.csv`、`outliers.csv` 与四张图。

记号：一对点里光学点 `p`、SAR 点 `q`，都是 patch 内像素 (列, 行)，y 已翻回向下为正。
错位 `d = q − p`。x 近似 SAR 的距离向（Mini-RF 视方位角约 90° 或 270°，朝东或朝西看），
y 近似方位向。

四部分，对应 issue 的四问：

1. **仿射拟合残差**。每个 patch 用仿射把 `p` 拟合到 `q`（每分量 3 个参数），残差按
   `σ̂² = ΣRSS / Σ(N − 3)` 分量各自跨 patch 汇总（两分量合起来即 `ΣRSS / Σ(2N − 6)`）。
   粗差按 3 倍规则迭代剔除：学生化残差 `e / (σ̂ √(1 − h))` 任一分量超过 3 就剔掉最大的
   那一个点、重拟合该 patch、重算 σ̂，直到没有。
2. **patch 内「有多斜」**。拟合出的线性部分 `A`，错位在 patch 内的变化是 `(A − I)·Δp`；
   取两条对角线 `(512, ±512)` 上变化量的较大者作「跨度」。零假设（真实错位在 patch 内
   是平移）下的跨度分布，用同样的点位加上 σ̂ 的高斯噪声模拟得到。
3. **空间统计**。点放回重叠区影像坐标（`P = 光学窗口 + p`，`Q = SAR 窗口 + q`），求相对
   该 ROI 控制点全局仿射 `G` 的残差 `r = Q − G(P)`，按分量算经验变异函数，拟合带 nugget
   的模型外推到 0。
4. **逐 patch 偏移**。patch 中心 (256, 256) 处的拟合错位作平移分量，另给点的离散程度。
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import optimize, stats
from scipy.spatial.distance import pdist

from moondata.geometry import apply_transform, estimate_affine
from moondata.sources import load_metadata, load_tie_points

REPO_ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
GROUND_TRUTH = REPO_ROOT / "data" / "ground-truth"

SIZE = 512
CENTRE = SIZE / 2
OUTLIER_Z = 3.0
NULL_REPS = 200
SEED = 20260925
DIAGONALS = np.array([[SIZE, SIZE], [SIZE, -SIZE]], dtype=float)
LAG_EDGES = np.array(
    [0, 15, 30, 45, 60, 80, 100, 130, 160, 200, 250, 320, 400, 500, 650, 800,
     1000, 1300, 1600, 2000, 2600, 3300, 4200, 5500], dtype=float,
)
MIN_PAIRS = 30
POSITION_EDGES = np.array([0, 64, 128, 192, 256, 320, 400])
"""点到 patch 中心的距离分组（像素）。角点离中心约 362。"""

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


# ---------------------------------------------------------------- 读入


@dataclass
class Patch:
    split: str
    roi: str
    index: int
    opt_window: np.ndarray
    sar_window: np.ndarray
    p: np.ndarray
    q: np.ndarray
    removed: list[int] = field(default_factory=list)
    """被当作粗差剔掉的点在原文件里的行号（0 起）。"""
    keep: np.ndarray = field(default=None)

    def __post_init__(self) -> None:
        self.keep = np.ones(len(self.p), dtype=bool)

    @property
    def pk(self) -> np.ndarray:
        return self.p[self.keep]

    @property
    def qk(self) -> np.ndarray:
        return self.q[self.keep]


def load_patches() -> list[Patch]:
    patches = []
    with (HERE / "windows.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["labelled"] != "1":
                continue
            path = GROUND_TRUTH / row["split"] / row["roi"] / f"patch_{row['patch']}.txt"
            a = np.loadtxt(path, ndmin=2)
            flip = np.array([1.0, -1.0])
            patches.append(Patch(
                row["split"], row["roi"], int(row["patch"]),
                np.array([row["opt_col"], row["opt_row"]], dtype=float),
                np.array([row["sar_col"], row["sar_row"]], dtype=float),
                a[:, 0:2] * flip, a[:, 2:4] * flip,
            ))
    return patches


# ---------------------------------------------------------------- 1. 仿射拟合与粗差


@dataclass
class Fit:
    coef: np.ndarray
    """(3, 2)：行是 [x − 256, y − 256, 1] 的系数，列是 q 的 x、y。"""
    resid: np.ndarray
    hat: np.ndarray

    @property
    def linear(self) -> np.ndarray:
        """2×2 的 A，`q ≈ A (p − c) + t`。"""
        return self.coef[:2].T

    @property
    def centre_offset(self) -> np.ndarray:
        """patch 中心处的错位 d(c) = t − c。"""
        return self.coef[2] - CENTRE


def design(p: np.ndarray) -> np.ndarray:
    return np.column_stack([p - CENTRE, np.ones(len(p))])


def fit_affine(p: np.ndarray, q: np.ndarray) -> Fit:
    x = design(p)
    coef, *_ = np.linalg.lstsq(x, q, rcond=None)
    hat = np.einsum("ij,jk,ik->i", x, np.linalg.pinv(x.T @ x), x)
    return Fit(coef, q - x @ coef, hat)


def pooled_sigma2(fits: dict[int, Fit], patches: list[Patch]) -> tuple[np.ndarray, int]:
    """分量各自的 σ̂² 与每分量的总自由度。"""
    rss, dof = np.zeros(2), 0
    for i, fit in fits.items():
        n = patches[i].keep.sum()
        if n > 3:
            rss += (fit.resid**2).sum(axis=0)
            dof += n - 3
    return rss / dof, dof


def remove_outliers(patches: list[Patch]) -> tuple[dict[int, Fit], list[dict]]:
    fits = {i: fit_affine(pt.pk, pt.qk) for i, pt in enumerate(patches)}
    removed = []
    while True:
        s2, _ = pooled_sigma2(fits, patches)
        worst, worst_z = None, OUTLIER_Z
        for i, fit in fits.items():
            if patches[i].keep.sum() <= 3:
                continue
            z = np.abs(fit.resid) / np.sqrt(s2 * np.clip(1 - fit.hat, 1e-9, None)[:, None])
            j = np.unravel_index(np.argmax(z), z.shape)
            if z[j] > worst_z:
                worst, worst_z = (i, j[0], z[j[0]]), z[j]
        if worst is None:
            return fits, removed
        i, j, z = worst
        pt = patches[i]
        row = np.flatnonzero(pt.keep)[j]
        fit = fits[i]
        removed.append({
            "split": pt.split, "roi": pt.roi, "patch": pt.index, "row": int(row),
            "opt_x": pt.p[row, 0], "opt_y": pt.p[row, 1], "sar_x": pt.q[row, 0], "sar_y": pt.q[row, 1],
            "resid_x": fit.resid[j, 0], "resid_y": fit.resid[j, 1], "z_x": z[0], "z_y": z[1],
        })
        pt.keep[row] = False
        pt.removed.append(int(row))
        fits[i] = fit_affine(pt.pk, pt.qk)


def residual_summary(fits: dict[int, Fit], patches: list[Patch]) -> dict:
    s2, dof = pooled_sigma2(fits, patches)
    used = [i for i in fits if patches[i].keep.sum() > 3]
    scaled = np.vstack([fits[i].resid / np.sqrt(1 - fits[i].hat)[:, None] for i in used])
    resid = np.vstack([fits[i].resid for i in used])
    cov = sum(fits[i].resid[:, 0] @ fits[i].resid[:, 1] for i in used) / dof
    mad = 1.4826 * np.median(np.abs(scaled - np.median(scaled, axis=0)), axis=0)
    ci = lambda v: [float(np.sqrt(v * dof / stats.chi2.ppf(0.975, dof))),
                    float(np.sqrt(v * dof / stats.chi2.ppf(0.025, dof)))]
    return {
        "patches": len(used),
        "points": int(sum(patches[i].keep.sum() for i in used)),
        "dof_per_component": int(dof),
        "sigma_x": float(np.sqrt(s2[0])), "sigma_y": float(np.sqrt(s2[1])),
        "sigma_x_ci95": ci(s2[0]), "sigma_y_ci95": ci(s2[1]),
        "sigma_per_axis": float(np.sqrt(s2.mean())),
        "sigma_radial": float(np.sqrt(s2.sum())),
        "robust_sigma_x": float(mad[0]), "robust_sigma_y": float(mad[1]),
        "corr_xy": float(cov / np.sqrt(s2[0] * s2[1])),
        "kurtosis_excess_x": float(stats.kurtosis(scaled[:, 0])),
        "kurtosis_excess_y": float(stats.kurtosis(scaled[:, 1])),
        "_scaled": scaled, "_resid": resid,
    }


def by_position(fits: dict[int, Fit], patches: list[Patch]) -> list[dict]:
    """e²/(1 − h) 是该点残差方差的无偏贡献，按点到 patch 中心的距离分组平均。"""
    rows = []
    for i, fit in fits.items():
        if patches[i].keep.sum() <= 3:
            continue
        r = np.linalg.norm(patches[i].pk - CENTRE, axis=1)
        v = fit.resid**2 / (1 - fit.hat)[:, None]
        rows += [(ri, *vi) for ri, vi in zip(r, v)]
    rows = np.array(rows)
    out = []
    for lo, hi in zip(POSITION_EDGES[:-1], POSITION_EDGES[1:]):
        m = (rows[:, 0] >= lo) & (rows[:, 0] < hi)
        if m.sum() < 20:
            continue
        out.append({"from": int(lo), "to": int(hi), "points": int(m.sum()),
                    "sigma_x": float(np.sqrt(rows[m, 1].mean())), "sigma_y": float(np.sqrt(rows[m, 2].mean()))})
    return out


def by_roi(fits: dict[int, Fit], patches: list[Patch], metadata: dict) -> list[dict]:
    groups = defaultdict(list)
    for i in fits:
        groups[patches[i].roi].append(i)
    out = []
    for roi, members in sorted(groups.items()):
        sub = {i: fits[i] for i in members}
        s2, dof = pooled_sigma2(sub, patches)
        meta = metadata[roi]
        out.append({
            "roi": roi, "split": patches[members[0]].split, "patches": len(members), "dof": int(dof),
            "sigma_x": float(np.sqrt(s2[0])), "sigma_y": float(np.sqrt(s2[1])),
            "sigma_x_ci95": [float(np.sqrt(s2[0] * dof / stats.chi2.ppf(q, dof))) for q in (0.975, 0.025)],
            "sigma_y_ci95": [float(np.sqrt(s2[1] * dof / stats.chi2.ppf(q, dof))) for q in (0.975, 0.025)],
            "incidence_deg": float(meta["入射角_deg"]), "look": meta["视向"].strip(),
        })
    return out


# ---------------------------------------------------------------- 2. 有多斜


def span(delta: np.ndarray) -> tuple[float, float, float]:
    """(A − I) 或 (A − L) 沿两条对角线的变化量：(合, x 分量, y 分量)，各取两条对角线的较大者。"""
    change = DIAGONALS @ delta.T  # (2 条对角线, 2 分量)
    return (float(np.linalg.norm(change, axis=1).max()),
            float(np.abs(change[:, 0]).max()), float(np.abs(change[:, 1]).max()))


def tilt(fits: dict[int, Fit], patches: list[Patch], globals_: dict[str, np.ndarray], s2: np.ndarray) -> dict[int, dict]:
    rng = np.random.default_rng(SEED)
    sd = np.sqrt(s2)
    out = {}
    for i, fit in fits.items():
        pt = patches[i]
        p, q = pt.pk, pt.qk
        n = len(p)
        a = fit.linear
        total, total_x, total_y = span(a - np.eye(2))
        local = span(a - globals_[pt.roi])[0]
        # 零假设：patch 内真实错位是平移（或全局线性部分 + 平移），只有高斯噪声。
        x = design(p)
        solve = np.linalg.pinv(x)
        noise = rng.normal(size=(NULL_REPS, n, 2)) * sd
        coefs = np.einsum("kn,rnc->rkc", solve, noise)
        null = np.array([span(c[:2].T)[0] for c in coefs])
        # 嵌套模型的 χ² 检验：平移（A = I）、全局线性部分 + 平移（A = L），各比仿射多 4 个约束。
        tests = {}
        for name, lin in (("translation", np.eye(2)), ("global_slope", globals_[pt.roi])):
            fixed = q - (p - CENTRE) @ lin.T
            rss0 = ((fixed - fixed.mean(axis=0)) ** 2).sum(axis=0)
            stat = float(((rss0 - (fit.resid**2).sum(axis=0)) / s2).sum())
            tests[name] = float(stats.chi2.sf(stat, 4)) if n > 3 else float("nan")
        out[i] = {"span": total, "span_x": total_x, "span_y": total_y, "span_local": local,
                  "null_p95": float(np.percentile(null, 95)), "null_median": float(np.median(null)),
                  "p_translation": tests["translation"], "p_global_slope": tests["global_slope"]}
    return out


# ---------------------------------------------------------------- 3. 变异函数


def exp_model(h, c0, c, a):
    return c0 + c * (1 - np.exp(-h / a))


def sph_model(h, c0, c, a):
    s = np.clip(h / a, 0, 1)
    return c0 + c * (1.5 * s - 0.5 * s**3)


def gau_model(h, c0, c, a):
    return c0 + c * (1 - np.exp(-((h / a) ** 2)))


def lin_model(h, c0, b):
    return c0 + b * h


def quad_model(h, c0, b):
    return c0 + b * h**2


FULL_MODELS = {"指数": exp_model, "球状": sph_model, "高斯": gau_model}
SHORT_MODELS = {"线性": lin_model, "二次": quad_model}
FULL_HMAX = (250, 500, 1000, 2000)
SHORT_HMAX = (60, 100, 150)


def roi_pairs(members: list[Patch], matrix: np.ndarray) -> dict[str, np.ndarray]:
    P = np.vstack([pt.opt_window + pt.pk for pt in members])
    Q = np.vstack([pt.sar_window + pt.qk for pt in members])
    ids = np.concatenate([np.full(pt.keep.sum(), k) for k, pt in enumerate(members)])
    r = Q - apply_transform(P, matrix)
    return {
        "h": pdist(P),
        "dx": pdist(r[:, [0]], "cityblock"),
        "dy": pdist(r[:, [1]], "cityblock"),
        "same": pdist(ids[:, None].astype(float), "cityblock") == 0,
    }


def binned(pairs: list[dict[str, np.ndarray]], mask_key: str | None = None, value: bool = True) -> dict:
    """按 LAG_EDGES 分组的 Σ(½Δ²)、Σ|Δ|^½ 与计数，跨 ROI 累加（点对只在 ROI 内配）。"""
    nb = len(LAG_EDGES) - 1
    acc = {k: np.zeros(nb) for k in ("n", "h", "sx", "sy", "rx", "ry")}
    for pr in pairs:
        m = np.ones(len(pr["h"]), dtype=bool) if mask_key is None else (pr[mask_key] == value)
        b = np.digitize(pr["h"][m], LAG_EDGES) - 1
        ok = (b >= 0) & (b < nb)
        b = b[ok]
        for key, arr in (("h", pr["h"][m][ok]), ("sx", 0.5 * pr["dx"][m][ok] ** 2), ("sy", 0.5 * pr["dy"][m][ok] ** 2),
                         ("rx", np.sqrt(pr["dx"][m][ok])), ("ry", np.sqrt(pr["dy"][m][ok]))):
            acc[key] += np.bincount(b, weights=arr, minlength=nb)
        acc["n"] += np.bincount(b, minlength=nb)
    n = acc["n"]
    good = n >= MIN_PAIRS
    with np.errstate(invalid="ignore", divide="ignore"):
        ch = lambda s: 0.5 * (s / n) ** 4 / (0.457 + 0.494 / n)
        return {"n": n[good], "h": (acc["h"] / n)[good],
                "gx": (acc["sx"] / n)[good], "gy": (acc["sy"] / n)[good],
                "chx": ch(acc["rx"])[good], "chy": ch(acc["ry"])[good]}


def fit_nugget(h, g, n, model, hmax) -> float:
    m = h <= hmax
    if m.sum() < 3:
        return float("nan")
    hh, gg, nn = h[m], g[m], n[m]
    sigma = gg / np.sqrt(nn)
    try:
        if model in SHORT_MODELS.values():
            p, _ = optimize.curve_fit(model, hh, gg, p0=[gg[0], 0.0], sigma=sigma,
                                      bounds=([0, -np.inf], [np.inf, np.inf]), maxfev=20000)
        else:
            p, _ = optimize.curve_fit(model, hh, gg, p0=[gg[0] * 0.5, gg[-1], hmax / 3], sigma=sigma,
                                      bounds=([0, 0, 1], [np.inf, np.inf, 1e6]), maxfev=20000)
    except RuntimeError:
        return float("nan")
    return float(p[0])


def nugget_table(v: dict, key: str) -> dict[str, dict[int, float]]:
    table = {}
    for name, model in FULL_MODELS.items():
        table[name] = {hm: fit_nugget(v["h"], v[key], v["n"], model, hm) for hm in FULL_HMAX}
    for name, model in SHORT_MODELS.items():
        table[name] = {hm: fit_nugget(v["h"], v[key], v["n"], model, hm) for hm in SHORT_HMAX}
    return table


# ---------------------------------------------------------------- 报告


def q(a, ps=(5, 25, 50, 75, 95)):
    return [float(x) for x in np.percentile(a, ps)]


def main() -> int:
    patches = load_patches()
    metadata = load_metadata(REPO_ROOT)
    globals_affine = {roi: estimate_affine(*load_tie_points(REPO_ROOT, roi)) for roi in {p.roi for p in patches}}
    globals_linear = {roi: m[:2, :2] for roi, m in globals_affine.items()}
    counts = np.bincount([len(p.p) for p in patches])

    raw_fits = {i: fit_affine(pt.p, pt.q) for i, pt in enumerate(patches)}
    before = residual_summary(raw_fits, patches)
    fits, removed = remove_outliers(patches)
    after = residual_summary(fits, patches)
    s2 = np.array([after["sigma_x"], after["sigma_y"]]) ** 2
    expected_false = 2 * stats.norm.sf(OUTLIER_Z) * 2 * after["points"]
    position = by_position(fits, patches)
    rois = by_roi(fits, patches, metadata)
    rho_inc_x = stats.spearmanr([r["incidence_deg"] for r in rois], [r["sigma_x"] for r in rois])
    rho_inc_y = stats.spearmanr([r["incidence_deg"] for r in rois], [r["sigma_y"] for r in rois])
    look = {lk: [r for r in rois if r["look"] == lk] for lk in ("LEFT", "RIGHT")}

    tilts = tilt(fits, patches, globals_linear, s2)
    T = {k: np.array([tilts[i][k] for i in fits]) for k in next(iter(tilts.values()))}
    global_span = {roi: span(l - np.eye(2)) for roi, l in globals_linear.items()}

    by_roi_members = defaultdict(list)
    for pt in patches:
        by_roi_members[pt.roi].append(pt)
    pairs = [roi_pairs(members, globals_affine[roi]) for roi, members in sorted(by_roi_members.items())]
    vg = binned(pairs)
    vg_same = binned(pairs, "same", True)
    vg_cross = binned(pairs, "same", False)
    nug_x, nug_y = nugget_table(vg, "gx"), nugget_table(vg, "gy")
    nug_chy = nugget_table({**vg, "gy": vg["chy"]}, "gy")
    roi_vg = {}
    for (roi, _), pr in zip(sorted(by_roi_members.items()), pairs):
        v = binned([pr])
        roi_vg[roi] = {
            "nugget_y_exp1000": fit_nugget(v["h"], v["gy"], v["n"], exp_model, 1000),
            "nugget_y_lin100": fit_nugget(v["h"], v["gy"], v["n"], lin_model, 100),
            "nugget_x_exp1000": fit_nugget(v["h"], v["gx"], v["n"], exp_model, 1000),
            "nugget_x_lin100": fit_nugget(v["h"], v["gx"], v["n"], lin_model, 100),
            "gamma_y_first": float(v["gy"][0]), "gamma_x_first": float(v["gx"][0]), "h_first": float(v["h"][0]),
        }

    # 逐 patch 表
    table = []
    for i, fit in fits.items():
        pt = patches[i]
        d = pt.qk - pt.pk
        t = fit.centre_offset
        rss = (fit.resid**2).sum()
        n = int(pt.keep.sum())
        table.append({
            "split": pt.split, "roi": pt.roi, "patch": pt.index, "points": n, "removed": len(pt.removed),
            "opt_col": int(pt.opt_window[0]), "opt_row": int(pt.opt_window[1]),
            "dx_centre": t[0], "dy_centre": t[1], "dx_mean": d[:, 0].mean(), "dy_mean": d[:, 1].mean(),
            "dx_std": d[:, 0].std(ddof=1), "dy_std": d[:, 1].std(ddof=1),
            "rms_affine": float(np.sqrt(rss / (2 * n - 6))) if n > 3 else float("nan"),
            **{k: tilts[i][k] for k in ("span", "span_x", "span_y", "span_local", "p_translation", "p_global_slope")},
        })
    write_csv(HERE / "patches.csv", table)
    write_csv(HERE / "outliers.csv", removed)
    offsets = np.array([[r["dx_centre"], r["dy_centre"]] for r in table])

    summary = {
        "points_per_patch": {str(k): int(v) for k, v in enumerate(counts) if v},
        "residual_before": {k: v for k, v in before.items() if not k.startswith("_")},
        "residual_after": {k: v for k, v in after.items() if not k.startswith("_")},
        "outliers": {"removed": len(removed), "expected_if_gaussian": expected_false},
        "position": position, "rois": rois,
        "spearman_incidence": {"x": [rho_inc_x.statistic, rho_inc_x.pvalue], "y": [rho_inc_y.statistic, rho_inc_y.pvalue]},
        "tilt": {
            "span_q": q(T["span"]), "span_x_q": q(T["span_x"]), "span_y_q": q(T["span_y"]),
            "span_local_q": q(T["span_local"]), "null_q": q(T["null_median"]),
            "frac_span_gt": {str(t): float((T["span"] > t).mean()) for t in (1, 2, 5, 10, 20)},
            "frac_local_gt": {str(t): float((T["span_local"] > t).mean()) for t in (1, 2, 5, 10, 20)},
            "frac_local_above_null_p95": float((T["span_local"] > T["null_p95"]).mean()),
            "frac_span_above_null_p95": float((T["span"] > T["null_p95"]).mean()),
            "frac_p_translation_lt": {str(a): float((T["p_translation"] < a).mean()) for a in (0.05, 0.01)},
            "frac_p_global_slope_lt": {str(a): float((T["p_global_slope"] < a).mean()) for a in (0.05, 0.01)},
            "global_span": {roi: list(v) for roi, v in sorted(global_span.items())},
        },
        "variogram": {
            "pooled": {k: np.asarray(v).tolist() for k, v in vg.items()},
            "within_patch": {k: np.asarray(v).tolist() for k, v in vg_same.items()},
            "cross_patch": {k: np.asarray(v).tolist() for k, v in vg_cross.items()},
            "nugget_x": nug_x, "nugget_y": nug_y, "nugget_y_cressie_hawkins": nug_chy, "per_roi": roi_vg,
        },
        "offsets": {
            "dx_centre_q": q(offsets[:, 0]), "dy_centre_q": q(offsets[:, 1]),
            "abs_dx_centre_q": q(np.abs(offsets[:, 0])), "abs_dy_centre_q": q(np.abs(offsets[:, 1])),
            "per_roi": {roi: {"dx": q([r["dx_centre"] for r in table if r["roi"] == roi]),
                              "dy": q([r["dy_centre"] for r in table if r["roi"] == roi])}
                        for roi in sorted(by_roi_members)},
            "per_split": {s: {"abs_dx": q([abs(r["dx_centre"]) for r in table if r["split"] == s]),
                              "abs_dy": q([abs(r["dy_centre"]) for r in table if r["split"] == s])}
                          for s in ("Val", "Test")},
        },
    }
    (HERE / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")

    plot_residuals(after, position, rois)
    plot_tilt(T, global_span)
    plot_variogram(vg, vg_same, vg_cross, nug_x, nug_y)
    plot_offsets(table, by_roi_members)
    write_tables(summary, rois, removed, patches)
    print(f"σ̂x {after['sigma_x']:.2f}、σ̂y {after['sigma_y']:.2f} 像素，剔除 {len(removed)} 点；"
          f"y nugget {min(min(r.values()) for r in nug_y.values()):.2f}–{max(max(r.values()) for r in nug_y.values()):.2f} 像素²。"
          f"产出见 {HERE}")
    return 0


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (f"{v:.4f}" if isinstance(v, (float, np.floating)) else v) for k, v in row.items()})


# ---------------------------------------------------------------- 图


def plot_residuals(after: dict, position: list[dict], rois: list[dict]) -> None:
    fig, ax = plt.subplots(2, 2, figsize=(12, 9))
    scaled = after["_scaled"]
    bins = np.linspace(-8, 8, 81)
    for k, name in enumerate(("x（距离向）", "y（方位向）")):
        ax[0, 0].hist(scaled[:, k], bins=bins, histtype="step", density=True, label=f"{name}，σ={np.sqrt((scaled[:, k]**2).mean()):.2f}")
    for k, s in enumerate((after["sigma_x"], after["sigma_y"])):
        xs = np.linspace(-8, 8, 400)
        ax[0, 0].plot(xs, stats.norm.pdf(xs, 0, s), ls=":", color=f"C{k}")
    ax[0, 0].set_yscale("log"); ax[0, 0].set_ylim(1e-4, 1)
    ax[0, 0].set_xlabel("仿射残差 / √(1−h)（像素）"); ax[0, 0].set_title("残差分布（点线：同 σ 的高斯）"); ax[0, 0].legend()

    mids = [(r["from"] + r["to"]) / 2 for r in position]
    ax[0, 1].plot(mids, [r["sigma_x"] for r in position], "o-", label="x")
    ax[0, 1].plot(mids, [r["sigma_y"] for r in position], "s-", label="y")
    ax[0, 1].set_xlabel("点到 patch 中心的距离（像素）"); ax[0, 1].set_ylabel("σ（像素）")
    ax[0, 1].set_ylim(0, None); ax[0, 1].set_title("残差与点在 patch 内的位置"); ax[0, 1].legend()

    xs = np.arange(len(rois))
    for k, (key, mk) in enumerate((("sigma_x", "o"), ("sigma_y", "s"))):
        vals = np.array([r[key] for r in rois])
        ci = np.array([r[key + "_ci95"] for r in rois])
        ax[1, 0].errorbar(xs + (k - 0.5) * 0.2, vals, yerr=[vals - ci[:, 0], ci[:, 1] - vals], fmt=mk, label=key[-1])
    ax[1, 0].set_xticks(xs, [f"{r['roi'][4:]}\n{r['split']}" for r in rois], fontsize=8)
    ax[1, 0].set_ylabel("σ（像素，95% 区间）"); ax[1, 0].set_title("逐 ROI 的仿射残差 σ"); ax[1, 0].legend()

    for r in rois:
        c = "C3" if r["look"] == "LEFT" else "C2"
        ax[1, 1].plot(r["incidence_deg"], r["sigma_x"], "o", color=c)
        ax[1, 1].plot(r["incidence_deg"], r["sigma_y"], "s", color=c, mfc="none")
        ax[1, 1].annotate(r["roi"][4:], (r["incidence_deg"], r["sigma_x"]), fontsize=7)
    ax[1, 1].set_xlabel("入射角（度）"); ax[1, 1].set_ylabel("σ（像素）")
    ax[1, 1].set_title("σ 与入射角（实心 x、空心 y；红 LEFT、绿 RIGHT）")
    fig.tight_layout(); fig.savefig(HERE / "residuals.png", dpi=110); plt.close(fig)


def plot_tilt(T: dict, global_span: dict) -> None:
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
    for key, label in (("span", "实测（A − I）"), ("span_local", "扣掉全局线性部分（A − L）"), ("null_median", "零假设：纯平移 + 噪声（逐 patch 中位）")):
        v = np.sort(T[key])
        ax[0].plot(v, np.arange(1, len(v) + 1) / len(v), label=label)
    ax[0].set_xscale("log"); ax[0].set_xlabel("错位跨 patch 的变化（像素，对角线）"); ax[0].set_ylabel("累计比例")
    ax[0].set_title("patch 内「有多斜」"); ax[0].legend(fontsize=8); ax[0].grid(alpha=0.3)
    for key, label in (("span_x", "x 分量"), ("span_y", "y 分量")):
        v = np.sort(T[key])
        ax[1].plot(v, np.arange(1, len(v) + 1) / len(v), label=label)
    gx = [v[1] for v in global_span.values()]
    ax[1].plot(np.sort(gx), np.linspace(0, 1, len(gx)), "k.", label="全局仿射的 x 分量（13 个 ROI）")
    ax[1].set_xscale("log"); ax[1].set_xlabel("变化（像素）"); ax[1].set_title("按分量")
    ax[1].legend(fontsize=8); ax[1].grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(HERE / "tilt.png", dpi=110); plt.close(fig)


def plot_variogram(vg: dict, same: dict, cross: dict, nug_x: dict, nug_y: dict) -> None:
    fig, ax = plt.subplots(1, 2, figsize=(13, 5))
    hs = np.linspace(0, 2000, 400)
    for k, (key, nug, title) in enumerate((("gx", nug_x, "x（距离向）"), ("gy", nug_y, "y（方位向）"))):
        a = ax[k]
        a.plot(vg["h"], vg[key], "ko", label="全部点对")
        a.plot(same["h"], same[key], "^", color="C1", label="同一 patch 内")
        a.plot(cross["h"], cross[key], "v", color="C2", label="跨 patch")
        for name, model in FULL_MODELS.items():
            m = vg["h"] <= 1000
            try:
                p0 = [vg[key][0] * 0.5, vg[key][m][-1], 300]
                p, _ = optimize.curve_fit(model, vg["h"][m], vg[key][m], p0=p0, sigma=vg[key][m] / np.sqrt(vg["n"][m]),
                                          bounds=([0, 0, 1], [np.inf, np.inf, 1e6]), maxfev=20000)
                a.plot(hs, model(hs, *p), lw=1, label=f"{name}（h≤1000），nugget {p[0]:.2f}")
            except RuntimeError:
                pass
        a.set_xscale("symlog", linthresh=50); a.set_yscale("log")
        a.set_ylim(vg[key].min() / 3, vg[key].max() * 2)
        a.set_xlabel("点间距 h（重叠区像素）"); a.set_ylabel("γ(h)（像素²）")
        a.set_title(f"相对全局仿射残差的经验变异函数：{title}"); a.legend(fontsize=7); a.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(HERE / "variogram.png", dpi=110); plt.close(fig)


def plot_offsets(table: list[dict], members: dict) -> None:
    rois = sorted(members)
    fig, ax = plt.subplots(2, 1, figsize=(13, 8))
    data = [[r["dx_centre"] for r in table if r["roi"] == roi] for roi in rois]
    ax[0].boxplot(data, labels=[r[4:] for r in rois], whis=(5, 95), showfliers=False)
    ax[0].axhline(0, color="k", lw=0.5); ax[0].set_ylabel("patch 中心的 x 向错位（像素）")
    ax[0].set_title("逐 patch 残余错位 x 分量（箱：四分位，须：5–95%）")
    data = [[r["dy_centre"] for r in table if r["roi"] == roi] for roi in rois]
    ax[1].boxplot(data, labels=[r[4:] for r in rois], whis=(5, 95), showfliers=False)
    ax[1].axhline(0, color="k", lw=0.5); ax[1].set_ylabel("y 向错位（像素）"); ax[1].set_title("y 分量")
    fig.tight_layout(); fig.savefig(HERE / "offsets.png", dpi=110); plt.close(fig)

    fig, axes = plt.subplots(1, len(rois), figsize=(2 * len(rois), 9), sharey=False)
    for a, roi in zip(axes, rois):
        rows = [r for r in table if r["roi"] == roi]
        x = [r["opt_col"] / SIZE for r in rows]
        y = [r["opt_row"] / SIZE for r in rows]
        c = [r["dx_centre"] for r in rows]
        lim = max(10, np.percentile(np.abs(c), 95))
        sc = a.scatter(x, y, c=c, cmap="RdBu_r", vmin=-lim, vmax=lim, marker="s", s=12)
        a.invert_yaxis(); a.set_aspect("equal"); a.set_title(roi[4:], fontsize=9); a.set_xticks([])
        fig.colorbar(sc, ax=a, fraction=0.08, shrink=0.5)
    fig.suptitle("patch 中心 x 向错位在条带上的分布（每格一个 patch，色标单位像素）")
    fig.tight_layout(); fig.savefig(HERE / "offset_maps.png", dpi=100); plt.close(fig)


def write_tables(s: dict, rois: list[dict], removed: list[dict], patches: list[Patch]) -> None:
    f = lambda v, n=2: f"{v:.{n}f}"
    lines = ["# 评测真值点：仿射残差、有多斜、变异函数与逐 patch 偏移", "",
             "由 `analyze.py` 生成，勿手改。像素指 7.5 m 网格的像素。", ""]
    a, b = s["residual_after"], s["residual_before"]
    lines += ["## 1. 仿射拟合残差", "",
              f"每 patch 点数：{s['points_per_patch']}。", "",
              "| | 剔除前 | 剔除后 |", "|---|---|---|",
              f"| patch / 点 | {b['patches']} / {b['points']} | {a['patches']} / {a['points']} |",
              f"| 每分量自由度 | {b['dof_per_component']} | {a['dof_per_component']} |",
              f"| σ̂x（95% 区间） | {f(b['sigma_x'])} | {f(a['sigma_x'])}（{f(a['sigma_x_ci95'][0])}–{f(a['sigma_x_ci95'][1])}） |",
              f"| σ̂y（95% 区间） | {f(b['sigma_y'])} | {f(a['sigma_y'])}（{f(a['sigma_y_ci95'][0])}–{f(a['sigma_y_ci95'][1])}） |",
              f"| σ̂ 每轴（x、y 合并） | {f(b['sigma_per_axis'])} | {f(a['sigma_per_axis'])} |",
              f"| 稳健 σ（1.4826·MAD）x / y | {f(b['robust_sigma_x'])} / {f(b['robust_sigma_y'])} | {f(a['robust_sigma_x'])} / {f(a['robust_sigma_y'])} |",
              f"| x、y 残差相关系数 | {f(b['corr_xy'])} | {f(a['corr_xy'])} |",
              f"| 超额峰度 x / y | {f(b['kurtosis_excess_x'])} / {f(b['kurtosis_excess_y'])} | {f(a['kurtosis_excess_x'])} / {f(a['kurtosis_excess_y'])} |",
              "", f"3 倍规则剔除 {s['outliers']['removed']} 个点（若残差是高斯、没有粗差，期望约 "
              f"{s['outliers']['expected_if_gaussian']:.0f} 个）。清单见 `outliers.csv`。", "",
              "### 与点在 patch 内位置的关系", "", "| 到中心距离 | 点数 | σx | σy |", "|---|---|---|---|"]
    lines += [f"| {r['from']}–{r['to']} | {r['points']} | {f(r['sigma_x'])} | {f(r['sigma_y'])} |" for r in s["position"]]
    lines += ["", "### 逐 ROI", "", "| ROI | 划分 | patch | 入射角 | 视向 | σx（95%） | σy（95%） | y nugget（指数，h≤1000） | y nugget（线性，h≤100） |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in rois:
        v = s["variogram"]["per_roi"][r["roi"]]
        lines.append(f"| {r['roi']} | {r['split']} | {r['patches']} | {r['incidence_deg']:.1f} | {r['look']} | "
                     f"{f(r['sigma_x'])}（{f(r['sigma_x_ci95'][0])}–{f(r['sigma_x_ci95'][1])}） | "
                     f"{f(r['sigma_y'])}（{f(r['sigma_y_ci95'][0])}–{f(r['sigma_y_ci95'][1])}） | "
                     f"{np.sqrt(v['nugget_y_exp1000']):.2f} | {np.sqrt(v['nugget_y_lin100']):.2f} |")
    sp = s["spearman_incidence"]
    lines += ["", f"入射角与 σ 的 Spearman 秩相关（13 个 ROI）：x {sp['x'][0]:.2f}（p={sp['x'][1]:.2f}），"
              f"y {sp['y'][0]:.2f}（p={sp['y'][1]:.2f}）。表中 nugget 列已开方成 σ。", ""]
    t = s["tilt"]
    pct = lambda v: f"{100 * v:.1f}%"
    qs = lambda v: " / ".join(f(x, 1) for x in v)
    lines += ["## 2. patch 内「有多斜」", "",
              "跨度 = 错位沿 patch 对角线从一角到另一角的变化（像素），分位 5 / 25 / 50 / 75 / 95：", "",
              "| 量 | 分位 |", "|---|---|",
              f"| 实测 A − I | {qs(t['span_q'])} |", f"| 其中 x 分量 | {qs(t['span_x_q'])} |", f"| 其中 y 分量 | {qs(t['span_y_q'])} |",
              f"| 扣掉全局线性部分 A − L | {qs(t['span_local_q'])} |", f"| 零假设（纯平移 + σ̂ 噪声）逐 patch 中位 | {qs(t['null_q'])} |", "",
              "| 阈值（像素） | " + " | ".join(t["frac_span_gt"]) + " |", "|---" * (len(t["frac_span_gt"]) + 1) + "|",
              "| 跨度超过阈值的 patch 比例 | " + " | ".join(pct(v) for v in t["frac_span_gt"].values()) + " |",
              "| 扣掉全局线性部分后 | " + " | ".join(pct(v) for v in t["frac_local_gt"].values()) + " |", "",
              f"跨度超过零假设 95 分位的 patch：实测 {pct(t['frac_span_above_null_p95'])}，扣掉全局线性部分后 {pct(t['frac_local_above_null_p95'])}（零假设下期望 5%）。",
              f"χ² 检验（4 个约束）拒绝「纯平移」的比例：p<0.05 {pct(t['frac_p_translation_lt']['0.05'])}、p<0.01 {pct(t['frac_p_translation_lt']['0.01'])}；"
              f"拒绝「全局线性部分 + 平移」：p<0.05 {pct(t['frac_p_global_slope_lt']['0.05'])}、p<0.01 {pct(t['frac_p_global_slope_lt']['0.01'])}。", "",
              "全局仿射（控制点）本身在 patch 内造成的跨度（合 / x / y，像素）：", "", "| ROI | 合 | x | y |", "|---|---|---|---|"]
    lines += [f"| {roi} | {f(v[0], 1)} | {f(v[1], 1)} | {f(v[2], 1)} |" for roi, v in t["global_span"].items()]
    v = s["variogram"]
    lines += ["", "## 3. 变异函数 nugget（全部 ROI 合并，像素²；括号里开方成 σ）", ""]
    for key, title in (("nugget_x", "x"), ("nugget_y", "y"), ("nugget_y_cressie_hawkins", "y，Cressie–Hawkins 稳健估计")):
        lines += [f"### {title}", "", "| 模型 | 拟合范围 h ≤ | nugget |", "|---|---|---|"]
        for model, row in v[key].items():
            for hm, val in row.items():
                lines.append(f"| {model} | {hm} | {f(val)}（{np.sqrt(val):.2f}） |")
        lines.append("")
    pool = v["pooled"]
    lines += ["### 经验变异函数（合并）", "", "| h 中心 | 点对 | γx | γy | 同 patch γy | 跨 patch γy |", "|---|---|---|---|---|---|"]
    same = dict(zip(np.round(v["within_patch"]["h"], -1), v["within_patch"]["gy"]))
    cross = dict(zip(np.round(v["cross_patch"]["h"], -1), v["cross_patch"]["gy"]))
    for h, n, gx, gy in zip(pool["h"], pool["n"], pool["gx"], pool["gy"]):
        lines.append(f"| {h:.0f} | {int(n)} | {gx:.2f} | {gy:.2f} | "
                     f"{f(same[round(h, -1)]) if round(h, -1) in same else '—'} | {f(cross[round(h, -1)]) if round(h, -1) in cross else '—'} |")
    o = s["offsets"]
    lines += ["", "（同 patch / 跨 patch 两列按 h 中心取整对齐，个别行因中心不同对不上时显示 —；精确值见 `summary.json`。）", "",
              "## 4. 逐 patch 偏移（patch 中心处的错位，像素）", "",
              "分位 5 / 25 / 50 / 75 / 95。逐 patch 数值见 `patches.csv`。", "",
              "| 量 | 分位 |", "|---|---|",
              f"| dx | {qs(o['dx_centre_q'])} |", f"| dy | {qs(o['dy_centre_q'])} |",
              f"| \\|dx\\| | {qs(o['abs_dx_centre_q'])} |", f"| \\|dy\\| | {qs(o['abs_dy_centre_q'])} |"]
    for sp_, vv in o["per_split"].items():
        lines.append(f"| {sp_} \\|dx\\| / \\|dy\\| 中位 | {vv['abs_dx'][2]:.1f} / {vv['abs_dy'][2]:.1f} |")
    lines += ["", "| ROI | dx 分位 | dy 分位 |", "|---|---|---|"]
    lines += [f"| {roi} | {qs(vv['dx'])} | {qs(vv['dy'])} |" for roi, vv in o["per_roi"].items()]
    (HERE / "tables.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
