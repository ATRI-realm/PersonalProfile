"""硬约束判定与**独立**求值器。

这里的求值器只依据标准运算符优先级解析**题面文本**，
不读取表达式树的任何结构信息。它既是回读校验（round-trip）的执行者，
也是整个项目对"括号与优先级有没有拼错"的结构性保障。

生成逻辑与校验逻辑互相独立，任何一方写错都会被另一方发现。
"""

from __future__ import annotations

from typing import Any

from .config import Config, OP_PRECEDENCE, mul_bounds
from .model import Problem


class InvalidExpression(ValueError):
    """文本不是合法的整数算式（解析失败、除零、不整除等）。"""


_SYMBOL_ALIASES: dict[str, str] = {
    "×": "*",
    "⋅": "*",
    "·": "*",
    "÷": "/",
    "−": "-",
    "–": "-",
    "—": "-",
    "＋": "+",
    "－": "-",
}

_ALLOWED = set("+-*/()")


def _lex(text: str) -> list[tuple[str, int]]:
    """把文本切成 ``(kind, payload)`` 序列，``kind`` 为 ``num`` 或 ``op``。"""
    tokens: list[tuple[str, int]] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char.isdigit():
            end = index
            while end < length and text[end].isdigit():
                end += 1
            tokens.append(("num", int(text[index:end])))
            index = end
            continue
        normalized = _SYMBOL_ALIASES.get(char, char)
        if normalized in _ALLOWED:
            tokens.append(("op", ord(normalized)))
            index += 1
            continue
        raise InvalidExpression(f"出现无法识别的字符 {char!r}")
    if not tokens:
        raise InvalidExpression("算式为空")
    return tokens


class _Parser:
    """递归下降解析器：expr := term (('+'|'-') term)* ；term := factor (('*'|'/') factor)*。"""

    def __init__(self, tokens: list[tuple[str, int]]) -> None:
        self._tokens = tokens
        self._pos = 0
        self.values: list[int] = []
        self.operations: list[tuple[str, int, int]] = []

    def parse(self) -> int:
        value = self._expr()
        if self._pos != len(self._tokens):
            raise InvalidExpression("算式在应有结尾处仍有剩余内容，括号可能不配对")
        return value

    def _peek_op(self) -> str | None:
        if self._pos < len(self._tokens):
            kind, payload = self._tokens[self._pos]
            if kind == "op":
                return chr(payload)
        return None

    def _take(self) -> tuple[str, int]:
        if self._pos >= len(self._tokens):
            raise InvalidExpression("算式意外结束")
        token = self._tokens[self._pos]
        self._pos += 1
        return token

    def _expr(self) -> int:
        value = self._term()
        while self._peek_op() in ("+", "-"):
            op = chr(self._take()[1])
            right = self._term()
            self.operations.append((op, value, right))
            value = value + right if op == "+" else value - right
            self.values.append(value)
        return value

    def _term(self) -> int:
        value = self._factor()
        while self._peek_op() in ("*", "/"):
            op = chr(self._take()[1])
            right = self._factor()
            self.operations.append((op, value, right))
            if op == "*":
                value = value * right
            else:
                if right == 0:
                    raise InvalidExpression("除数为 0")
                if value % right:
                    raise InvalidExpression(f"{value} ÷ {right} 不能整除")
                value //= right
            self.values.append(value)
        return value

    def _factor(self) -> int:
        kind, payload = self._take()
        if kind == "num":
            self.values.append(payload)
            return payload
        char = chr(payload)
        if char == "(":
            value = self._expr()
            kind, payload = self._take()
            if kind != "op" or chr(payload) != ")":
                raise InvalidExpression("左括号没有对应的右括号")
            return value
        raise InvalidExpression(f"不应出现的符号 {char!r}")


def eval_text(
    text: str, *, operations: list[tuple[str, int, int]] | None = None
) -> tuple[int, list[int]]:
    """按标准优先级求值题面文本。

    返回 ``(最终值, 全部数值)``，其中"全部数值"包含每个字面量与每一步中间结果，
    传入 ``operations`` 时另记录每步的运算符和左右操作数，用于检查实际乘法因子。
    供调用方做范围检查。任何非法情形（解析失败、除零、不整除）抛
    ``InvalidExpression``。
    """
    parser = _Parser(_lex(text))
    value = parser.parse()
    if operations is not None:
        operations.extend(parser.operations)
    return value, parser.values


def validate_problem(problem: Problem, cfg: Config) -> list[str]:
    """逐条核对硬约束，返回违规说明列表（空列表表示全部通过）。"""
    errors: list[str] = []
    root = problem.root

    count = root.operator_count()
    if count not in (1, 2):
        errors.append(f"运算符个数为 {count}，要求 1 或 2")

    for node in root.iter_nodes():
        if not isinstance(node.value, int) or isinstance(node.value, bool):
            errors.append(f"出现非整数数值 {node.value!r}")
            continue
        if node.value < 0:
            errors.append(f"出现负数 {node.value}")
        if node.value > cfg.max_result:
            errors.append(f"数值 {node.value} 超过上界 {cfg.max_result}")
        if not node.is_leaf and node.op not in OP_PRECEDENCE:
            errors.append(f"出现未知运算符 {node.op!r}")

    for leaf in root.leaves():
        if leaf < cfg.min_value or leaf > cfg.max_value:
            errors.append(f"叶子操作数 {leaf} 不在 [{cfg.min_value}, {cfg.max_value}] 内")

    for node in root.iter_operators():
        left, right = node.left, node.right
        if left is None or right is None:
            errors.append(f"运算符 {node.op!r} 缺少操作数")
            continue
        if node.op == "/":
            if right.value == 0:
                errors.append("出现除数为 0 的除法")
            elif left.value % right.value:
                errors.append(f"{left.value} ÷ {right.value} 不能整除")
        if node.op == "*":
            mul_low, mul_high = mul_bounds(cfg)
            for operand in (left.value, right.value):
                if not mul_low <= operand <= mul_high:
                    errors.append(
                        f"乘法操作数 {operand} 不在九九表区间 [{mul_low}, {mul_high}] 内"
                    )

    try:
        operations: list[tuple[str, int, int]] = []
        value, values = eval_text(problem.text, operations=operations)
    except InvalidExpression as exc:
        errors.append(f"题面无法解析：{exc}")
    else:
        if value != problem.answer:
            errors.append(f"回读校验不符：题面算得 {value}，记录答案为 {problem.answer}")
        if value != root.value:
            errors.append(f"回读校验不符：题面算得 {value}，表达式树为 {root.value}")
        for item in values:
            if item < 0:
                errors.append(f"题面求值过程中出现负数 {item}")
            if item > cfg.max_result:
                errors.append(f"题面求值过程中出现 {item}，超过上界 {cfg.max_result}")
        mul_low, mul_high = mul_bounds(cfg)
        for op, left, right in operations:
            if op == "*" and not all(mul_low <= x <= mul_high for x in (left, right)):
                errors.append(f"题面实际乘法 {left} × {right} 超出九九表区间 [{mul_low}, {mul_high}]")

    if not cfg.allow_zero_result and problem.answer == 0:
        errors.append("结果为 0，但配置要求不允许")

    return errors
