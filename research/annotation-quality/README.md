# 标注误差的最小复现

文档站「标注质量」页上的每个数、每张图都由本目录的三个脚本从头算出。

```sh
PYTHONPATH=src python research/annotation-quality/windows.py [数据根]   # 需数据盘，写 windows.csv（已入库）
PYTHONPATH=src python research/annotation-quality/estimate.py           # 只读仓库，写 tables.md、results.json
PYTHONPATH=src python research/annotation-quality/figures.py [数据根]   # 写 docs/assets/annotation-quality/*.svg
python scripts/build_site.py
```

数据根默认取 `config.toml` 的 `data_root`。只有 `windows.py` 与 `figures.py` 里的两张例子图要读影像；
`estimate.py` 只用仓库里的评测真值点、控制点、元数据表与 `windows.csv`，不需要 scipy。

- `windows.py`：每个带评测真值点的 patch 在重叠区影像上的光学、SAR 窗口左上角，并校验 SAR 窗口与控制点全局仿射推出的一致。
- `estimate.py`：三种估计方法（最小二乘拟合残差、变异函数、重复测量）。`tables.md` 是全部数字，页面正文照它写。
- `figures.py`：页面上的 6 张图。
