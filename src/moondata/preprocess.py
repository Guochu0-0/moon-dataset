"""输入表示：把一个 patch 的原始像素变成网络输入的固定变换。纯 numpy。

决定与取舍见 `docs/adr/0001-input-representation-no-upper-clip.md`。常数只取自训练集、
三个划分共用；它们是交付给使用者的约定，改了等于换了一份数据集的输入，要改须新写 ADR。

- SAR：总功率 S1 = b1 + b2 取 dB，先夹到 `SAR_FLOOR_DB` 以上，再用训练集常数标准化。
  不截上限：高端全是真实的亮结构。下限只用来消除近零的重采样过冲，非正值也落到这里。
- 光学：灰度直接用训练集常数标准化。阴影饱和（灰度 1）不做特殊处理。

两个函数都输出单通道 `(H, W)` float32，不复制成 3 通道。
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

SAR_FLOOR_DB = -25.0
"""S1 的 dB 下限：Mini-RF Zoom 模式的噪声等效后向散射系数（SIS 表 1 标称值）。"""
SAR_MEAN_DB = -10.976
"""训练集 S1 dB 的均值，全部像素、先夹下限。"""
SAR_STD_DB = 2.711
"""训练集 S1 dB 的标准差，同上。"""
OPTICAL_MEAN = 73.786
"""训练集光学灰度的均值，全部像素。"""
OPTICAL_STD = 26.533
"""训练集光学灰度的标准差，同上。"""


def sar_input(bands: npt.ArrayLike) -> np.ndarray:
    """`(4, H, W)` 原始 SAR 波段 → `(H, W)` float32 的 z 值。

    只用前两个波段（H、V 路接收功率）；交叉功率不进单通道表示。
    """
    bands = np.asarray(bands)
    if bands.ndim != 3 or bands.shape[0] != 4:
        raise ValueError(f"SAR 波段应为 (4, H, W)，实际为 {bands.shape}")
    s1 = bands[0].astype(np.float64) + bands[1]
    db = 10 * np.log10(np.maximum(s1, 10 ** (SAR_FLOOR_DB / 10)))
    return ((db - SAR_MEAN_DB) / SAR_STD_DB).astype(np.float32)


def optical_input(optical: npt.ArrayLike) -> np.ndarray:
    """`(H, W)` uint8 光学灰度 → `(H, W)` float32 的 z 值。

    只收 uint8：常数按 0–255 的灰度算出，已缩放到 [0, 1] 的输入会被静默算错。
    """
    optical = np.asarray(optical)
    if optical.ndim != 2 or optical.dtype != np.uint8:
        raise ValueError(f"光学应为 (H, W) uint8，实际为 {optical.shape} {optical.dtype}")
    return ((optical - OPTICAL_MEAN) / OPTICAL_STD).astype(np.float32)
