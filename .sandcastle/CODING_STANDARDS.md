# Coding Standards

reviewer 阶段通过 `@.sandcastle/CODING_STANDARDS.md` 加载本文件，因此这些约定只在
审查时消耗 token，implementation 阶段不付这份成本。

权威来源是仓库里的 [AGENTS.md](../AGENTS.md)、[CONTEXT.md](../CONTEXT.md) 与各模块
docstring；本文件是给 reviewer 的速查，两者冲突时以仓库文档为准。

## 语言与术语

- 注释、docstring、commit message 用简体中文。标识符用英文。
- 领域概念用 `CONTEXT.md` 里的词：「重叠区影像」「控制点」「评测真值点」「窗口」
  「正向复现」「数据根」「输出根」。不要写回已废弃的「对齐影像」「对齐控制点」。
- docstring 解释**为什么**这么做，而不是复述代码做了什么。参照
  `src/moondata/geometry.py` 的模块 docstring：它讲的是哪些实现为复现历史而保留、
  改了会怎样。

## 布局

- 两个编号脚本 `scripts/01_overlap.py`、`scripts/02_patches.py`，加素材脚本
  `scripts/make_assets.py` 与站点生成 `scripts/build_site.py`。编号脚本里只放本步骤的
  流程编排（定网格、写影像、切片、写 `windows.json`），可复用的逻辑在包里；素材脚本与
  站点生成器的逻辑全在包里（`assets`、`site`），脚本只是入口。
- 编号脚本的唯一命令行参数是 ROI 列表，不带参数跑全部 ROI，已有产物直接覆盖。
  不加 argparse 子命令，不加 `moondata` 控制台命令。
- `moondata` 是扁平小包，每个模块一个文件：`config`、`errors`、`geometry`、`raster`、
  `sources`、`assets`、`site`。不要再长出子包。

## 架构

- **GDAL/pyproj 的调用只允许出现在 `moondata.raster` 内。** 其余模块一律不得
  `import` 它们。`geometry` 是纯 numpy、无 IO，窗口位置与编号的全部规则在这里。
- `pyproject.toml` 的 `dependencies` 里不要加 GDAL/pyproj。它们由 `environment.yml`
  从 conda-forge 提供；仓库只有这一个环境文件。
- **配置只有 `config.toml` 一层。** 数据根、输出根、patch 尺寸、重采样方式、按 ROI 的
  `grid_crs` 都在里面，经 `moondata.config.load_config` 读取。不要加环境变量、
  命令行开关或本机私有配置文件；路径不得硬编码。
- 正向复现：从原始输入与控制点算出数据集。历史事实只进显式的修正表（`sources` 里的
  CE-2 `lat_ts` 纠正表、`geometry.EXCLUDED_WINDOWS`，以及 `02_patches.py` 里 ROI_027
  编号后删除的纯色块 `DELETED_NUMBERS`），不读任何历史产物文件。不得为凑一致新增
  表项，也不得在这几张表之外按 ROI 写特例代码。
- 为复现历史而保留的实现（向零截断、1.2 倍外扩、SAR 坐标系网格、剔除表、ROI_027 空号等）
  只在代码注释里讲清：最初做法、造成的问题、为什么仍要模拟。
- 站点生成器只读入库文件（`docs/`、`data/metadata/`、`data/ground-truth/`），数据盘不在
  也能完整重建。页面不用 `fetch()`、不用 ES module，要能在 file:// 下双击打开。
- 影像数据不在仓库内。任何测试或默认代码路径都不得假设数据根存在。

## 数据盘

- **仓库代码不写数据盘上的原有数据**，三个划分都一样。产物写到输出根（默认 `work/`，
  不入库）或 `/tmp`。
- 沙箱里数据根只读挂在 `/mnt/data`，与入库 `config.toml` 的 `data_root` 相同。
  布局：`/mnt/data/raw/ROI_*/`（原始影像）、`/mnt/data/Processed_Data/{Train,Val,Test}/`
  （既有 patch）。
- bind mount 上遍历大量小文件很慢（`stat` 约 511 次/s），这是已知代价，不是卡死。

## 风格

- 模块开头写 `from __future__ import annotations`。
- 用类型标注；结构化数据用 `dataclass`，路径用 `pathlib.Path` 而不是字符串拼接。
- 预期内的错误用 `moondata.errors` 里的异常类型（`MoonDataError` 的子类），不要裸
  `raise Exception`。脚本捕获 `MoonDataError`，打印一行中文、以退出码 1 结束，不打 traceback。

## 文档

- 文档站正文（`docs/pages/`）与 README 遵守写法规则：不写元叙述；标题直接陈述；
  不留开发过程痕迹（issue 编号、「本轮」、验收、实现历史）；不渲染情绪、不反复警告；
  不在正文为设计辩护；写事实、表格、参数、出处；同一事实只写一处。
- README 讲仓库怎么用，不重复数据集事实；数据集事实只在文档站。
- 改了文档正文、素材或元数据表，要重跑 `python scripts/build_site.py` 并连同 `_site/`
  一起提交。

## 测试

- 测试放 `tests/`，用 pytest。只测外部可观察的行为：给定输入得到什么输出；不测内部
  调用关系、不测私有函数。期望值手算或来自已知变换，不拿被测代码的算法重算一遍。
- 两个接缝：`tests/test_geometry.py`（`geometry` 的公开函数）与 `tests/test_site.py`
  （站点生成器的整体输出，含「入库的 `_site/` 与生成器输出逐字节一致」）。
  `raster`、`sources`、素材脚本与编号脚本不设单测。
- 测试不得依赖数据盘，也不得依赖 GDAL/pyproj。
- 测试 fixture 里的路径必须平台中立：用 `tmp_path` 派生并以 `.as_posix()` 写入。
- 校验命令是 `pytest`。**本仓库没有 typecheck 或 CI**，不要臆造 `mypy` 之类的命令。

## 审查时额外留意

- 有没有模块在 `moondata.raster` 之外碰了地理库。
- 有没有代码写数据根下的文件。
- 有没有把本机路径、盘符、或凭据写进代码或提交。
- 中文注释是不是退化成了复述代码。
