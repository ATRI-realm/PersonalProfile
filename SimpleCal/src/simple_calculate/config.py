"""生成参数与运算符元数据。

本模块不依赖任何其他模块（除标准库），是整条调用链的最底层。
"""

from __future__ import annotations

from dataclasses import dataclass

ALL_OPS: tuple[str, ...] = ("+", "-", "*", "/")

OP_DISPLAY: dict[str, str] = {"+": "+", "-": "−", "*": "×", "/": "÷"}

OP_PRECEDENCE: dict[str, int] = {"+": 1, "-": 1, "*": 2, "/": 2}

PAREN_MODES: tuple[str, ...] = ("none", "necessary", "always")


def mul_bounds(cfg: "Config") -> tuple[int, int]:
    """乘法因子的取值区间。

    九九表约束作用在乘法节点本身——**两个操作数**（叶子或中间结果）
    都必须落在 ``[mul_min, mul_max]`` 内。默认 ``[1, 9]``，即九九表不含 0；
    把 ``mul_min`` 设为 0 才会出现 ``0 × n`` 这类题。

    放在 config 层是为了让生成器与校验器共用同一定义，避免两处边界各写一遍而跑偏。
    """
    return max(cfg.min_value, cfg.mul_min), cfg.mul_max


def divisor_floor(cfg: "Config") -> int:
    """除数的下界：不能为 0，即使 ``min_value`` 允许 0。"""
    return max(1, cfg.min_value)


@dataclass
class Config:
    """一次出题任务的全部参数。

    默认值即"已确认的推荐配置"：
      * 默认 0 不作为操作数或中间结果，但允许作为最终结果
      * 乘法限制在九九表内（``mul_min = 1``、``mul_max = 9``）
      * 结果允许为 0（``allow_zero_result = True``）
      * 括号只出现在必需处（``paren = "necessary"``）
    """

    count: int = 20
    ops: tuple[str, ...] = ALL_OPS
    weights: dict[str, int] | None = None
    operator_counts: tuple[int, ...] = (1, 2)
    ratio: tuple[int, int] = (1, 1)
    min_value: int = 1
    max_value: int = 99
    max_result: int = 100
    mul_min: int = 1
    mul_max: int = 9
    paren: str = "necessary"
    allow_zero_result: bool = True
    exclude_trivial: bool = True
    exclude_zero_forms: bool = True
    allow_repeat: bool = False
    per_line: int = 4
    seed: int | None = None
    attempts_per_problem: int = 300

    def validate_config(self) -> None:
        problems: list[str] = []

        if self.ops == () or any(op not in ALL_OPS for op in self.ops):
            problems.append(f"ops 必须取自 {ALL_OPS}，当前为 {self.ops!r}")
        if self.count < 1:
            problems.append("count 必须 ≥ 1")
        if not self.operator_counts or any(k not in (1, 2) for k in self.operator_counts):
            problems.append(f"operator_counts 只能取 1 或 2，当前为 {self.operator_counts!r}")
        if len(set(self.operator_counts)) != len(self.operator_counts):
            problems.append("operator_counts 不能有重复项")
        if len(self.operator_counts) > 1:
            if len(self.ratio) != len(self.operator_counts):
                problems.append("ratio 的项数必须与 operator_counts 一致")
            elif any(value < 0 for value in self.ratio):
                problems.append("ratio 不能有负数")
            elif sum(self.ratio) == 0:
                problems.append("ratio 不能全为 0")
        if self.min_value < 0:
            problems.append("min_value 不能为负")
        if self.max_value < self.min_value:
            problems.append("max_value 不能小于 min_value")
        if self.max_value > self.max_result:
            problems.append("叶子操作数上界 max_value 不能超过 max_result")
        if self.mul_min < 0 or self.mul_max < self.mul_min:
            problems.append("必须满足 0 ≤ mul_min ≤ mul_max")
        if self.mul_max > self.max_value:
            problems.append("mul_max 不能超过 max_value")
        if self.paren not in PAREN_MODES:
            problems.append(f"paren 必须取自 {PAREN_MODES}，当前为 {self.paren!r}")
        if self.paren == "always" and 2 not in self.operator_counts:
            problems.append("paren='always' 只对双运算符题有意义，operator_counts 需包含 2")
        if self.per_line < 1:
            problems.append("per_line 必须 ≥ 1")
        if self.attempts_per_problem < 1:
            problems.append("attempts_per_problem 必须 ≥ 1")
        if self.weights is not None:
            unknown = [op for op in self.weights if op not in ALL_OPS]
            if unknown:
                problems.append(f"weights 中含未知运算符 {unknown!r}")
            if any(w < 0 for w in self.weights.values()):
                problems.append("weights 不能为负")
            if all(w == 0 for w in self.weights.values()):
                problems.append("weights 不能全为 0")

        if problems:
            raise ValueError("配置有误：" + "；".join(problems))
