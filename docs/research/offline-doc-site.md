# 本地双击打开的文档站：方案调研

对应 issue #14。调研日期 2026-09-23。

## 使用场景与约束

- 读者克隆仓库后双击 HTML 阅读，地址栏是 `file://`；不联网，不装任何工具链。
- 需要：离线全文搜索（中文可用）；光学/SAR 图像展示；ROI 总表 → 约 67 个 ROI 详情页。
- 现状：Quarto 网站 + 后处理脚本 `src/moondata/docsite.py`。ROI 页由 `moondata pages`（`src/moondata/roipages.py`）从元数据 CSV、统计快照、缩略图清单、已知问题 TOML 生成 Markdown；缩略图 135 张共 4.7 MB（`docs/rois/thumbnails/`），构建产物 `_site/` 约 12 MB 并随仓库提交。

## file:// 下的两条浏览器限制

所有候选能否工作，基本取决于它们是否踩到这两条：

1. **`fetch()` / XHR 取本地文件被拒。** 浏览器通常把 `file:///` 下的文档视为不透明源（opaque origin），同目录的文件之间也会触发 CORS 错误 [MDN-SOP]。Material for MkDocs 文档给出的报错是 `Cross origin requests are only supported for protocol schemes: http, [...]` [MKM-offline]。
2. **`<script type="module">` 被拒。** 模块脚本按 CORS 规则加载，用 `file://` 打开会遇到 CORS 错误 [MDN-modules]。

普通 `<script src>`（经典脚本）不受这两条限制。因此在 file:// 下搜索能工作的前提是：索引以 `.js` 文件形式由 `<script src>` 加载，页面不依赖 ES module，也不依赖运行时 fetch。

## Quarto 的现状（基线）

- Quarto 的站内搜索在运行时 `fetch(offsetURL("search.json"))`；检测到 `window.location.protocol === "file:"` 时直接提示 "Search requires JavaScript features disabled when running in file://... URLs" 并放弃搜索 [Q-search-js]。Quarto 官方搜索文档没有离线/file:// 的说明 [Q-search]。
- `quarto.js` 以 `type="module"` 加载，file:// 下被拒，页内目录高亮等功能丢失（见 `docsite.py` 模块说明）。
- 本仓库的 `docsite.py` 做了两处修补：把 `search.json` 内嵌进 `quarto-search.js`、绕过 file:// 判断；把 `tabsets.js` 内联进 `quarto.js` 并去掉 `type="module"`。修补依赖 Quarto 产物里的若干字面锚点，Quarto 升级改动这些代码时，脚本会在构建期报错（设计如此），需要人工对照新版调整。
- 中文搜索：Quarto 用 Fuse.js，`ignoreLocation: true`、`minMatchCharLength: 2` [Q-search-js]。字符级近似匹配，中文子串可命中，单字查询无结果（见 `docsite.py` 说明）。
- 图片：Quarto 内置 lightbox（`lightbox: true` / `auto`，基于 GLightbox）[Q-lightbox]；仓库已设 `resources-from-cdn: false`，JS/CSS 均拷进 `site_libs/`。
- ROI 表与详情页：Quarto 的 listing 可以从 YAML 文件取条目并以 `type: table` 展示，但不提供“一行数据生成一页”的功能 [Q-listings]；现有做法是 `pre-render` 调用 `moondata pages` 生成 Markdown。
- 当前版本 v1.10.18（2026-07-24）[Q-rel]。

## 候选方案

### MkDocs + Material 主题 + 官方 offline 插件

- **file:// 搜索**：offline 插件把搜索索引写成 JS 文件（源码里是 `search/search_index.js`，内容为 `var __index = {...}`），并借助 iframe-worker shim 在 file:// 下运行搜索 worker；同时强制关闭 `use_directory_urls`，使链接指向 `xxx.html` [MKM-offline] [MKM-offline-src]。依赖 fetch 的功能必须关闭：instant loading、站点统计、版本切换、评论系统 [MKM-offline]。
- **需要注意的离线缺口**：offline 插件把 iframe-worker shim 登记为 `https://unpkg.com/iframe-worker/shim`，即默认从 CDN 取 [MKM-offline-src]。完全不联网时，须同时启用 privacy 插件（9.5.0 起内置），它在构建期把外部脚本、样式、字体下载到站点目录并改写引用 [MKM-privacy]。主题默认从 Google Fonts 取字体，也要靠 privacy 插件或关闭字体配置解决。这一点需要原型实测确认 shim 确被本地化。
- **中文搜索**：Material 的搜索基于 lunr（按词建索引）。中文分词在构建期由 jieba 完成，jieba 是可选依赖，只在 `import jieba` 成功时才对标题与正文切词 [MKM-search] [MKM-search-src]；未安装时中文段落不切分，基本无法按词命中。切词后查询需与 jieba 的切分结果对齐，任意子串（跨词边界）能否命中需原型实测。
- **图片**：Markdown 图片原样拷贝。大图预览需第三方插件（如 mkdocs-glightbox，未核查其离线行为）。optimize 插件（9.7.0 起内置）可在构建期压缩 PNG/JPEG，依赖 Pillow、pngquant 等 [MKM-optimize]。
- **ROI 页生成**：可继续用 `moondata pages` 预生成 Markdown，或用 mkdocs-gen-files 在构建期运行 Python 脚本生成页面 [gen-files]。
- **维护状态**：Material 团队 2025-11-05 宣布 Material for MkDocs 进入维护模式，承诺至少 12 个月内修复关键缺陷与安全问题；同文称 MkDocs 本体自 2024-08 起无人维护，应视为供应链风险 [MKM-zensical]。PyPI 上 mkdocs 最新为 1.6.1，mkdocs-material 为 9.7.7。mkdocs-gen-files 的 README 现已改为面向 MkDocs 的分支 ProperDocs [gen-files]，生态在分裂。
- **后继者 Zensical**：同一团队的新生成器，兼容 `mkdocs.yml`，也有 offline 插件（同样默认从 unpkg 取 iframe-worker，可在 `extra.polyfills` 中改为本地文件）[ZS-offline]；但其搜索文档写明“Search is currently only available in English”、不使用 lunr 管线，未提中文支持 [ZS-search]。PyPI 版本 0.0.64（2026-09-22），仍处 0.x。

### mdBook

- **file:// 搜索**：可用。搜索脚本在打开搜索框时动态插入 `<script src=".../searchindex.js">` 加载索引，不走 fetch [mdBook-searcher]。
- **中文搜索**：不可用。使用 elasticlunr，按空白切词；issue #1081、#2052（“Support CJK search”）仍开放，维护者在 #2699 中回复“I don't believe chinese search is supported” [mdBook-2052] [mdBook-2699]。
- **ROI 页**：`SUMMARY.md` 必须列出每一章 [mdBook-summary]，67 页需由脚本生成该文件。
- 结论：搜索中文这一项不满足，不作为候选。

### Sphinx（+ MyST 解析 Markdown）

- **file:// 搜索**：索引通过插入 `<script>` 加载 `searchindex.js`（`Search.loadIndex`），可在 file:// 下工作；但结果摘要通过 `fetch(requestUrl)` 取页面原文，file:// 下这一步失败，结果列表只有标题没有摘要 [Sphinx-searchtools]。
- **中文搜索**：`sphinx/search/zh.py` 依赖 jieba；未安装 jieba 时 `cut_for_search` 返回空，中文文本不进入索引 [Sphinx-zh]。安装 jieba 后按词匹配。
- 需要 Sphinx + MyST + jieba + 主题，配置量比 MkDocs 大；现有 Markdown 需适配 MyST 语法。在本场景下没有相对 MkDocs 的明显优势，列为备选，不建议原型。

### VitePress

- 官方部署文档（main 分支，对应 2.0.0-alpha.20 引入的相对 base `./`）写明：file:// 下页面可作为带样式、可导航的静态站阅读，但浏览器阻止 JS 模块，没有 hydration，**搜索等交互功能不可用** [VP-deploy] [VP-changelog]。
- 结论：不满足离线搜索，排除。

### Docusaurus

- 默认构建须由服务器提供。3.x 提供实验性 `future.experimental_router: 'hash'`，官方说明其用途之一是打成 `.zip` 本地浏览 [DS-config] [DS-3825]。
- 官方搜索方案是 Algolia（在线）；本地搜索依赖第三方插件，未核查其 file:// 行为。整体依赖 Node 工具链与 React 客户端路由，维护成本在所有候选中最高。
- 结论：排除。

### 手写静态页（Python 生成多页 HTML）

- 做法：沿用 `moondata pages` 的数据读取，直接输出 HTML（模板 + 少量 CSS/JS），不经过站点生成器。
- **file:// 搜索**：构建时把全文索引写成 `search-index.js`（`window.SEARCH = [...]`），各页用 `<script src>` 加载；查询用简单子串匹配或 bigram。中文按字符匹配即可，无需分词。条件是全部使用经典脚本、不用 fetch、不用 ES module（见上文两条浏览器限制）。
- **图片**：`<img loading="lazy">` 显示缩略图，点击 `<a href>` 打开原图；可选一个本地拷贝的 lightbox 库。
- **ROI 页**：总表与详情页均由现有生成器输出，天然从 CSV 批量生成。
- **成本**：没有第三方构建工具，也没有需要随上游升级而修补的锚点；代价是导航、页内目录、响应式布局、Markdown 渲染需自行实现或引入一个 Python Markdown 库（如 `markdown`）。

### 单页 HTML

- 做法：所有内容（含 67 个 ROI 小节）放进一个 `.html`，图片外链到同目录。
- **搜索**：浏览器 Ctrl+F，中文完全可用，无需任何脚本；也可加一个页内过滤框。
- **图片**：不宜用 base64 内嵌（体积膨胀约 1/3，且整页一次性加载）；外链图片配合 `loading="lazy"`。
- **ROI 页**：总表链接到页内锚点 `#ROI_001`；由生成器批量输出。
- **局限**：内容增长后单页变长，术语表、来源文档、流程文档、产物文档与 ROI 档案都挤在一页，导航依赖侧栏锚点。适合作为 ROI 档案的附加视图，或整站内容量较小时使用。

### 其他未采用的方向

- Pagefind 等基于 WebAssembly、按需 fetch 索引分片的搜索库：加载机制依赖 fetch，按上文限制推断在 file:// 下不可用（未实测，未找到官方表述）。

## 对比表

| 方案 | file:// 离线搜索 | 中文搜索 | 大图展示 | ROI 总表 → 详情页 | 构建依赖 | 需额外修补 | 维护风险 |
|:---|:---|:---|:---|:---|:---|:---|:---|
| Quarto（现状） | 开箱不可用；经 `docsite.py` 修补后可用 | 可用（Fuse.js 字符级，≥2 字） | 内置 lightbox（GLightbox） | 表可用 listing/Markdown；详情页靠 `moondata pages` 预生成 | Quarto CLI（含 Pandoc、Dart Sass）+ Python | 是：内嵌索引、去 module，锚点随 Quarto 升级可能失效 | 中：修补脚本与 Quarto 内部实现耦合 |
| MkDocs + Material + offline | 官方支持（索引转 JS + iframe-worker） | 需装 jieba，构建期分词；子串命中待实测 | 原样拷贝；lightbox 需第三方插件；optimize 插件可压缩 | 预生成 Markdown 或 mkdocs-gen-files | Python：mkdocs、mkdocs-material、jieba（+ privacy 插件） | 否，但须启用 privacy 插件使 iframe-worker shim 本地化（待验证） | 高：Material 维护模式，MkDocs 本体无人维护 |
| Zensical | 官方支持（同上机制） | 文档称搜索仅支持英文 | 同 Material | 同 Material | Python（Rust 内核） | 同上 | 高：0.x 版本 |
| mdBook | 支持（`<script>` 加载索引） | 不支持（#2052 未解决） | 原样拷贝 | SUMMARY.md 须逐页列出 | 单个 Rust 二进制 | 否 | 低，但功能不满足 |
| Sphinx + MyST | 索引可用，结果摘要 fetch 失败 | 需装 jieba，否则中文不入索引 | 原样拷贝 | 预生成 + toctree glob | Python：sphinx、myst-parser、jieba、主题 | 摘要缺失需修补或接受 | 中 |
| VitePress | 不可用（官方说明） | — | — | — | Node | — | 排除 |
| Docusaurus | 仅 hash router 实验特性；本地搜索靠第三方 | 未核查 | — | — | Node + React | 很可能需要 | 排除 |
| 手写多页静态页 | 自行实现，`<script src>` 加载 JS 索引 | 子串匹配，天然可用 | 缩略图 + 原图链接，可选 lightbox | 直接由现有生成器输出 | 仅 Python（可选 `markdown` 库） | 否 | 低；自维护代码量增加 |
| 单页 HTML | Ctrl+F | 可用 | 外链 + lazy 加载 | 页内锚点 | 仅 Python | 否 | 低；内容多时可读性下降 |

## 关于大图

各方案对图片的处理差别不大，差别在于仓库体积与加载方式：

- 页面内展示缩略图（现有 135 张共 4.7 MB），原始尺寸图单独存放、通过链接打开；多 MB 的图不直接嵌在正文里，也不 base64 内嵌。
- 构建产物随仓库提交，大图会进入 git 历史。GitHub 对超过 50 MiB 的文件告警、超过 100 MiB 的文件拒收 [GH-large]。数 MB 的图数量多时，应评估是否只提交缩略图或降采样版本，原图留在数据盘。
- 本地图片通过 `<img>` 与 `<a href>` 加载，不受 file:// 的 fetch 限制；lightbox 类库只要是经典脚本且随站点分发，同样可用。

## 建议原型的形式

1. **Quarto 现状加固**：保留现有站点，开启 `lightbox`，在 Chrome/Edge/Firefox 下以 file:// 实测搜索与 lightbox；统计 Quarto 近几次升级中 `docsite.py` 锚点是否失效，以评估长期修补成本。作为对照基线。
2. **手写多页静态页**：复用 `roipages.py` 的数据层，输出 HTML 与 `search-index.js`，子串搜索。重点评估：导航/页内目录的实现量；与现有 Markdown 文档（术语表、来源文档、产物文档）的衔接方式。这是唯一不依赖第三方生成器内部实现、中文搜索无需分词的方案。
3. **MkDocs + Material + offline + privacy + jieba**：验证完全断网下搜索是否可用（iframe-worker 是否本地化）、中文子串与跨词查询的命中情况。鉴于 Material 已进入维护模式，原型结论即使正面，也应把迁移到 Zensical 或其他工具的可能性计入成本。

单页 HTML 可在方案 2 中顺带产出（同一生成器多一个输出模板），用于 ROI 档案的整页浏览与 Ctrl+F，不单独立项。

## 来源

- [MDN-SOP] MDN, Same-origin policy — File origins. https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Same-origin_policy
- [MDN-modules] MDN, JavaScript modules（关于 `file://` 的说明）. https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules
- [Q-search] Quarto, Website Search. https://quarto.org/docs/websites/website-search.html
- [Q-search-js] quarto-cli 源码 `src/resources/projects/website/search/quarto-search.js`（file:// 判断、`fetch(offsetURL("search.json"))`、Fuse 选项）. https://github.com/quarto-dev/quarto-cli/blob/main/src/resources/projects/website/search/quarto-search.js
- [Q-lightbox] Quarto, Lightbox Figures. https://quarto.org/docs/output-formats/html-lightbox-figures.html
- [Q-listings] Quarto, Website Listings. https://quarto.org/docs/websites/website-listings.html
- [Q-rel] quarto-cli releases, v1.10.18. https://github.com/quarto-dev/quarto-cli/releases
- [MKM-offline] Material for MkDocs, Built-in offline plugin. https://squidfunk.github.io/mkdocs-material/plugins/offline/
- [MKM-offline-src] mkdocs-material 源码 `material/plugins/offline/plugin.py`（`use_directory_urls = False`、`https://unpkg.com/iframe-worker/shim`、`search_index.js`）. https://github.com/squidfunk/mkdocs-material/blob/master/material/plugins/offline/plugin.py
- [MKM-privacy] Material for MkDocs, Built-in privacy plugin. https://squidfunk.github.io/mkdocs-material/plugins/privacy/
- [MKM-optimize] Material for MkDocs, Built-in optimize plugin. https://squidfunk.github.io/mkdocs-material/plugins/optimize/
- [MKM-search] Material for MkDocs, Built-in search plugin — Segmentation. https://squidfunk.github.io/mkdocs-material/plugins/search/
- [MKM-search-src] mkdocs-material 源码 `material/plugins/search/plugin.py`（`try: import jieba` / `if jieba:`）. https://github.com/squidfunk/mkdocs-material/blob/master/material/plugins/search/plugin.py
- [MKM-zensical] Material for MkDocs 博客, 2025-11-05 “Zensical”. https://squidfunk.github.io/mkdocs-material/blog/2025/11/05/zensical/
- [ZS-offline] Zensical, Offline usage. https://zensical.org/docs/setup/offline/
- [ZS-search] Zensical, Site search. https://zensical.org/docs/setup/search/
- [gen-files] mkdocs-gen-files README. https://github.com/oprypin/mkdocs-gen-files
- [mdBook-searcher] mdBook 源码 `crates/mdbook-html/front-end/searcher/searcher.js`（`loadSearchScript` 插入 `<script>`）. https://github.com/rust-lang/mdBook/blob/master/crates/mdbook-html/front-end/searcher/searcher.js
- [mdBook-2052] rust-lang/mdBook#2052, Support CJK (multiple language) search（另见 #1081）. https://github.com/rust-lang/mdBook/issues/2052
- [mdBook-2699] rust-lang/mdBook#2699, 如何才能支持中文搜索. https://github.com/rust-lang/mdBook/issues/2699
- [mdBook-summary] mdBook guide, SUMMARY.md. https://rust-lang.github.io/mdBook/format/summary.html
- [Sphinx-searchtools] Sphinx 源码 `sphinx/themes/basic/static/searchtools.js`（`loadIndex` 与摘要 `fetch`）. https://github.com/sphinx-doc/sphinx/blob/master/sphinx/themes/basic/static/searchtools.js
- [Sphinx-zh] Sphinx 源码 `sphinx/search/zh.py`（jieba 缺失时 `cut_for_search` 为空）. https://github.com/sphinx-doc/sphinx/blob/master/sphinx/search/zh.py
- [VP-deploy] VitePress, Deploy — Relocatable Builds (Relative Base). https://github.com/vuejs/vitepress/blob/main/docs/en/guide/deploy.md
- [VP-changelog] VitePress CHANGELOG, 2.0.0-alpha.20（relative base `./`）. https://github.com/vuejs/vitepress/blob/main/CHANGELOG.md
- [DS-config] Docusaurus, docusaurus.config.js — `future.experimental_router`. https://docusaurus.io/docs/api/docusaurus-config
- [DS-3825] facebook/docusaurus#3825, Option to generate offline static HTML files usable without server. https://github.com/facebook/docusaurus/issues/3825
- [GH-large] GitHub Docs, About large files on GitHub. https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github
