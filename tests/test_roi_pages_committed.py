"""已提交的 ROI 档案页必须就是生成器此刻的输出。

档案页是生成物，却随仓库提交（克隆后双击就能读）。改了元数据表、重扫了快照、
补了一条已知问题，却忘了重新生成——页面不会报错，只会悄悄过期。这条测试守住它。
只读仓库里的文件，不需要数据盘。
"""

from pathlib import Path

from moondata.config import ROI_PAGES_RELDIR
from moondata.roipages import load_inputs, render_pages

REPO = Path(__file__).resolve().parents[1]


def test_committed_pages_match_the_generator() -> None:
    expected = render_pages(load_inputs(REPO))
    directory = REPO / ROI_PAGES_RELDIR
    on_disk = {p.name for p in directory.glob("*.md")}
    assert on_disk == set(expected), "页面集合对不上，跑一次 `moondata pages`"
    stale = [
        name for name, text in expected.items()
        if (directory / name).read_bytes() != text.encode("utf-8")
    ]
    assert stale == [], f"这些页面过期了，跑一次 `moondata pages`：{stale}"


def test_every_thumbnail_the_pages_use_is_committed() -> None:
    directory = REPO / ROI_PAGES_RELDIR
    for page in directory.glob("ROI_*.md"):
        for line in page.read_text(encoding="utf-8").splitlines():
            if "](thumbnails/" in line:
                target = line.split("](", 1)[1].split(")", 1)[0]
                assert (directory / target).is_file(), f"{page.name} 引用的 {target} 不存在"
