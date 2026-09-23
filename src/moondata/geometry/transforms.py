"""由同名点估计二维全局变换：刚体、相似、仿射、单应。

约定
----
- 点集是 `(n, 2)`，列序 `(x, y)` = (列号, 行号)，y 向下为正——与术语表里的坐标符号
  约定一致，本层从不见到取负的 y。
- 四种模型一律返回 `3×3` 齐次矩阵。前三种的末行恒为 `[0, 0, 1]`；统一形状是为了让
  调用方不必按模型分支（旧代码就栽在「`(2,3)` 与 `(3,3)` 各走一支、第三种形状落空」上）。
- 点数不够就抛 `InsufficientPoints`，点集退化（重合、共线）就抛 `DegeneratePoints`。
  **从不静默降级**：少一个点就改解低一档的模型，得到的是另一个问题的答案。
"""

from __future__ import annotations

from enum import Enum

import numpy as np

from moondata.errors import DegeneratePoints, InsufficientPoints


class TransformModel(Enum):
    """值是命令行里用的名字。"""

    RIGID = "rigid"
    SIMILARITY = "similarity"
    AFFINE = "affine"
    HOMOGRAPHY = "homography"

    @property
    def min_points(self) -> int:
        """刚体 3 个自由度、相似 4 个、仿射 6 个、单应 8 个；每对点给两个方程。"""
        return {"rigid": 2, "similarity": 2, "affine": 3, "homography": 4}[self.value]


def estimate_transform(src, dst, model: TransformModel) -> np.ndarray:
    """最小二乘估计把 `src` 映到 `dst` 的变换，返回 `3×3`。"""
    source, target = _pair(src, dst, model)
    if model is TransformModel.AFFINE:
        return _affine(source, target)
    if model is TransformModel.RIGID:
        return _procrustes(source, target, scaled=False)
    if model is TransformModel.SIMILARITY:
        return _procrustes(source, target, scaled=True)
    return _homography(source, target)


def apply_transform(points, matrix) -> np.ndarray:
    """把 `(n, 2)` 的点按 `3×3` 矩阵变换（含透视除法），返回 `(n, 2)`。"""
    pts = _points(points, "points")
    m = np.asarray(matrix, dtype=np.float64)
    if m.shape != (3, 3):
        raise ValueError(f"变换矩阵应为 3×3，实际为 {m.shape}")
    homo = np.column_stack([pts, np.ones(len(pts))]) @ m.T
    return homo[:, :2] / homo[:, 2:3]


def _affine(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    # lstsq 而不是正规方程 inv(PᵀP)Pᵀ：后者把条件数平方，旧代码就是这么写的。
    design = np.column_stack([src, np.ones(len(src))])
    solution, _, rank, _ = np.linalg.lstsq(design, dst, rcond=None)
    if rank < 3:
        raise DegeneratePoints("仿射变换要求控制点不全共线")
    return np.vstack([solution.T, [0.0, 0.0, 1.0]])


def _procrustes(src: np.ndarray, dst: np.ndarray, *, scaled: bool) -> np.ndarray:
    """Kabsch/Umeyama：刚体（`scaled=False`）或相似（`scaled=True`）。"""
    src_mean, dst_mean = src.mean(axis=0), dst.mean(axis=0)
    src_c, dst_c = src - src_mean, dst - dst_mean
    spread = float((src_c**2).sum())
    if spread == 0.0:
        raise DegeneratePoints("源点全部重合，定不出旋转")
    u, sigma, vt = np.linalg.svd(dst_c.T @ src_c)
    # det(U·Vᵀ) = −1 时它是反射而不是旋转——旧代码漏了这一步，控制点噪声大时会悄悄
    # 输出一个镜像的「刚体」。翻转最小奇异值对应的方向，得到离它最近的真旋转；
    # 缩放的分子要跟着减去那个奇异值（Umeyama）。
    flip = np.diag([1.0, np.sign(np.linalg.det(u @ vt)) or 1.0])
    rotation = u @ flip @ vt
    scale = float((sigma * np.diag(flip)).sum()) / spread if scaled else 1.0
    matrix = np.eye(3)
    matrix[:2, :2] = scale * rotation
    matrix[:2, 2] = dst_mean - scale * rotation @ src_mean
    return matrix


def _homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """归一化 DLT。像素坐标动辄上万，不先做 Hartley 归一化，设计矩阵各列差好几个
    数量级，解会明显失真。"""
    t_src, src_n = _hartley(src)
    t_dst, dst_n = _hartley(dst)
    rows = []
    for (x, y), (u, v) in zip(src_n, dst_n):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, singular, vt = np.linalg.svd(np.asarray(rows))
    # 零空间不止一维（第 8 个奇异值也≈0）说明点集退化，比如 4 点里有 3 点共线。
    if singular[7] < 1e-10 * singular[0]:
        raise DegeneratePoints("单应变换要求控制点里不能有太多点共线")
    h = np.linalg.inv(t_dst) @ vt[-1].reshape(3, 3) @ t_src
    return h / h[2, 2]


def _hartley(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """平移到质心、缩放到平均距离 √2。返回 (归一化矩阵, 归一化后的点)。"""
    centroid = points.mean(axis=0)
    centered = points - centroid
    mean_distance = float(np.sqrt((centered**2).sum(axis=1)).mean())
    if mean_distance == 0.0:
        raise DegeneratePoints("控制点全部重合")
    scale = np.sqrt(2.0) / mean_distance
    matrix = np.array(
        [[scale, 0.0, -scale * centroid[0]], [0.0, scale, -scale * centroid[1]], [0.0, 0.0, 1.0]]
    )
    return matrix, centered * scale


def _points(points, name: str) -> np.ndarray:
    array = np.asarray(points, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 2:
        raise ValueError(f"{name} 应为 (n, 2) 的点集，实际为 {array.shape}")
    return array


def _pair(src, dst, model: TransformModel) -> tuple[np.ndarray, np.ndarray]:
    source, target = _points(src, "src"), _points(dst, "dst")
    if len(source) != len(target):
        raise ValueError(f"两侧点数不一致：{len(source)} 对 {len(target)}")
    if len(source) < model.min_points:
        raise InsufficientPoints(
            f"{model.value} 变换至少需要 {model.min_points} 对点，实际只有 {len(source)} 对"
        )
    return source, target
