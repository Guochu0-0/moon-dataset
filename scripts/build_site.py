"""构建文档站：把 `docs/pages/` 的正文与 `docs/assets/` 的素材渲染到 `_site/`。

    python scripts/build_site.py

只读仓库里的文件，不需要数据盘。`_site/` 整个重写后入库，克隆后双击 `_site/index.html`
即可阅读。素材要更新时先跑 `scripts/make_assets.py`。
"""

from __future__ import annotations

import sys

from moondata.config import REPO_ROOT
from moondata.errors import MoonDataError
from moondata.site import SITE_DIRNAME, build_site, write_site


def main() -> int:
    files = build_site(REPO_ROOT)
    write_site(files, REPO_ROOT / SITE_DIRNAME)
    pages = sum(1 for path in files if path.endswith(".html"))
    print(f"已写出 {REPO_ROOT / SITE_DIRNAME}：{pages} 个页面，共 {len(files)} 个文件")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MoonDataError as error:
        print(f"错误：{error}", file=sys.stderr)
        sys.exit(1)
