# 月球光学–SAR 配准数据集研究工作区

CE-2 7 m DOM × Mini-RF SAR 配准数据集的文档、处理代码与关键元数据。
数据集已冻结；955 GB 影像不在本仓库内，通过可配置的数据根路径引用。

## 先看文档站

全部说明材料在 `_site/` 里，**构建产物随仓库提交**：克隆下来双击 `_site/index.html`
就能读，不装任何工具链、不联网、也不用接移动硬盘。左边导航树，右边页内目录，
右上角搜索框搜全站正文，中文可用。

第一站是[术语表](CONTEXT.md)（仓库根的 `CONTEXT.md`，站点里那一页就是它渲染出来的）。
里面钉死了两件容易出错的事：**对齐控制点**与**评测真值点**不是一回事；
三种同名点文件对 y 的符号处理不一致。两者弄错都不会报错。

改完 `.qmd` 或 `CONTEXT.md` 之后重新构建，一条命令：

```bash
quarto render
```

`_site/` 会整个重生成，**记得连同产物一起提交**——否则读者双击看到的还是旧的。

> 渲染完成后 `_quarto.yml` 会自动跑一步 `python -m moondata.docsite`。Quarto 的搜索
> 在运行时 `fetch("search.json")`、页内目录脚本按 ES 模块加载，这两件事在 `file://`
> 下都会被浏览器拦掉，那一步把它们改成离线也能用的形式。理由写在
> `src/moondata/docsite.py` 的模块 docstring 里。

## 装哪一档

依赖分两档。**先想清楚你要干什么，再决定装哪一个**——分档的唯一理由是
GDAL 在 Windows 上用 pip 装经常失败，那是接手这个项目的人第一个会卡住的地方，
而只想读文档或做分析的人不该被它拦住。

| | 文档档 `environment.yml` | 数据处理档 `environment-data.yml` |
|---|---|---|
| 环境名 | `moon-dataset` | `moon-dataset-data` |
| 含 GDAL/pyproj | 否 | 是 |
| 适合谁 | 读文档、渲染文档站、跑几何层单测、做基于统计快照的分析 | 要真正读取 955 GB 影像、重跑四步流程、复现数据集的人 |
| 需要移动硬盘 | 不需要 | 需要 |

```bash
conda env create -f environment.yml        # 文档档
conda activate moon-dataset
```

```bash
conda env create -f environment-data.yml   # 数据处理档
conda activate moon-dataset-data
```

> **先把求解器换成 libmamba，否则数据处理档基本装不上。** conda 23.10 以前默认用
> 经典 SAT 求解器，它在 `gdal + qt6 + jupyter` 这一锅上会卡到没有尽头——实测跑满
> 40 分钟、吃掉 3.8 GB 内存仍未出解。libmamba 几十秒解完。
>
> ```bash
> conda config --set solver libmamba        # 一次性设置
> conda --version                           # 23.10 及以后已经是默认
> ```
>
> 不想改全局配置的话，在建环境时加 `--solver=libmamba` 也行。

两档都会把本仓库以可编辑方式装进环境，装完即有 `moondata` 命令。

> 只是想读文档的话，其实**什么都不用装**：文档站的构建产物已提交，克隆后直接
> 双击 HTML 即可离线阅读。

## 数据根怎么配

955 GB 影像在一块移动硬盘上，不同机器、不同时刻挂载在不同盘符，所以数据根可配置。
三层来源，**优先级由高到低**，取第一个给出非空值的：

1. 命令行 `--data-root PATH`
2. 环境变量 `MOONDATA_DATA_ROOT`
3. 仓库根 `moondata.toml` 的 `[data] root`

都没给则为「未设置」：文档渲染与快照分析本来就不需要数据根，所以这不影响它们；
但 `moondata doctor` 会以退出码 1 结束，因为它回答不了「数据在不在」这个问题。

相对路径各按自己那层的基准解析——命令行与环境变量按当前工作目录，`moondata.toml`
里写的按该文件所在目录。

```bash
cp moondata.toml.example moondata.toml     # 然后改成本机路径
```

`moondata.toml` 写的是本机挂载点，不入库；入库的是 `moondata.toml.example`。

## 盘没插的时候

**降级运行，不是崩溃。** 凡是能靠统计快照完成的照常跑，只有真正需要读影像的
命令才报错，而且报的是一行中文，不是 traceback。

```bash
moondata doctor
```

一次报全三件事：数据根解析到哪个路径（以及是哪一层给出的）、该路径是否可达、
与统计快照的指纹是否一致。盘插着且一切正常时退出码为 0，否则为 1。

> 快照若尚未生成，「指纹」一栏显示「统计快照尚未生成」——这不算失败，退出码仍是 0。

```
数据根    G:\Lunar_Optical_SAR_Registration_Dataset
来源      环境变量 MOONDATA_DATA_ROOT
可达性    可达
统计快照  D:\Code\moon-dataset\stats\snapshot.json
指纹      一致
```

统计快照在仓库根的 `stats/snapshot.json`，**入库**——文档只读它、不读影像，
所以盘没插时文档照样渲染。它不放在 `data/` 下：`data/` 装的是不可再生的关键资产，
而快照是随时可以重新扫出来的计算产物（见 `data/README.md`）。

## 重新生成统计快照

```bash
moondata scan
quarto render
```

`scan` 读遍 `Processed_Data/` 下全部 patch（光学、SAR、评测真值点），把数量、数据类型、
数值范围、真值点覆盖、与窗口清单的数量差连同生成时间和数据指纹写进
`stats/snapshot.json`。它要读几十 GB，需时十来分钟。之后 `quarto render` 让文档取新值，
**快照与 `_site/` 一起提交**。

什么时候要重跑：`moondata doctor` 报指纹「不一致」时。数据集已冻结，正常情况下不该发生——
真发生了，先查清是数据变了还是快照过期了。

读 patch 不需要 GDAL：`moondata.tiff` 只用标准库与 numpy。这批 TIFF 用 tifffile 读会报
`LIBDEFLATE_BAD_DATA`，理由见该模块 docstring。

指纹刻画的是数据根的**目录形态**（相对路径 + 文件大小），不是像素内容——955 GB
逐字节哈希不现实，而「少了一个 ROI」「patch 数量变了」这类真正会让快照失效的
变化都体现在形态上。

## ROI 档案页

每个 ROI 一页（`docs/rois/ROI_<nnn>.md`），外加总览页，**全部由脚本生成，不手写**：

```bash
moondata pages        # 只读仓库，不需要数据盘；quarto render 前也会自动跑
```

输入全在仓库里：元数据表、统计快照、缩略图清单，以及唯一手写的
`docs/rois/known-issues.toml`（ROI 的已知问题，每条注明出处）。要补一条已知问题，
改这个文件再 `quarto render` 即可。生成的页面随仓库提交；有测试守着「提交的页面
就是生成器此刻的输出」，改了输入忘了重新生成会被测出来。

缩略图要读对齐影像（`raw/ROI_*/cropped/ce2/`，六十多 GB），所以**只能接上数据盘生成**，
生成后作为产物提交（`docs/rois/thumbnails/`，每张图的来源、降采样步长、拉伸区间
记在同目录的 `thumbnails.json` 里）：

```bash
moondata thumbnails   # 需时约五分钟
quarto render
```

对齐影像是 256 × 256 分块存储的，同样由 `moondata.tiff` 读取，不需要 GDAL。

## 对齐与变换求解（流程前三步）

```bash
moondata transform 35 6 --verify      # 第三步：由对齐控制点求全局变换，并对照窗口清单
moondata tiepoints 73                 # 第二步：看某个 ROI 用的是哪一代对齐控制点
moondata overlap 35 --verify          # 第一步：对齐到同一网格，写出 work/aligned/ROI_035/
```

- `tiepoints` / `transform` 只读仓库里的 `data/tie-points/`，**不要数据盘、不要 GDAL**。
  默认模型是最小二乘仿射——产出现有数据集的那个；`--model rigid|similarity|homography`
  供研究对比。`--verify` 用求出的变换重算窗口清单里每个窗口的 SAR 位置，偏差在取整
  误差（[0, 2) 像素）以内算一致；超出的窗口逐个报出编号与偏差，并以退出码 1 结束。
  除 ROI_73（清单是按当年错误的标注算的，见 `data/README.md`）外全部一致。
- `overlap` 要数据处理档环境（GDAL/pyproj）和数据盘。镶嵌、重投影、裁切、重采样在
  **一次** `gdal.Warp` 里完成；5 幅 CE-2 分幅头里写错的 `lat_ts` 在读取时纠正（临时 VRT，
  源文件只读）；写完读回核对两幅确实落在同一网格上。产物写到仓库的 `work/`（不入库），
  `--out` 可改。`--plan-only` 只算网格、秒级完成。
- `overlap --verify` 拿正向算出的网格对照窗口清单里的历史网格。66/68 个 ROI 一致；
  其中 ROI_34、57、58、70 当年是在 SAR 的投影下对齐的，要加 `--grid-crs sar`。
  ROI_65（原点差 0.27 m、多一行）与 ROI_73 的历史网格来自被旧脚本改坏的中间文件，
  **来源不可复现**，原因见 `moondata.overlap` 的模块 docstring。

## 正向窗口与第一级验收（流程第四步的前半）

```bash
moondata windows 6 11 20              # 正向算出窗口，写进 work/windows/ROI_006.json 等
moondata windows 70 --grid-crs sar    # 当年在 SAR 投影下对齐的 ROI，同 overlap
moondata verify-windows               # 第一级验收：验证集 + 测试集，逐条比对窗口清单
moondata verify-windows 35            # 也可以只比某几个 ROI（含训练集）
```

- `windows` 要数据处理档环境和数据盘，**全程不读窗口清单、不读任何历史 patch**：
  对齐控制点 → 仿射变换 → 从原始输入规划网格 → 从原点铺 512 窗口、边缘余量丢弃 →
  四角经变换、各自向零截断、取平均、再截断，得 SAR 窗口 → 丢掉出界与重叠不足 70% 的 →
  丢掉任一边含 0 像素的 → 余下的按顺序编号。规则逐条写在 `moondata.geometry.windows`
  与 `moondata.patches` 的 docstring 里。
- 「含不含 0 像素」看的是**筛选影像**：按当年做法（光学一次、SAR 两次最近邻）从原始输入
  重做的一对对齐影像，默认放在 `work/selection/<ROI>/`，首次每个 ROI 约一两分钟、约 1 GB，
  之后复用。不能用数据盘上现在的对齐影像来判——它们已用 cubic 重做过，nodata 边缘
  差一两个像素，验证/测试集上会多留下 11 个贴边窗口，其后的编号整体错位。
- `verify-windows` 只读 `work/windows/` 与 `data/windows/`，**不读影像、不要数据盘、不要 GDAL**，
  秒级完成。对不上时按 ROI 报出：网格差异、多出和缺少的窗口（带编号与坐标）、
  因此改了编号的窗口、同编号位置不同的窗口及其像素偏差。全部一致退出码 0，否则 1。
- 验收门的完整跑法（首次约半小时、筛选影像共约 15 GB）：
  `moondata windows 6 7 11 20 35 37 49 54 59 60 71 75 80`，再 `moondata windows 70 --grid-crs sar`，
  最后 `moondata verify-windows`。2026-09-23 实跑（GDAL 3.6.2）：**14/14 个 ROI、2107 个窗口
  逐条一致**，没有需要记为「来源不可复现」的 ROI。
- 几何这一半另有一道不读影像的单测（`tests/test_windows.py`）：全部 67 个 ROI 的清单窗口
  都落在正向候选上、SAR 坐标逐像素相等、先后顺序不变。

## 代码结构即流程图

```
src/moondata/
├── overlap/     第一步  算重叠区
├── tiepoints/   第二步  对齐控制点
├── transform/   第三步  估计全局变换
├── patches/     第四步  正向算窗口、切 patch
├── raster/      支撑层  唯一依赖 GDAL/pyproj 的地方
├── geometry/    支撑层  纯 numpy，无地理库，可被完整单测
├── manifest.py  窗口清单的读写（读只用于验收对照；正向结果按同一格式写）
├── config.py    数据根解析
├── snapshot.py  数据指纹与统计快照的存取
├── stats.py     扫描 patch 产物，产出快照里的统计量
├── tiff.py      不依赖影像库的 TIFF 读取器
├── docvalues.py 文档页从快照取值、排版数字
├── metadata.py  Mini-RF 逐 ROI 元数据表的读取
├── thumbnails.py 从对齐影像画 ROI 缩略图
├── roipages.py  生成 ROI 档案页
├── sources.py   产品 ID 解码、CE-2 分幅与分带、条带元数据汇总（来源文档用）
├── doctor.py    自检
├── docsite.py   文档站构建后处理（让 file:// 下搜索可用）
└── cli.py       命令行

stats/snapshot.json   统计快照（入库；文档只读它，不读影像）

_quarto.yml           文档站配置（一条 `quarto render` 走完全程）
CONTEXT.md            术语表；同时是站点的一页
index.qmd             站点首页
docs/                 站点其余页面（docs/agents/ 是给 agent 的约定，不进站点）
_site/                构建产物（入库，供离线双击阅读）
```

`raster/` 与 `geometry/` 之间那条线是有意画的：地理库调用全部收在 `raster/`，
所以几何计算能在没有 GDAL 的机器上跑、并被单元测试完整覆盖。

## 跑测试

```bash
pytest
```

不需要移动硬盘，也不需要 GDAL。

## 更多

- `CONTEXT.md` —— 术语表
- `AGENTS.md` —— agent 约定
- `data/README.md` —— 纳入版本控制的不可再生关键资产
