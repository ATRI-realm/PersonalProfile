"""两数合法对构造的核验。

重点是把「按区间构造」与「暴力枚举」的结果对齐——
构造区间一旦把边界写错，这里会立刻暴露。

为避免 subTest 的开销，循环里只收集问题，最后一次性断言。
"""

from __future__ import annotations

import random
import unittest

from simple_calculate.config import ALL_OPS, Config, mul_bounds
from simple_calculate.core import (
    apply_op,
    can_gen_pair,
    gen_pair,
    left_candidates,
    right_candidates,
    solvable_ops,
)


def configs_for_scan() -> list[Config]:
    return [
        Config(),
        Config(min_value=1),
        Config(max_value=20, mul_max=9),
        Config(max_value=99, mul_max=99),
        Config(mul_min=0, min_value=0, exclude_zero_forms=False),
        Config(ops=("+", "-")),
        Config(ops=("/",), max_value=30),
        Config(ops=("*",), max_value=99, mul_max=99),
    ]


class TestCandidateSets(unittest.TestCase):
    def test_two_tables_are_symmetric_on_leaf_domain(self) -> None:
        """当左右两侧都取叶子值时，两张候选表必须互为对称。

        ``right_candidates(op, x)`` 回答"x 在左，右边能放什么"；
        ``left_candidates(op, y)`` 回答"y 在右，左边能放什么"。
        在叶子定义域上，两者的判定必须完全一致。
        """
        mismatches: list[str] = []
        for cfg in configs_for_scan():
            domain = list(range(cfg.min_value, cfg.max_value + 1))
            for op in ALL_OPS:
                right_sets = {x: set(right_candidates(cfg, op, x)) for x in domain}
                left_sets = {y: set(left_candidates(cfg, op, y)) for y in domain}
                for x in domain:
                    right_set = right_sets[x]
                    for y in domain:
                        in_right = y in right_set
                        in_left = x in left_sets[y]
                        if in_right != in_left:
                            mismatches.append(f"{x} {op} {y}：右表={in_right} 左表={in_left}")
        self.assertEqual(mismatches[:10], [], f"两张候选表出现 {len(mismatches)} 处不一致")

    def test_candidates_are_always_legal_leaves(self) -> None:
        violations: list[str] = []
        for cfg in configs_for_scan():
            for op in ALL_OPS:
                for given in range(0, cfg.max_result + 1):
                    values = list(right_candidates(cfg, op, given)) + list(
                        left_candidates(cfg, op, given)
                    )
                    for value in values:
                        if not cfg.min_value <= value <= cfg.max_value:
                            violations.append(f"{op} 已知 {given} 给出越界候选 {value}")
        self.assertEqual(violations[:10], [], f"共 {len(violations)} 处越界候选")

    def test_multiplication_operands_stay_inside_mul_table(self) -> None:
        """九九表约束是双向闭合的：两个操作数都必须落在区间内。

        只卡上界会让 ``0 × 1`` 在一张表里合法、在另一张表里非法，
        所以这里同时检查上下界。
        """
        violations: list[str] = []
        for cfg in configs_for_scan():
            mul_low, mul_high = mul_bounds(cfg)
            for given in range(0, cfg.max_result + 1):
                for value in right_candidates(cfg, "*", given):
                    if not mul_low <= given <= mul_high:
                        violations.append(f"左操作数 {given} 不在九九表区间")
                    if not mul_low <= value <= mul_high:
                        violations.append(f"右操作数 {value} 不在九九表区间")
                for value in left_candidates(cfg, "*", given):
                    if not mul_low <= given <= mul_high:
                        violations.append(f"右操作数 {given} 不在九九表区间")
                    if not mul_low <= value <= mul_high:
                        violations.append(f"左操作数 {value} 不在九九表区间")
        self.assertEqual(violations[:10], [], f"共 {len(violations)} 处超出九九表")

    def test_division_never_uses_zero_divisor(self) -> None:
        for cfg in configs_for_scan():
            for given in range(0, cfg.max_result + 1):
                self.assertNotIn(0, right_candidates(cfg, "/", given))
                if given == 0:
                    self.assertEqual(left_candidates(cfg, "/", given), [])

    def test_division_quotient_never_exceeds_leaf_upper_bound(self) -> None:
        for cfg in configs_for_scan():
            for given in range(0, cfg.max_result + 1):
                for value in right_candidates(cfg, "/", given):
                    if given == 0:
                        continue
                    quotient = given // value
                    self.assertGreaterEqual(quotient, 0)
                    self.assertLessEqual(quotient, cfg.max_result)


class TestGenPair(unittest.TestCase):
    def test_division_samples_each_legal_pair_once_per_ticket(self) -> None:
        """逐一覆盖抽样名额，与暴力枚举对齐，避免只抽除数导致商 1 偏多。"""
        class TicketRandom(random.Random):
            def __init__(self, ticket):
                self.ticket = ticket

            def randrange(self, stop):
                assert 0 <= self.ticket < stop
                return self.ticket

        for minimum in (0, 1, 3):
            cfg = Config(min_value=minimum, max_value=20)
            expected = {(a, b) for a in range(minimum, 21)
                        for b in range(max(1, minimum), 21) if a % b == 0}
            actual = [gen_pair(cfg, TicketRandom(i), "/") for i in range(len(expected))]
            self.assertEqual(set(actual), expected)
            self.assertEqual(len(actual), len(set(actual)))

    def test_generated_pairs_satisfy_every_constraint(self) -> None:
        rng = random.Random(20260916)
        violations: list[str] = []
        for cfg in configs_for_scan():
            mul_low, mul_high = mul_bounds(cfg)
            for op in solvable_ops(cfg):
                for _ in range(1500):
                    left, right = gen_pair(cfg, rng, op)
                    if not cfg.min_value <= left <= cfg.max_value:
                        violations.append(f"{op} 左操作数 {left} 越界")
                    if not cfg.min_value <= right <= cfg.max_value:
                        violations.append(f"{op} 右操作数 {right} 越界")
                    if op == "*":
                        for operand in (left, right):
                            if not mul_low <= operand <= mul_high:
                                violations.append(
                                    f"{op} 操作数 {operand} 不在九九表区间：{left} × {right}"
                                )
                    value = apply_op(op, left, right)
                    if value < 0 or value > cfg.max_result:
                        violations.append(f"{op} 结果 {value} 越界")
        self.assertEqual(violations[:10], [], f"共 {len(violations)} 处违规")

    def test_can_gen_pair_matches_actual_behaviour(self) -> None:
        rng = random.Random(7)
        for cfg in configs_for_scan():
            for op in ALL_OPS:
                possible = can_gen_pair(cfg, op)
                try:
                    gen_pair(cfg, rng, op)
                    actual = True
                except Exception:
                    actual = False
                self.assertEqual(possible, actual, f"{cfg} / {op}")


if __name__ == "__main__":
    unittest.main()
