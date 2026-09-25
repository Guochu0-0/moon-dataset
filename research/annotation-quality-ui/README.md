# PROTOTYPE：「标注质量」页的 UI

原型，用完即弃，不合入 main。回答「原型：『标注质量』页的讲法与版式」（#49，地图 #34）。

正文只读 `research/annotation-quality-text/text.md`（「对话：『标注质量』页写什么、怎么组织、怎么措辞」#51 的定稿），
一字不改；四个变体只改顺序、分栏与显隐。`?variant=A|B|C|D` 切换（底部黑色切换条或键盘 ← →）。

| 变体 | 布局 | 三种方法怎样并列 | 图与正文 |
|---|---|---|---|
| A 线性长文 | 定稿原样：引言 → 误差模型 → 三法依次 → 估计结果 | 末尾汇总表 | 图在占位处，随文 |
| B 结果前置，图在右栏 | 引言 → 估计结果 → 误差模型 → 三法；宽版 | 汇总数轴图 + 表放在前面 | 每种方法正文在左，它的图在右栏（sticky） |
| C 三法并排对照 | 三法排成三列，例子 / 原理 / 计算 / 结果 / 出处逐行对齐；宽版 | 网格本身 + 末尾汇总表 | 图在各自格子里 |
| D 概览卡片 + 分方法详情 | 概览：引言、误差模型、三张方法卡、估计结果；点卡片进该方法的详情（`#m1`…`#m3`），可前后翻 | 卡片（摘句 + 数）+ 数轴图 + 表 | 概览卡片放缩略图；详情随文 |

切换条右侧的「位置」按钮把侧栏里的「标注质量」挪到「配对特征」或「使用建议」之后（`?pos=usage`）。

汇总数轴图（`summary-axis`）不在定稿里，是 B、D 给「三法怎样并列比较」加的图形方案。
截图：`figs/page-{A,B,C,D}.preview.png`、`figs/page-D-detail.preview.png`。

## 运行

```sh
PYTHONPATH=src conda run -n moon-dataset python research/annotation-quality-ui/figures.py
PYTHONPATH=src conda run -n moon-dataset python research/annotation-quality-ui/build.py
```

然后双击 `research/annotation-quality-ui/_site/data/annotation-quality.html`。

- `figures.py` 读本目录的 `summary.json`（拷自 `research/ground-truth-residuals`）、`pairs.csv`（拷自
  `research/annotation-repeat`）与数据盘（环境变量 `MOON_DATA`，默认 `G:/Lunar_Optical_SAR_Registration_Dataset`）。
- 生成器临时加了 `md_in_html` 扩展（正文里的 `<details>` 要用）；正式页若保留可折叠的例子，生成器要加上它。
