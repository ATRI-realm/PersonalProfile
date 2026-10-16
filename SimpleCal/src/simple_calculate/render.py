"""渲染层：把表达式树转成题面文本。

括号决策完全交给"求值比对"（对应计划书 §3.2 / §3.3）：

1. 先按**最保守**的方式渲染——每个内部节点都加括号。
2. 再逐个尝试去掉某个内部节点的括号，只有同时满足下面条件才确认去掉：
   * 按标准优先级重新求值，结果与设计值相同；
   * 求值过程中**每一步中间结果**也在 ``[0, max_result]`` 内。
   * 按题面实际顺序执行的乘法，其两个因子仍在配置的九九表区间内。

第二条是必需的。反例：``6 × (88 ÷ 11)`` 的值与展开后的 ``6 × 88 ÷ 11`` 相同，
但学生按标准优先级实际要先算出 ``6 × 88 = 528``——虽然最终答案对，
"计算过程"却越界了。只看最终值会漏掉这一类题。

这样括号只可能出现在真正必需的位置，且判定不依赖任何手写的优先级规则表。

本模块同时是"插件式渲染"的落点：后续要加 HTML / PDF 输出，
平行新增函数即可，生成逻辑无需改动。
"""

from __future__ import annotations

import unicodedata
from typing import Iterable

from .config import OP_DISPLAY, Config, mul_bounds
from .model import Node, Problem
from .validate import InvalidExpression, eval_text


def _render(node: Node, droppable: set[int]) -> str:
    if node.is_leaf:
        return str(node.value)
    text = (
        f"{_render(node.left, droppable)} "  # type: ignore[arg-type]
        f"{OP_DISPLAY[node.op]} "  # type: ignore[index]
        f"{_render(node.right, droppable)}"  # type: ignore[arg-type]
    )
    return text if id(node) in droppable else f"({text})"


def plain_text(root: Node) -> str:
    """完全不带括号的写法（仅用于测试与对照，不用于出题）。"""
    return _render(root, {id(node) for node in root.iter_nodes()})


def _is_acceptable(cfg: Config, text: str, target: int) -> bool:
    """去掉括号后结果等价、计算过程不越界，实际乘法因子仍合法。"""
    try:
        operations: list[tuple[str, int, int]] = []
        value, values = eval_text(text, operations=operations)
    except InvalidExpression:
        return False
    if value != target:
        return False
    mul_low, mul_high = mul_bounds(cfg)
    return all(0 <= item <= cfg.max_result for item in values) and all(
        op != "*" or all(mul_low <= x <= mul_high for x in (left, right))
        for op, left, right in operations
    )


def render_expr(root: Node, cfg: Config) -> str:
    """渲染算式本体，只在括号必需处保留括号。"""
    droppable: set[int] = {id(root)}
    for node in root.iter_nodes():
        if node.is_leaf or node is root:
            continue
        trial = droppable | {id(node)}
        if _is_acceptable(cfg, _render(root, trial), root.value):
            droppable = trial
    return _render(root, droppable)


def display_width(text: str) -> int:
    """按终端显示宽度计数：全角/宽字符算 2 列。

    注意 ``×`` ``÷`` ``−`` 属于 Unicode "ambiguous" 区间，
    本项目按单列处理——这与绝大多数等宽字体的实际渲染一致。
    """
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def render_problem(problem: Problem, show_answer: bool = False) -> str:
    body = f"{problem.text} = "
    return body + str(problem.answer) if show_answer else body


def render_sheet(
    problems: Iterable[Problem],
    per_line: int = 4,
    show_answer: bool = False,
    blank_between_rows: bool = True,
    index_start: int = 1,
) -> str:
    """把一批题目排成一份可打印的题面。

    ``show_answer`` 为假时只输出题面（本版默认行为）；答案在 ``Problem`` 里始终保留，
    后续做答案页时打开这个开关即可，生成逻辑不用动。
    """
    cells = [
        f"{index_start + offset:>3}. {render_problem(problem, show_answer)}"
        for offset, problem in enumerate(problems)
    ]
    if not cells:
        return ""
    column_width = max(display_width(cell) for cell in cells) + 3
    lines: list[str] = []
    for start in range(0, len(cells), per_line):
        row = cells[start : start + per_line]
        padded = "".join(cell + " " * (column_width - display_width(cell)) for cell in row)
        lines.append(padded.rstrip())
        if blank_between_rows and start + per_line < len(cells):
            lines.append("")
    return "\n".join(lines)
