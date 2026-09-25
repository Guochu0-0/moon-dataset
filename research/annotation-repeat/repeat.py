"""控制点与评测真值点里的「无意重标」：用它锚定标注误差（issue #41，地图 #34）。

    python research/annotation-repeat/repeat.py

控制点（ENVI，整幅重叠区影像，整数像素）与评测真值点（ArcGIS，逐 patch，亚像素）是同一个人
先后两次、用两套工具独立标的。标评测真值点时常常又选中了标控制点时用过的显眼地物，于是
两套点里有一批落在同一处：这就是现成的重复标注，不依赖残余错位的形状假设。

输入只有仓库里的东西：`data/ground-truth/`、`data/tie-points/`，以及
`research/ground-truth-residuals/windows.csv`（窗口位置）。产出写到本目录：
`pairs.csv`（全部 5 像素内的配对）与 `tables.md`。

记号：点放回重叠区影像坐标，光学 `P`、SAR `Q`，位移 `d = Q − P`。一个配对是一个评测真值点
与一个控制点，光学侧相距 `r = |P_gt − P_tie|`。两次标注之差 `e = d_gt − d_tie`，每轴

    Var(e) = 2σ² + 2/12

σ 是一次标注（光学、SAR 两次点击合成）每轴的误差，两次标注假定同样准、相互独立；2/12 是
控制点光学、SAR 两个坐标都取整带来的量化方差。`r` 越大越可能不是同一处，残余错位在 `r`
上的变化也混进来，所以按 `r` 的阈值分档报。粗差按 3 倍 MAD 剔除（任一分量超出即剔）。

偶然重合的期望数：把控制点整体平移（每轴 ±50–300 像素随机）后重数 5 像素内的配对，取平均。
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from moondata.sources import load_tie_points  # noqa: E402

HERE = Path(__file__).resolve().parent
WINDOWS = REPO_ROOT / "research" / "ground-truth-residuals" / "windows.csv"
GROUND_TRUTH = REPO_ROOT / "data" / "ground-truth"
RADIUS = 5.0
THRESHOLDS = (1.0, 2.0, 3.0, 5.0)
QUANT = 2 / 12
SHUFFLES = 200


def ground_truth() -> dict[str, np.ndarray]:
    """每个 ROI 的评测真值点，重叠区影像坐标 (P_x, P_y, Q_x, Q_y)。"""
    out: dict[str, list[np.ndarray]] = {}
    with WINDOWS.open(newline="") as f:
        for row in csv.DictReader(f):
            if row["labelled"] != "1":
                continue
            path = GROUND_TRUTH / row["split"] / row["roi"] / f"patch_{row['patch']}.txt"
            a = np.loadtxt(path, ndmin=2)[:, :4].copy()
            a[:, [1, 3]] *= -1  # 磁盘格式 y 取负
            a += [int(row["opt_col"]), int(row["opt_row"]), int(row["sar_col"]), int(row["sar_row"])]
            out.setdefault(row["roi"], []).append(a)
    return {roi: np.vstack(v) for roi, v in out.items()}


def match(gt: np.ndarray, tie: np.ndarray) -> list[tuple[int, int, float]]:
    r = np.hypot(gt[:, None, 0] - tie[None, :, 0], gt[:, None, 1] - tie[None, :, 1])
    return [(i, j, r[i, j]) for i, j in zip(*np.nonzero(r < RADIUS))]


def main() -> None:
    gt = ground_truth()
    ties = {roi: np.hstack(load_tie_points(REPO_ROOT, roi)) for roi in gt}

    rows = []
    for roi in sorted(gt):
        for i, j, r in match(gt[roi], ties[roi]):
            g, t = gt[roi][i], ties[roi][j]
            e = (g[2:] - g[:2]) - (t[2:] - t[:2])
            rows.append((roi, i, j, r, *(g[:2] - t[:2]), *e))

    rng = np.random.default_rng(0)
    chance = []
    for _ in range(SHUFFLES):
        n = 0
        for roi in gt:
            shift = rng.uniform(50, 300, 2) * rng.choice([-1, 1], 2)
            moved = ties[roi].copy()
            moved[:, :2] += shift
            n += len(match(gt[roi], moved))
        chance.append(n)

    with (HERE / "pairs.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["roi", "gt_index", "tie_index", "r", "dp_x", "dp_y", "e_x", "e_y"])
        for row in rows:
            w.writerow([row[0], row[1], row[2], *(f"{v:.4f}" for v in row[3:])])

    data = np.array([row[3:] for row in rows])
    n_tie = sum(len(t) for t in ties.values())
    lines = [
        "# 无意重标：控制点与评测真值点落在同一处",
        "",
        f"13 个验证、测试 ROI 共 {n_tie} 个控制点、{sum(len(g) for g in gt.values())} 个评测真值点。"
        f"光学侧 {RADIUS:g} 像素内的配对 {len(rows)} 个；控制点随机平移后同样半径内平均 "
        f"{np.mean(chance):.1f} 个（{SHUFFLES} 次，最多 {max(chance)}），所以几乎全是同一处地物。",
        "",
        "σ 是一次标注、每轴的误差（光学与 SAR 两次点击合成），已扣控制点取整的量化方差；"
        "± 是 σ 的近似标准误 `σ / √(2(n−1))`。中位数是两次标注之间的系统差 `e`。",
        "",
        "| 光学侧距离 r | 配对 | 剔除 | σx（像素） | σy（像素） | e 中位数 x | e 中位数 y |",
        "|---|---|---|---|---|---|---|",
    ]
    for thr in THRESHOLDS:
        e = data[data[:, 0] < thr, 3:5]
        med = np.median(e, axis=0)
        mad = 1.4826 * np.median(np.abs(e - med), axis=0)
        keep = np.all(np.abs(e - med) < 3 * mad, axis=1)
        s2 = e[keep].var(axis=0, ddof=1)
        sigma = np.sqrt((s2 - QUANT) / 2)
        se = sigma / np.sqrt(2 * (keep.sum() - 1))
        lines.append(
            f"| < {thr:g} | {len(e)} | {len(e) - keep.sum()} | {sigma[0]:.2f} ± {se[0]:.2f} | "
            f"{sigma[1]:.2f} ± {se[1]:.2f} | {med[0]:+.2f} | {med[1]:+.2f} |"
        )
    counts = {roi: sum(1 for row in rows if row[0] == roi) for roi in sorted(gt)}
    lines += ["", "每个 ROI 的配对数（r < 5）：" + "、".join(f"{k} {v}" for k, v in counts.items()) + "。", ""]
    (HERE / "tables.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
