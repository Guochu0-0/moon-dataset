# PROTOTYPE：「标注质量」页的讲法与版式

原型，用完即弃，不合入 main。回答「原型：『标注质量』页的讲法与版式」（#49，地图 #34）。

同一页三种写法，`?variant=A|B|C` 切换（页面底部黑色切换条，或键盘 ← →）。变异函数完整写，
仿射拟合残差、无意重标只列提纲。页面临时挂在「数据说明」侧栏「配对特征」之后。

| 变体 | 结构 | 三法怎样比较 | 公式与代码 |
|---|---|---|---|
| A 教科书式 | 一张结论表，三法依次全展开 | 页首结论表 | 全展开，代码约 20 行 |
| B 数轴 + 折叠 | 页首一张数轴图，每法一句思想 + 例图，其余折叠 | 页首数轴图（上界画成灰条，测量画成点） | 折叠在 `<details>` 里 |
| C 对照表 + 标签页 | 四行对照表（看的是 / 假设 / 多算进去的 / 结果），三法放在标签页里 | 对照表 | 只放 3 行核心，完整代码链到脚本 |

不看图的截图：`figs/page-{A,B,C}.preview.png`。

## 运行

```sh
PYTHONPATH=src conda run -n moon-dataset python research/annotation-quality-prototype/figures.py
PYTHONPATH=src conda run -n moon-dataset python research/annotation-quality-prototype/build.py
```

然后双击 `research/annotation-quality-prototype/_site/data/annotation-quality.html`。

- 数字只读 `research/ground-truth-residuals/summary.json`（从研究分支 `research/annotation-repeat` 拷来）。
- `check_fit.py`：numpy 加权最小二乘复现研究分支的 6 个短距离 nugget，逐位一致（环境里没有 scipy）。
- 原型给生成器加了 `md_in_html` 扩展（`<details>`、标签页、图注要用）；正式页若用这些，生成器要加上它。
- 公式用 Unicode 文本写，站点没有 KaTeX。
