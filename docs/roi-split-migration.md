# ROI 划分迁移

当前 ROI 归属以 [Mini-RF 逐 ROI 元数据表](../data/metadata/minirf_metadata.csv) 的「划分」列为准。迁移基线是 Git 修订 `0388796`，其中 ROI_017 已排除 18 对 patch。旧划分与当前划分均有 9,844 对 patch，复现实验时记录 Git 修订或 ROI 归属。

## 成品目录清单

路径相对于数据根下的 `Processed_Data/`。先完成表中前 6 项，再完成后 7 项。每项移动整个 ROI 目录，保留 `Optical/`、`SAR/` 和存在的 `Label/`。

| 原目录 | 目标目录 |
|---|---|
| `Val/ROI_035` | `Test/ROI_035` |
| `Val/ROI_049` | `Test/ROI_049` |
| `Val/ROI_070` | `Test/ROI_070` |
| `Val/ROI_071` | `Test/ROI_071` |
| `Val/ROI_075` | `Test/ROI_075` |
| `Val/ROI_080` | `Test/ROI_080` |
| `Train/ROI_001` | `Val/ROI_001` |
| `Train/ROI_009` | `Val/ROI_009` |
| `Train/ROI_018` | `Val/ROI_018` |
| `Train/ROI_050` | `Val/ROI_050` |
| `Train/ROI_055` | `Val/ROI_055` |
| `Train/ROI_067` | `Val/ROI_067` |
| `Train/ROI_078` | `Val/ROI_078` |

迁移前检查各源目录存在、各目标目录空缺。若源成品仍有 9,862 对，先应用 [ROI_017 文件补丁](patch-roi-017.md) 派生迁移基线。迁移后按元数据核对 67 个 ROI 各位于一个划分，每个 ROI 的光学和 SAR patch 文件名一一对应，ROI_017 保留 195 对和原编号缺口。

| 划分 | ROI | Patch 对 | 带评测真值点的 patch 对 |
|---|---:|---:|---:|
| Train | 47 | 6,909 | 0 |
| Val | 7 | 980 | 0 |
| Test | 13 | 1,955 | 1,605 |
| 合计 | 67 | 9,844 | 1,605 |

## 数据盘验收

Sandcastle 所挂载的数据根下的 `Processed_Data/` 已切换到当前划分。原树有 9,862 对，保存在同级的 `Processed_Data-9862/`。切换前用同卷硬链接准备了应用 ROI_017 剔除的成品树，再按清单移动整目录。

已核对全部 67 个 ROI 的唯一归属、每个 ROI 的光学和 SAR 文件名、ROI_017 原编号缺口和表中数量。测试集的 1,605 个 `.txt` 标签与仓库内文件逐字节一致，同名 `.prj` 随目录保留。其他部署的数据根需分别按清单切换和核对。

## 复现旧划分

在独立 Git 工作树检出 `0388796` 可读到旧元数据、评测真值点路径、站点和分析脚本。需要配套的 9,844 对旧成品目录时，在独立的成品树中按上表逆向移动两组目录。先将后 7 项从 `Val/` 移回 `Train/`，再将前 6 项从 `Test/` 移回 `Val/`。复现标注质量时将旧成品所在的数据根传给历史脚本。

当前站点的历史难度表从 `docs/assets/difficulty-roi-splits.json` 读取旧归属。该表来自 `0388796` 的 `research/sample-difficulty/patch-positions.csv`，仅用于历史图表。

输入表示常数的历史重算使用剔除前的 9,862 对成品。如需在本机复现，把历史 `research/preprocess-constants/recompute.py` 的输入目录指向保留的 `Processed_Data-9862/`。
