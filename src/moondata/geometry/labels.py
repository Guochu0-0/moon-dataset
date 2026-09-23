"""生成标签的几何：patch 内的一组规则网格点，以及它们在 SAR patch 上的对应位置。

对应位置由全局变换换算到两个窗口的**局部**坐标下算出，不逐点重新匹配——所以生成标签的
精度完全取决于对齐控制点拟合出的那个全局变换。规则取自旧代码
（`lunar_benchmark.patches.make_label`）：每边 5 点、覆盖 `[0, size − 1]` 的闭区间。

生成标签不是评测真值点：后者是人工在 patch 上标的，只在验证集与测试集上有。
"""

from __future__ import annotations

import numpy as np

from moondata.geometry.transforms import apply_transform

LABEL_GRID = 5
"""每边几个点，共 `LABEL_GRID²` 个。"""


def label_points(
    matrix, optical: tuple[int, int], sar: tuple[int, int], size: int, per_side: int = LABEL_GRID
) -> tuple[np.ndarray, np.ndarray]:
    """一对 patch 的标签点：(光学 patch 内的网格点, 它们在 SAR patch 内的位置)，都是 `(n, 2)`。

    `optical`、`sar` 是两个窗口在各自对齐影像上的左上角 (列, 行)；`matrix` 是光学 → SAR 的
    全局 `3×3` 变换。y 向下为正——取负是磁盘格式的事，见 `moondata.patches.labels`。
    """
    axis = np.linspace(0, size - 1, per_side)
    xs, ys = np.meshgrid(axis, axis)
    local = np.column_stack([xs.ravel(), ys.ravel()])
    warped = apply_transform(local + np.asarray(optical, float), matrix)
    return local, warped - np.asarray(sar, float)
