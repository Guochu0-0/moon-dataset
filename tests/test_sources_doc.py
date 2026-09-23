"""来源文档页的几条硬约束（issue #7 的验收标准）。

这些约束一旦被破坏，渲染不会报任何错：少一个来源标注、把一句解释性论断写进分辨率一节、
把那条已被推翻的错位归因抄回来——都只会在几个月后误导读者。所以用测试守住。
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "docs" / "sources.qmd"
TAG = re.compile(r"\[(官方|实测|推断)")
FENCED_BLOCK = re.compile(r"^```.*?^```", re.S | re.M)


@pytest.fixture(scope="module")
def text() -> str:
    return PAGE.read_text(encoding="utf-8")


def sections(text: str, level: str) -> dict[str, str]:
    """`level` 为 "##" 或 "###"；返回 标题 → 正文（到下一个同级或更高级标题为止）。"""
    body = FENCED_BLOCK.sub("", text)
    heading = re.compile(rf"^(#{{2,{len(level)}}}) (.+)$", re.M)
    found, marks = {}, list(heading.finditer(body))
    for mark, following in zip(marks, marks[1:] + [None]):
        if mark[1] == level:
            end = following.start() if following else len(body)
            found[mark[2].strip()] = body[mark.end() : end]
    return found


def test_every_fact_section_says_where_it_comes_from(text: str) -> None:
    """每个 ### 小节至少带一个「官方 / 实测 / 推断」标注。"""
    untagged = [title for title, body in sections(text, "###").items() if not TAG.search(body)]
    assert untagged == []


def test_the_page_explains_the_three_tags(text: str) -> None:
    for tag in ("**[官方]**", "**[实测]**", "**[推断]**"):
        assert tag in text


def test_the_lat_ts_warning_comes_before_any_section(text: str) -> None:
    """醒目：读者还没往下翻，就先看到这条。"""
    warning = text.find(".callout-warning")
    first_section = re.search(r"^## ", text, re.M)
    assert 0 <= warning < first_section.start()
    callout = text[warning : text.find("\n:::\n", warning)]
    assert "lat_ts" in callout
    assert "读取时" in callout
    for tile in ("E215", "E218", "E219", "I219", "I236"):
        assert tile in callout


def test_the_overturned_misalignment_attribution_is_not_inherited(text: str) -> None:
    """地形 / 高程只允许出现在「这条结论已被推翻」的那句话里。"""
    for line in text.splitlines():
        if re.search(r"地形|高程|DEM", line):
            assert "推翻" in line, line


def test_resolution_section_states_numbers_without_explaining_them(text: str) -> None:
    [body] = [b for t, b in sections(text, "##").items() if "分辨率" in t]
    assert "`{python}" in body
    for word in ("因为", "由于", "导致", "说明了", "意味着", "原因是"):
        assert word not in body, word


def test_the_page_is_in_the_navigation() -> None:
    """导航栏与侧边栏各一处；占位的「尚未产出」要一并去掉。"""
    config = (REPO / "_quarto.yml").read_text(encoding="utf-8")
    assert len(re.findall(r"^\s*- href: docs/sources\.qmd$", config, re.M)) == 2
    assert "issue #7" not in config
