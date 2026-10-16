"""基础运算与「两数合法对」的构造。

设计要点（对应计划书 §4.2 / §4.3）：

* 不做"随机试、不合法就重试"的拒绝采样，而是按运算符**直接定出合法区间**，
  因此不存在失败重试，也不会有分布偏斜。
* 一切归约为"两数运算"：双运算符算式只是把内层结果当作一个操作数再算一次。
* 乘法按九九表约定，要求**该乘法节点的两个操作数**都不超过 ``mul_max``
  （中间结果同样受限，否则 ``11 × 9`` 就跑到九九表外面去了）。
"""

from __future__ import annotations

import random
from typing import Sequence, TypeVar

from .config import Config, divisor_floor, mul_bounds

T = TypeVar("T")


class NoSolution(Exception):
    """在给定约束下不存在可用的构造。"""

    def __init__(self, op: str, given: int) -> None:
        super().__init__(f"运算符 {op!r} 在已知操作数为 {given} 时无解")
        self.op = op
        self.given = given


def apply_op(op: str, a: int, b: int) -> int:
    """执行一次二元运算；非法情形（除零、不整除）抛 ``ValueError``。"""
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if b == 0:
            raise ValueError("除数为 0")
        if a % b:
            raise ValueError(f"{a} ÷ {b} 不能整除")
        return a // b
    raise ValueError(f"未知运算符 {op!r}")


def right_candidates(cfg: Config, op: str, left_value: int) -> list[int]:
    """已知**左操作数** ``left_value`` 时，可用作右操作数的叶子值候选集。

    ``left_value`` 可能是中间结果，取值范围 ``[0, max_result]``；
    返回的候选都是叶子，必须落在 ``[min_value, max_value]``。
    """
    low, high, limit = cfg.min_value, cfg.max_value, cfg.max_result

    if op == "+":
        upper = min(high, limit - left_value)
        return list(range(low, upper + 1)) if upper >= low else []

    if op == "-":
        upper = min(high, left_value)
        return list(range(low, upper + 1)) if upper >= low else []

    if op == "*":
        mul_low, mul_high = mul_bounds(cfg)
        if not mul_low <= left_value <= mul_high:
            return []
        if left_value == 0:
            # 0 × y 恒为 0，不可能越界，任何合法因子都行。
            # 只有 mul_min = 0 时 0 才会落进上面的区间，默认九九表下走不到这里；
            # 但这条分支必须留着，否则下面的 limit // left_value 会整数除零。
            return list(range(mul_low, mul_high + 1))
        upper = min(mul_high, limit // left_value)
        return list(range(mul_low, upper + 1)) if upper >= mul_low else []

    if op == "/":
        floor = divisor_floor(cfg)
        if left_value == 0:
            return list(range(floor, high + 1))
        return [y for y in range(floor, high + 1) if left_value % y == 0]

    raise ValueError(f"未知运算符 {op!r}")


def left_candidates(cfg: Config, op: str, right_value: int) -> list[int]:
    """已知**右操作数** ``right_value`` 时，可用作左操作数的叶子值候选集。

    ``right_value`` 可能是中间结果，取值范围 ``[0, max_result]``。
    """
    low, high, limit = cfg.min_value, cfg.max_value, cfg.max_result

    if op == "+":
        upper = min(high, limit - right_value)
        return list(range(low, upper + 1)) if upper >= low else []

    if op == "-":
        lower = max(low, right_value)
        return list(range(lower, high + 1)) if lower <= high else []

    if op == "*":
        mul_low, mul_high = mul_bounds(cfg)
        if not mul_low <= right_value <= mul_high:
            return []
        if right_value == 0:
            # a × 0 恒为 0，同理；见 right_candidates 中的说明。
            return list(range(mul_low, mul_high + 1))
        upper = min(mul_high, limit // right_value)
        return list(range(mul_low, upper + 1)) if upper >= mul_low else []

    if op == "/":
        if right_value == 0:
            return []  # 除数不能为 0，该运算符整体不可行
        # 被除数 a = right_value × q，且 a 本身是叶子，须落在 [min_value, max_value]
        quotient_low = 0 if low == 0 else max(1, -(-low // right_value))
        quotient_high = high // right_value
        if quotient_high < quotient_low:
            return []
        return [right_value * q for q in range(quotient_low, quotient_high + 1)]

    raise ValueError(f"未知运算符 {op!r}")


def ops_with_right_candidate(cfg: Config, left_value: int) -> list[str]:
    """给定左操作数，挑出**存在可用右操作数**的运算符。"""
    return [op for op in cfg.ops if right_candidates(cfg, op, left_value)]


def ops_with_left_candidate(cfg: Config, right_value: int) -> list[str]:
    """给定右操作数，挑出**存在可用左操作数**的运算符。"""
    return [op for op in cfg.ops if left_candidates(cfg, op, right_value)]


def can_gen_pair(cfg: Config, op: str) -> bool:
    """不依赖随机数，判断给定运算符能否构造出合法的两数运算。"""
    if op == "+":
        return cfg.max_value >= cfg.min_value and cfg.max_result >= 2 * cfg.min_value
    if op == "-":
        return cfg.max_value >= cfg.min_value
    if op == "*":
        mul_low, mul_high = mul_bounds(cfg)
        if mul_low > mul_high or mul_low > cfg.max_value:
            return False
        return any(
            right_candidates(cfg, "*", left)
            for left in range(mul_low, min(mul_high, cfg.max_value) + 1)
        )
    if op == "/":
        floor = divisor_floor(cfg)
        return any(
            _quotient_range(cfg, divisor) is not None
            for divisor in range(floor, cfg.max_value + 1)
        )
    raise ValueError(f"未知运算符 {op!r}")


def solvable_ops(cfg: Config) -> list[str]:
    """在给定约束下真正可用的运算符集合。"""
    return [op for op in cfg.ops if can_gen_pair(cfg, op)]


def gen_pair(cfg: Config, rng: random.Random, op: str) -> tuple[int, int]:
    """生成一对满足全部约束的 ``(左操作数, 右操作数)``。

    除法按合法整数对等概率抽样，再由除数与商乘出被除数。
    这样能一次性保证"整除"与"被除数不超过上界"，
    若等概率选除数，大除数只对应商 1，会让 n÷n 过于集中。
    按每个除数的合法商数量分配名额，可消除这个额外偏斜。
    """
    if op == "/":
        floor = divisor_floor(cfg)
        ranges = []
        for divisor in range(floor, cfg.max_value + 1):
            bounds = _quotient_range(cfg, divisor)
            if bounds is not None:
                ranges.append((divisor, *bounds))
        total = sum(high - low + 1 for _, low, high in ranges)
        if not total:
            raise NoSolution(op, cfg.max_value)
        ticket = rng.randrange(total)
        for divisor, low, high in ranges:
            size = high - low + 1
            if ticket < size:
                return divisor * (low + ticket), divisor
            ticket -= size
        raise AssertionError("除法候选计数与抽样不一致")

    if op == "*":
        mul_low, mul_high = mul_bounds(cfg)
        usable_lefts = [
            left
            for left in range(mul_low, min(mul_high, cfg.max_value) + 1)
            if right_candidates(cfg, "*", left)
        ]
        if not usable_lefts:
            raise NoSolution(op, cfg.mul_max)
        left_value = rng.choice(usable_lefts)
        return left_value, rng.choice(right_candidates(cfg, "*", left_value))

    left_low, left_high = cfg.min_value, cfg.max_value
    if op == "+":
        # 右操作数下界为 min_value，故左操作数不能太大
        left_high = min(left_high, cfg.max_result - cfg.min_value)

    left_value = rng.randint(left_low, left_high)
    candidates = right_candidates(cfg, op, left_value)
    if not candidates:
        raise NoSolution(op, left_value)
    return left_value, rng.choice(candidates)


def _quotient_range(cfg: Config, divisor: int) -> tuple[int, int] | None:
    """给定除数，返回合法商区间；无解时返回 ``None``。

    商 q 需满足：``0 ≤ min_value ≤ divisor × q ≤ max_value``。
    """
    low = cfg.min_value
    quotient_low = 0 if low == 0 else max(1, -(-low // divisor))
    quotient_high = cfg.max_value // divisor
    if quotient_high < quotient_low:
        return None
    return quotient_low, quotient_high


def pick_weighted(
    rng: random.Random, items: Sequence[T], weights: dict | None
) -> T:
    """按权重抽取；``weights`` 为 ``None`` 或权重全为 0 时等概率。"""
    pool = list(items)
    if len(pool) == 1 or not weights:
        return rng.choice(pool)
    effective = [weights.get(item, 1) for item in pool]
    if sum(effective) <= 0:
        return rng.choice(pool)
    return rng.choices(pool, weights=effective, k=1)[0]
