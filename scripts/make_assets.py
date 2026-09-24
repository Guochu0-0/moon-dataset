"""生成文档站素材，输出入库到 `docs/assets/`。需要数据盘与 GDAL。

    python scripts/make_assets.py basemap <lroc_color_poles_4k.tif>   全月底图
    python scripts/make_assets.py samples                             首页样例
    python scripts/make_assets.py facts [ROI_054 ...]                 逐 ROI 事实
    python scripts/make_assets.py overlays [ROI_054 ...]              原始产品叠合图

各组可单独重跑。生成后跑一次 `python scripts/build_site.py` 重建文档站。
"""

from __future__ import annotations

import sys
from pathlib import Path

from moondata import assets
from moondata.config import load_config
from moondata.errors import MoonDataError

USAGE = __doc__.split("\n\n")[1]


def main(argv: list[str]) -> int:
    if not argv:
        print(USAGE, file=sys.stderr)
        return 2
    group, rest = argv[0], argv[1:]
    config = load_config()
    if group == "basemap" and len(rest) == 1:
        assets.make_basemap(config, Path(rest[0]))
    elif group == "samples" and not rest:
        assets.make_samples(config)
    elif group == "facts":
        assets.make_facts(config, rest)
    elif group == "overlays":
        assets.make_overlays(config, rest)
    else:
        print(USAGE, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except MoonDataError as error:
        print(f"错误：{error}", file=sys.stderr)
        sys.exit(1)
