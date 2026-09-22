"""产物文档页的「无手写数字」约束。

验收标准是「文档中所有统计数字来自快照行内取值」。这条约束一旦被破坏，不会有任何
渲染错误，只会在几个月后以一个过期的数字出现在论文里——所以用测试守住它。
"""

import re
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[1] / "docs" / "products.qmd"

# 允许出现在正文里的数字：产品名里的、以及 issue 编号
ALLOWED = re.compile(r"CE-2|issue #\d+")

FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
FENCED_BLOCK = re.compile(r"^```.*?^```", re.S | re.M)
INLINE_EXPRESSION = re.compile(r"`\{python\}[^`]*`")
INLINE_CODE = re.compile(r"`([^`]*)`")
LINK_TARGET = re.compile(r"\]\([^)]*\)")


def prose(text: str) -> str:
    """去掉代码块与行内取值之后，剩下的就是手写的部分。"""
    text = FRONT_MATTER.sub("", text)
    text = FENCED_BLOCK.sub("", text)
    text = INLINE_EXPRESSION.sub("", text)
    return LINK_TARGET.sub("]()", text)


def handwritten_numbers(text: str) -> list[str]:
    found = []
    body = prose(text)
    for span in INLINE_CODE.findall(body):
        # 行内代码里的文件名、类型名可以带数字，但一个裸数字写进反引号里仍然是手写
        if re.fullmatch(r"[\d,.\s%+-]+", span) and re.search(r"\d", span):
            found.append(span)
    body = ALLOWED.sub("", INLINE_CODE.sub("", body))
    for line in body.splitlines():
        if re.search(r"\d", line):
            found.append(line.strip())
    return found


def test_the_products_page_has_no_handwritten_numbers() -> None:
    assert handwritten_numbers(PAGE.read_text(encoding="utf-8")) == []


def test_the_page_reads_numbers_from_the_snapshot() -> None:
    text = PAGE.read_text(encoding="utf-8")
    assert "load_stats_snapshot()" in text
    assert INLINE_EXPRESSION.search(text)


@pytest.mark.parametrize(
    "line",
    [
        "训练集有 7907 个 patch。",
        "覆盖率约 82%。",
        "共 `1605` 个。",
    ],
)
def test_the_check_catches_a_handwritten_number(line: str) -> None:
    assert handwritten_numbers(f"---\ntitle: x\n---\n\n{line}\n") != []


@pytest.mark.parametrize(
    "line",
    [
        "共 `{python} num(stats['x'])` 个。",
        "文件名是 `patch_<n>.tif`，目录是 `ROI_006`。",
        "见来源文档（issue #7）。CE-2 的光学影像。",
        "```{python}\nx = 512\n```",
    ],
)
def test_the_check_allows_values_from_code(line: str) -> None:
    assert handwritten_numbers(f"---\ntitle: x\n---\n\n{line}\n") == []
