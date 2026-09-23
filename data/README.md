# `data/` — 纳入版本控制的关键资产

本目录存放本项目中**不可再生**的小体积文件。它们是**数据，不是备份**：

- 955 GB 影像（CE-2 DOM 瓦片、Mini-RF 条带、切好的 patch）**可以重新下载或重新计算**，
  所以不进仓库，通过可配置的数据根路径引用。
- 本目录里的三类文件**一旦丢失就无法恢复**，或者恢复代价等同于推翻整个数据集：
  - **对齐控制点**是人工在 ENVI 中逐 ROI 标注的，丢了就是几十小时人工没了；
  - **窗口清单**是正向复现的验收基准，且是重切后「网格、窗口、编号」不变的唯一凭据，
    一旦丢失，验证集/测试集上的人工评测真值点全部作废；
  - **Mini-RF 逐 ROI 元数据表**是文档自足渲染 ROI 档案页的前提，其中「实测」列
    是在 955 GB 影像上量出来的，重算需要接上移动硬盘跑数小时。

因此它们被放进 git：要的是**完整改动历史**与**异地副本**，而不是某一时刻的快照。

> **源文件留在原处，一个字节都不改。** 本目录是只读副本，入库时逐文件核对过 SHA-256。
> 若将来源目录与本目录不一致，**以本目录为准**并查明源目录被谁改了。

## 目录结构

```
data/
├── README.md              本文件
├── SHA256SUMS.txt         全部 258 个文件的 SHA-256 清单
├── tie-points/            对齐控制点，68 个 ROI 目录、254 个文件
│   └── ROI_<n>/
│       ├── cropped/       当年真正用于生产的那一代
│       ├── cropped_1/     已废弃的一代（见下）
│       └── cropped_2/     仅 ROI_73，2026-09-11 重标
├── windows/
│   ├── windows.json       验证集 + 测试集窗口清单
│   └── windows_train.json 训练集窗口清单
└── metadata/
    ├── minirf_metadata.csv            Mini-RF 逐 ROI 元数据表
    └── removed_ROI_060_manifest.txt   被删除的 ROI_060 的文件清单
```

## 1. 对齐控制点 `tie-points/`

| 项 | 值 |
|---|---|
| 来源 | `D:\Data\Moon\tiepoints_backup\`（原始标注散落在 `G:\Lunar_Optical_SAR_Registration_Dataset\raw\ROI_<n>\cropped\ce2\opt_tie.*`，该备份目录是已整理过的权威副本） |
| 规模 | 68 个 ROI 目录、254 个文件、563 KB |
| 格式 | `.pts` ENVI Image-to-Image Tie Points；部分 ROI 另有同名 `.txt`（地图坐标，米）与 `.prj`（投影定义） |

**内容含义。** 每个 `opt_tie.pts` 是人工在**整幅对齐影像**（不是 patch）上标注的光学–SAR
同名点，用于解算该 ROI 的全局变换、进而决定 patch 切在何处。**这就是术语表里的
「对齐控制点（alignment tie points）」，与 patch 旁边的「评测真值点」是两种东西**，
不要混用。

- **ROI 数量口径：这里是 68 个 ROI 目录，数据集是 67 个 ROI。** 差的一个是 **ROI_60**
  ——它与 ROI_37 逐像素重复、已从主数据盘删除，但它的人工标注是照样标过的，
  同样不可再生，所以原样保留在此。凡是引用「67」的地方（issue、术语表）说的都是
  不含 ROI_60 的口径。
- 67 个 ROI 的控制点在 `cropped/opt_tie.pts`（ROI_60 在内、ROI_73 不在内），
  ROI_73 的在 `cropped_2/opt_tie.pts`。
- 每 ROI 19–150 对，中位数约 30 对：`cropped/opt_tie.pts` 合计 2157 对（其中 ROI_60 占 24 对），
  ROI_73 另有 30 对。
- `.pts` 是像素坐标（`base x, base y, warp x, warp y, score`），`.txt` 是同一批点的
  地图坐标（米），`.prj` 是 `.txt` 所用的投影。三者的坐标符号约定不同，详见术语表。

**`cropped` / `cropped_1` / `cropped_2` 是三代对齐产物，不是三种标注。**

- `cropped` —— 当年真正用来切片的那一代，**控制点以这一代为准**。
- `cropped_1` —— 已被认定为坏的一代：opt 与 sar 不在同一个网格上（墨卡托 vs 等距圆柱），
  因为当年的脚本把两幅各自 warp 到了自己的 CRS。影像已删除，**标注保留在此仅作历史记录，
  不要拿来算变换**。
- `cropped_2` —— 只有 ROI_73 有。ROI_73 的旧标注是双重错误：光学影像用了错误坐标
  （偏离约 205 km），且 `opt_tie.*` 实际标在 ROI_74 的影像上（存错了文件夹）。
  那三个文件已改名为 `opt_tie_作废_实为ROI74.*` 保留，正确标注在 `cropped_2/`。

**文件名保持原样**，包括空格、中文和 `opt_tie - 副本 (2).pts` 这种痕迹。
文件名与格式是格式契约的一部分，也是这批人工劳动的原始状态，不做任何整理。

## 2. 窗口清单 `windows/`

| 文件 | 来源 | 内容 |
|---|---|---|
| `windows.json` | `D:\Data\Moon\windows.json` | 14 个 ROI（Test 7 / Val 7），2107 个窗口（Test 1130 / Val 977） |
| `windows_train.json` | `D:\Data\Moon\windows_train.json` | 54 个 ROI，7886 个窗口 + 3 个 `unresolved` |

**内容含义。** 逐 ROI 记录切分所用的网格（`width`/`height`/`transform`/`crs`）与每一个
窗口的左上角像素坐标：

```json
{"patch_size": 512, "aligned_name": "cropped",
 "rois": {"ROI_006": {"grid": {...}, "split": "Test", "roi": 6,
                      "patches": [{"index": 0, "optical": [1024, 1536], "sar": [466, 1628]}, ...],
                      "unresolved": []}}}
```

**这份文件的用途发生过一次转变，必须记住。** 它最初是**从已有 patch 反推**得到的，
目的是保证重切之后「网格、窗口、编号」三者不变，从而让 patch 上的人工评测真值点继续成立。
现在旧产物已被删除，反推工具再也跑不了，它转变为**正向复现的验收基准**：新代码正向算出的
窗口必须与这里逐条相等。同一份文件，两种截然不同的用途。

`windows_train.json` 的 7886 个窗口（另有 3 个 `unresolved`）与实际训练集产物的
7907 个对不上。据数据集作者说明，差异来自两个训练集 ROI：

- **ROI_73**：清单里的 98 个窗口是按当年**错误的**对齐控制点算出来的（后来在
  `cropped_2/` 重标），产物有 119 个。正向复现**不要求**与这里的旧窗口一致。
- **ROI_27**：3 个 `unresolved`。作者印象中是几个因光照问题基本全黑、被删掉的 patch，
  与产物中该 ROI 的编号断档吻合；旧迁移记录 `D:\Data\Moon\MIGRATION.md` 也写明
  「ROI_027 缺 95/98/99（纯色废块）」。

两者都在训练集。正向复现的验收只在验证集与测试集上设门，那两个划分的清单与产物
完全一致。**不得**为凑数修改本文件。

## 3. Mini-RF 逐 ROI 元数据表 `metadata/minirf_metadata.csv`

| 项 | 值 |
|---|---|
| 来源 | `D:\Data\Moon\minirf_metadata.csv` |
| 规模 | 68 行 × 19 列，11 KB，UTF-8 with BOM |

每行一个 ROI。列分两类：

- **[官方]** 取自该条带的 PDS `.LBL`：`PRODUCT_ID`、轨道号、任务阶段、成像时刻 UTC、
  模式、中心频率、入射角、视向、视方位角、投影、`MAP_RESOLUTION_ppd`、原生采样、
  条带尺寸、波段数。
- **[实测]** 在本数据集影像上量出来的：`实测有效分辨率_距离向_m`、`实测有效分辨率_方位向_m`。

`划分` 列除 `Train`/`Val`/`Test` 外还有一个特殊值：**ROI_60 = `已删除(与ROI_37重复)`**
——该 ROI 与 ROI_37 逐像素重复，已从主数据盘删除。凡统计 ROI 数量的地方都要明确口径是
「含 ROI_60 的 68」还是「不含的 67」。

## 4. 删除清单 `metadata/removed_ROI_060_manifest.txt`

| 项 | 值 |
|---|---|
| 来源 | `D:\Data\Moon\docs\removed_ROI_060_manifest.txt` |
| 规模 | 599 行，UTF-8 |

2026-09-20 删除 `Processed_Data/Val/ROI_060` 时留下的记录：头部几行 `#` 注释写明删了什么、
为什么删、何时删，其后逐行列出被删的每个文件的相对路径。

它是 ROI_060 **唯一的剩余记录**——patch 与评测真值点都已从数据盘删除。统计快照
（`moondata scan`）靠它给出「含已删除 ROI」口径的 patch 数与带真值点的 patch 数。
清单只有文件名，没有内容，所以 ROI_060 的评测真值点**点数已无从得知**。

## 校验

`SHA256SUMS.txt` 覆盖本目录下全部 258 个文件（`README.md` 与清单自身除外）。

```bash
cd data && sha256sum -c SHA256SUMS.txt
```

仓库根的 `.gitattributes` 对 `data/**` 设了 `-text`，关闭一切行尾转换——
`.pts`/`.txt` 是 CRLF 文本，一旦被规范化，校验和就与源文件不再一致。

## 不在本目录的东西

- **955 GB 影像数据**（CE-2 瓦片、Mini-RF 条带、对齐影像、切好的 patch）：可再生，
  通过数据根路径引用。
- **评测真值点**（patch 旁的 `Label/*.txt`，Test 1906 + Val 1304 = 3210 个文件，774 KB）：
  同样不可再生，目前仍只存在于
  `G:\Lunar_Optical_SAR_Registration_Dataset\Processed_Data\{Test,Val}\ROI_*\Label\`。
  **不在本 issue 的范围内**，但它与对齐控制点的风险完全同级，应尽快单开一项纳入版本控制。
