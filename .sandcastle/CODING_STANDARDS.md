# Coding Standards

reviewer 阶段通过 `@.sandcastle/CODING_STANDARDS.md` 加载本文件，因此这些约定只在
审查时消耗 token，implementation 阶段不付这份成本。

权威来源是仓库里的 [AGENTS.md](../AGENTS.md) 与各模块 docstring；本文件是给 reviewer
的速查，两者冲突时以仓库文档为准。

## 语言

- 注释、docstring、commit message 用简体中文。标识符用英文。
- docstring 解释**为什么**这么做，而不是复述代码做了什么。参照
  `src/moondata/config.py` 的模块 docstring：它讲的是「数据根为什么必须可配置」
  以及「未设置为什么在库层面不算异常」。

## 架构

- **GDAL/pyproj 的调用只允许出现在 `moondata.raster` 内。** 其余模块一律不得
  `import` 它们。这是硬约束：只装了文档档环境（`environment.yml`，无地理库）的人
  必须还能 import 本包、跑几何层和自检命令。见 `src/moondata/raster/__init__.py`。
- `pyproject.toml` 的 `dependencies` 里不要加 GDAL/pyproj。它们只能由 conda 提供，
  见 `environment-data.yml`。
- 数据根路径不得硬编码。三层来源（`--data-root` → `MOONDATA_DATA_ROOT` →
  `moondata.toml`）的解析已收在 `moondata.config`，新代码走它。
- 955 GB 影像数据不在仓库内。任何测试或默认代码路径都不得假设数据根存在。

## 沙箱里的数据根

- 数据根已按 `MOONDATA_DATA_ROOT=/mnt/data` **只读**挂进沙箱。所以镶嵌、重投影、
  裁切、以及对着既有产物的逐字节验收，都能在沙箱里真的跑，不必假装。
- **`/mnt/data` 下一个字节都不许写。** 那 919 GB 原始影像不可再生，挂载本身是只读的，
  尝试写入会直接报错。中间产物和输出一律写到工作区内（会被 git 看到）或 `/tmp`。
- 布局：`/mnt/data/raw/ROI_*/`（原始影像，919 GB）、
  `/mnt/data/Processed_Data/{Train,Val,Test}/`（既有 patch 产物，37 GB / 22934 个文件）。
- 读大影像的随机块（GDAL 的常规访问方式）速度正常。但**遍历大量小文件很慢**——
  bind mount 的 `stat` 只有约 511 次/s，比宿主慢两个数量级。全量逐字节验收 22934 个
  文件约需 10 分钟，这是已知代价，不是卡死，别中途放弃或改小验收范围来绕。

## 风格

- 模块开头写 `from __future__ import annotations`。
- 用类型标注；结构化数据用 `dataclass`，枚举用 `Enum`，路径用 `pathlib.Path`
  而不是字符串拼接。
- 错误用 `moondata.errors` 里的异常类型，不要裸 `raise Exception`。
- 退出码有语义（例如 `moondata doctor` 在数据根未设置时以 1 退出，因为它答不上
  「数据在不在」）。改动退出码要在 docstring 里说明理由。

## 测试

- 测试放 `tests/`，用 pytest。`pyproject.toml` 已配好 `pythonpath = ["src"]`。
- 测试不得依赖 GDAL/pyproj，也不得依赖真实数据根。沙箱里两者都有，但只装了文档档
  （`environment.yml`，无地理库）、也没挂数据盘的人必须还能把测试跑全绿。需要真实
  数据或地理库才能验的东西，走命令行端到端跑，不要写成单测。
- 测试 fixture 里的路径必须平台中立：用 `tmp_path` 派生并以 `.as_posix()` 写入，
  不要写 `F:/...` 这类盘符路径。盘符在 Linux 上是相对路径，沙箱是 Linux 容器。
  （`.as_posix()` 而非 `str()`：Windows 的反斜杠在 TOML 字符串里是转义符。）
- 校验命令是 `pytest`。**本仓库没有 typecheck 脚本**，不要臆造 `npm run typecheck`
  或 `mypy` 之类的命令。

## 审查时额外留意

- 有没有模块在 `moondata.raster` 之外碰了地理库。
- 有没有把本机路径、盘符、或凭据写进代码或提交。
- 中文注释是不是退化成了复述代码。
