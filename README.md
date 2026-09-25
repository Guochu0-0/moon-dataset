# 月球光学–SAR 配准数据集

CE-2 7 m DOM 与 Mini-RF SAR 配准数据集的处理代码、文档站与不可再生的小文件。

文档站：双击 `_site/index.html`，不需要安装任何东西，也不需要联网。

## 环境

一个 conda 环境，包从 conda-forge 装，含 GDAL、pyproj 与测试所需的库，并以可编辑方式装入本仓库的 `moondata` 包：

```bash
conda env create -f environment.yml --solver=libmamba
conda activate moon-dataset
```

conda 23.10 起默认求解器就是 libmamba，`--solver=libmamba` 可省；更早的版本要带上它，经典求解器在含 GDAL 的环境上解不出来。也可以一次性设置：`conda config --set solver libmamba`。

## 配置

全部参数在仓库根的 `config.toml`，没有环境变量或命令行开关。换机器时改：

| 键 | 含义 |
|---|---|
| `data_root` | 数据根：原始影像与既有成品所在的目录。代码只读它。 |
| `work_root` | 输出根：两个编号脚本的产物目录，默认 `work/`（不入库）。 |

相对路径按 `config.toml` 所在目录解析。

## 运行

### 两个编号脚本

```bash
python scripts/01_overlap.py [ROI_054 ...]   # 重叠区提取
python scripts/02_patches.py [ROI_054 ...]   # 协同切片
```

唯一的参数是 ROI 列表，不带参数跑全部 ROI，已有产物直接覆盖。两步之间的人工步骤「标控制点」已完成，控制点在 `data/tie-points/`。

| 脚本 | 输入 | 输出 |
|---|---|---|
| `01_overlap.py` | 数据根下的原始影像 | `work/01_overlap/ROI_<nnn>/{opt,sar}.tif` |
| `02_patches.py` | 重叠区影像、`data/tie-points/ROI_<nnn>.pts` | `work/02_patches/<划分>/ROI_<nnn>/{Optical,SAR}/`、`windows.json` |

### 素材

`docs/assets/` 下的配图与 `roi-facts.json` 由素材脚本从数据盘生成，按组单独重跑：

```bash
python scripts/make_assets.py basemap <lroc_color_poles_4k.tif>   # 全月底图
python scripts/make_assets.py samples                             # 首页样例
python scripts/make_assets.py facts [ROI_054 ...]                 # 逐 ROI 事实
python scripts/make_assets.py overlays [ROI_054 ...]              # 原始产品叠合图
python scripts/make_assets.py process                             # 流程配图，先跑 01_overlap.py ROI_054
```

`basemap` 的输入是 [NASA SVS 4720](https://svs.gsfc.nasa.gov/4720) 的 `lroc_color_poles_4k.tif`，不入库。

### 文档站

```bash
python scripts/build_site.py
```

只读仓库里的文件，不需要数据盘。改了 `docs/pages/`、`docs/assets/` 或 `data/metadata/` 后重跑，连同 `_site/` 一起提交。

### 测试

```bash
pytest
```

不需要数据盘。

## 目录

| 路径 | 内容 |
|---|---|
| `scripts/` | 两个编号脚本、素材脚本 `make_assets.py`、站点生成 `build_site.py` |
| `src/moondata/` | 脚本背后的包：`geometry`（纯 numpy 的网格、窗口与仿射）、`raster`（全部 GDAL/pyproj 调用）、`sources`（定位原始输入）、`preprocess`（纯 numpy 的输入表示）、`config`、`assets`、`site`、`errors` |
| `tests/` | `geometry`、`preprocess` 与站点生成器的测试 |
| `config.toml` | 全部参数 |
| `environment.yml` | conda 环境 |
| `data/` | 控制点、评测真值点、Mini-RF 元数据表，见 [`data/README.md`](data/README.md) |
| `docs/pages/` | 文档站正文 |
| `docs/theme/` | 文档站样式、脚本与字体 |
| `docs/assets/` | 文档站素材（素材脚本生成） |
| `_site/` | 构建好的文档站 |
| `CONTEXT.md` | 术语表 |
| `AGENTS.md`、`docs/agents/`、`.sandcastle/` | agent 约定与编码规范 |
| `work/` | 编号脚本的产物（不入库） |
