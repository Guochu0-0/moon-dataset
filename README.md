# 月球光学–SAR 配准数据集研究工作区

CE-2 7 m DOM × Mini-RF SAR 配准数据集的文档、处理代码与关键元数据。
数据集已冻结；955 GB 影像不在本仓库内，通过可配置的数据根路径引用。

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

两档都会把本仓库以可编辑方式装进环境，装完即有 `moondata` 命令。

> 只是想读文档的话，其实**什么都不用装**：文档站的构建产物已提交，克隆后直接
> 双击 HTML 即可离线阅读。

## 数据根怎么配

955 GB 影像在一块移动硬盘上，不同机器、不同时刻挂载在不同盘符，所以数据根可配置。
三层来源，**优先级由高到低**，取第一个给出非空值的：

1. 命令行 `--data-root PATH`
2. 环境变量 `MOONDATA_DATA_ROOT`
3. 仓库根 `moondata.toml` 的 `[data] root`

都没给则为「未设置」——这不是错误，文档渲染与快照分析本来就不需要数据根。

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

```
数据根    G:\Lunar_Optical_SAR_Registration_Dataset
来源      环境变量 MOONDATA_DATA_ROOT
可达性    可达
统计快照  D:\Code\moon-dataset\data\stats\snapshot.json
指纹      一致
```

指纹刻画的是数据根的**目录形态**（相对路径 + 文件大小），不是像素内容——955 GB
逐字节哈希不现实，而「少了一个 ROI」「patch 数量变了」这类真正会让快照失效的
变化都体现在形态上。

## 代码结构即流程图

```
src/moondata/
├── overlap/     第一步  算重叠区
├── tiepoints/   第二步  对齐控制点
├── transform/   第三步  估计全局变换
├── patches/     第四步  正向算窗口、切 patch
├── raster/      支撑层  唯一依赖 GDAL/pyproj 的地方
├── geometry/    支撑层  纯 numpy，无地理库，可被完整单测
├── config.py    数据根解析
├── snapshot.py  数据指纹与统计快照
├── doctor.py    自检
└── cli.py       命令行
```

`raster/` 与 `geometry/` 之间那条线是有意画的：地理库调用全部收在 `raster/`，
所以几何计算能在没有 GDAL 的机器上跑、并被单元测试完整覆盖。

## 跑测试

```bash
pytest
```

不需要移动硬盘，也不需要 GDAL。

## 更多

- `AGENTS.md` —— agent 约定
- `data/README.md` —— 纳入版本控制的不可再生关键资产
