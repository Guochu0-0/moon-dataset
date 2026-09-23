"""标签文件 `Label/patch_<n>.txt` 的读写——格式契约，不改。

每行四列：光学 x、光学 y、SAR x、SAR y，**两个 y 都取负**（遗留的数学坐标习惯）。
字节层面照现有 1605 个评测真值点文件的样子：制表符分隔、8 位小数、CRLF 换行。

**取负只在这里发生**：读进来立刻翻回向下为正的行号，写出去时再翻一次；包内其余地方
的 y 一律为正（见术语表「坐标符号约定」）。对齐控制点的 `.pts` 与 `.txt` 不取负，
它们不经过本模块。

评测真值点与生成标签共用这个格式，本模块两者都能读写；但它们不是一种东西——
前者是人工在 patch 上标的，后者由全局变换算出（`moondata.geometry.label_points`）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

COLUMNS = 4
DECIMALS = 8
NEWLINE = b"\r\n"


def format_label(optical: np.ndarray, sar: np.ndarray) -> bytes:
    """`(n, 2)` 的两组点（y 向下为正）→ 标签文件的字节。"""
    rows = np.column_stack([optical[:, 0], -optical[:, 1], sar[:, 0], -sar[:, 1]])
    # 先按写出的精度取整再 + 0.0：第 0 行、或只差浮点残差的点取负之后不该写成 "-0.00000000"
    return b"".join(
        "\t".join(f"{round(value, DECIMALS) + 0.0:.{DECIMALS}f}" for value in row).encode("ascii")
        + NEWLINE
        for row in rows
    )


def parse_label(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """标签文件的字节 → (光学点, SAR 点)，都是 `(n, 2)`、y 向下为正。"""
    rows = []
    for number, line in enumerate(data.decode("ascii").splitlines(), start=1):
        if not line.strip():
            continue
        values = [float(token) for token in line.split()]
        if len(values) != COLUMNS:
            raise ValueError(f"标签第 {number} 行应有 {COLUMNS} 列，实际 {len(values)} 列：{line!r}")
        rows.append(values)
    table = np.asarray(rows, dtype=np.float64).reshape(-1, COLUMNS)
    return (
        np.column_stack([table[:, 0], -table[:, 1]]),
        np.column_stack([table[:, 2], -table[:, 3]]),
    )


def write_label(path: Path, optical: np.ndarray, sar: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(format_label(optical, sar))
    return path


def read_label(path: Path) -> tuple[np.ndarray, np.ndarray]:
    return parse_label(path.read_bytes())
