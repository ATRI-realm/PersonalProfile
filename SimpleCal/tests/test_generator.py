"""生成器的端到端核验。

核心是**批量采样**：约束是"全称命题"（每一个数值都要合法），
抽查没有意义，必须逐题断言。采样规模可用环境变量 ``SC_SAMPLE_N`` 调整。
"""

from __future__ import annotations

import collections
import json
import os
import random
import unittest

from simple_calculate.config import Config
from simple_calculate.generator import (
    GenerationError,
    _allocate_quotas,
    generate_problems,
    normalize_text,
    paren_never_needed,
)
from simple_calculate.render import render_problem, render_sheet
from simple_calculate.validate import InvalidExpression, eval_text, validate_problem

SAMPLE_N = int(os.environ.get("SC_SAMPLE_N", "20000"))


def scan(cfg: Config) -> list:
    """生成一批题并逐题断言；返回题目列表。"""
    problems, _ = generate_problems(cfg)
    for problem in problems:
        errors = validate_problem(problem, cfg)
        if errors:
            raise AssertionError(f"题面 {problem.text!r} 未通过校验：{errors}")
        value, _ = eval_text(problem.text)
        if value != problem.answer:
            raise AssertionError(f"题面 {problem.text!r} 回读得 {value}，记录 {problem.answer}")
        if "=" in problem.text:
            raise AssertionError(f"题面 {problem.text!r} 不应包含等号")
        if problem.root.operator_count() not in (1, 2):
            raise AssertionError(f"运算符个数异常：{problem.text!r}")
    return problems


class TestDefaultSampling(unittest.TestCase):
    def test_large_batch_passes_every_hard_constraint(self) -> None:
        """批量采样逐题核对全部硬约束（断言在 ``scan`` 内部）。

        规模由 ``SC_SAMPLE_N`` 控制。单运算符题的题面空间约 1 万种，
        因此规模拉大后允许出现缺额——缺额的报告行为由 ``TestTypeRatio`` 覆盖。
        """
        cfg = Config(count=SAMPLE_N, seed=20260916)
        problems = scan(cfg)
        self.assertGreater(
            len(problems), SAMPLE_N // 2, "产出远少于请求量，说明生成过程出了问题"
        )
        self.assertEqual(
            len({p.text_norm for p in problems}),
            len(problems),
            "同一份卷子里出现了重复题目",
        )

    def test_zero_is_allowed_to_participate(self) -> None:
        cfg = Config(count=2000, seed=1, min_value=0, exclude_zero_forms=False)
        problems = scan(cfg)
        leaves = [leaf for p in problems for leaf in p.root.leaves()]
        self.assertIn(0, leaves, "允许 0 参与，但样本里没出现任何 0 操作数")

    def test_zero_result_appears(self) -> None:
        cfg = Config(count=3000, seed=2)
        problems = scan(cfg)
        self.assertTrue(
            any(p.answer == 0 for p in problems), "允许结果为 0，但样本里没出现结果为 0 的题"
        )

    def test_multiplication_stays_inside_nine_nine_table(self) -> None:
        cfg = Config(count=3000, seed=3)
        problems = scan(cfg)
        mul_low, mul_high = cfg.mul_min, cfg.mul_max
        for problem in problems:
            for node in problem.root.iter_operators():
                if node.op == "*":
                    for operand in (node.left.value, node.right.value):
                        self.assertTrue(
                            mul_low <= operand <= mul_high,
                            f"{problem.text!r} 的乘法操作数 {operand} 不在九九表 [{mul_low}, {mul_high}] 内",
                        )

    def test_trivial_forms_are_filtered_by_default(self) -> None:
        cfg = Config(count=3000, seed=4)
        problems = scan(cfg)
        for problem in problems:
            for node in problem.root.iter_operators():
                left, right = node.left.value, node.right.value
                self.assertFalse(node.op == "*" and (left == 1 or right == 1), problem.text)
                self.assertFalse(node.op == "/" and right == 1, problem.text)
                self.assertFalse(left == 0 and right == 0, problem.text)

    def test_exclude_zero_forms_keeps_zero_only_as_answer(self) -> None:
        cfg = Config(count=1500, seed=5, exclude_zero_forms=True)
        problems = scan(cfg)
        for problem in problems:
            self.assertNotIn(0, problem.root.leaves(), problem.text)
            for node in problem.root.iter_nodes():
                if node is not problem.root and node.value == 0:
                    self.fail(f"{problem.text!r} 中 0 参与了运算")


class TestConfigurationsAndModes(unittest.TestCase):
    def test_no_paren_mode_never_emits_parentheses(self) -> None:
        cfg = Config(count=600, seed=6, paren="none")
        problems = scan(cfg)
        for problem in problems:
            self.assertNotIn("(", problem.text, problem.text)

    def test_always_paren_mode_only_two_operator_problems_with_parens(self) -> None:
        cfg = Config(count=600, seed=7, paren="always", operator_counts=(2,))
        problems = scan(cfg)
        for problem in problems:
            self.assertEqual(problem.root.operator_count(), 2)
            self.assertIn("(", problem.text, problem.text)

    def test_operator_count_selection_is_respected(self) -> None:
        single = scan(Config(count=300, seed=8, operator_counts=(1,)))
        self.assertTrue(all(p.root.operator_count() == 1 for p in single))
        double = scan(Config(count=300, seed=9, operator_counts=(2,)))
        self.assertTrue(all(p.root.operator_count() == 2 for p in double))

    def test_paren_mode_necessary_avoids_redundant_parentheses(self) -> None:
        """necessary 模式下，括号绝不多余。

        "必需"包括算式非法、语义改变、实际因子超出九九表或展开过程越界。
        例如 ``80 + (34 − 23)``
        去掉括号后要先算 ``80 + 34 = 114``）。
        """
        cfg = Config(count=600, seed=10, paren="necessary", operator_counts=(2,))
        problems = scan(cfg)
        checked = 0
        for problem in problems:
            if "(" not in problem.text:
                continue
            checked += 1
            stripped = problem.text.replace("(", "").replace(")", "")
            try:
                operations = []
                stripped_value, stripped_values = eval_text(stripped, operations=operations)
            except InvalidExpression:
                continue  # 情形一：算式直接非法
            if stripped_value != problem.answer:
                continue  # 情形二：语义改变
            # 值相同也可能让实际乘法的因子超出九九表。
            invalid_mul = any(
                op == "*" and any(not cfg.mul_min <= x <= cfg.mul_max for x in (a, b))
                for op, a, b in operations
            )
            self.assertTrue(
                invalid_mul or any(v < 0 or v > cfg.max_result for v in stripped_values),
                f"{problem.text!r} 的括号去掉后既不改语义也不越界，属于多余的括号",
            )
        self.assertGreater(checked, 0, "necessary 模式下未出现任何含括号的题")

    def test_parenthesised_problems_keep_expansion_inside_bounds(self) -> None:
        """括号必须守住"计算过程也不越界"这一条。

        反例形态：``6 × (88 ÷ 11)`` 看似可去括号（值相同），
        但展开后要先算 528，超出 100。
        """
        cfg = Config(count=4000, seed=31)
        problems = scan(cfg)
        found = False
        for problem in problems:
            for node in problem.root.iter_operators():
                if node.op == "*" and node.right is not None and node.right.op == "/":
                    found = True
            value, values = eval_text(problem.text)
            self.assertTrue(all(0 <= v <= cfg.max_result for v in values), problem.text)
        self.assertTrue(found, "样本中未出现「乘法套除法」的结构，无法覆盖该分支")

    def test_weights_shift_operator_distribution(self) -> None:
        cfg = Config(
            count=4000, seed=11, operator_counts=(1,), weights={"+": 9, "-": 1, "*": 1, "/": 1}
        )
        problems = scan(cfg)
        plus = sum(1 for p in problems if p.root.op == "+")
        self.assertGreater(plus / len(problems), 0.5, "加权后加法占比没有明显上升")

    def test_ops_restriction(self) -> None:
        problems = scan(Config(count=300, seed=12, ops=("+", "-")))
        for problem in problems:
            for node in problem.root.iter_operators():
                self.assertIn(node.op, ("+", "-"))

    def test_no_zero_result_switch(self) -> None:
        cfg = Config(count=800, seed=13, allow_zero_result=False)
        problems = scan(cfg)
        self.assertTrue(all(p.answer != 0 for p in problems))

    def test_min_value_one_excludes_zero(self) -> None:
        cfg = Config(count=800, seed=14, min_value=1)
        problems = scan(cfg)
        for problem in problems:
            self.assertNotIn(0, problem.root.leaves())

    def test_mul_min_zero_allows_zero_as_a_factor(self) -> None:
        """``--mul-min 0`` 让 0 也能作乘法操作数。

        这条路径曾经直接整数除零崩溃——``0 × y`` 恒为 0、不可能越界，
        但求候选上界的 ``⌊max_result / 操作数⌋`` 在操作数为 0 时会先炸。
        """
        cfg = Config(count=400, seed=15, ops=("*",), mul_min=0, min_value=0,
                     exclude_zero_forms=False, operator_counts=(1,))
        problems = scan(cfg)
        for problem in problems:
            node = problem.root
            for operand in (node.left.value, node.right.value):
                self.assertGreaterEqual(operand, cfg.mul_min, problem.text)
                self.assertLessEqual(operand, cfg.mul_max, problem.text)
        self.assertTrue(
            any(0 in (p.root.left.value, p.root.right.value) for p in problems),
            "mul_min=0 时样本中没出现 0 作乘法操作数",
        )

    def test_mul_min_zero_works_in_two_operator_problems(self) -> None:
        """0 作为乘法操作数时，双运算符题（含括号结构）也要正常生成。"""
        cfg = Config(count=600, seed=16, mul_min=0, min_value=0, exclude_zero_forms=False)
        problems = scan(cfg)
        self.assertTrue(any(p.operator_count == 2 for p in problems))


class TestBehaviourAndInterfaces(unittest.TestCase):
    def test_same_seed_reproduces_identical_sheet(self) -> None:
        first, _ = generate_problems(Config(count=120, seed=99))
        second, _ = generate_problems(Config(count=120, seed=99))
        self.assertEqual([p.text for p in first], [p.text for p in second])
        self.assertEqual(render_sheet(first), render_sheet(second))

    def test_different_seed_gives_different_sheet(self) -> None:
        first, _ = generate_problems(Config(count=120, seed=1))
        second, _ = generate_problems(Config(count=120, seed=2))
        self.assertNotEqual([p.text for p in first], [p.text for p in second])

    def test_external_rng_is_used(self) -> None:
        a, _ = generate_problems(Config(count=50), rng=random.Random(5))
        b, _ = generate_problems(Config(count=50), rng=random.Random(5))
        self.assertEqual([p.text for p in a], [p.text for p in b])

    def test_sheet_omits_answers_in_this_version(self) -> None:
        problems, _ = generate_problems(Config(count=16, seed=21))
        sheet = render_sheet(problems, per_line=4)
        self.assertNotIn("答案", sheet)
        for problem in problems:
            self.assertTrue(render_problem(problem).endswith("= "))
        for line in sheet.splitlines():
            if not line.strip():
                continue
            # 每个等号之后都必须只跟空白（留给学生作答）
            for segment in line.split("=")[1:]:
                self.assertTrue(
                    segment == "" or segment[0] == " ",
                    f"等号后出现了内容：{line!r}",
                )

    def test_problem_serialises_to_json(self) -> None:
        problems, _ = generate_problems(Config(count=5, seed=22))
        payload = json.dumps([p.to_dict() for p in problems], ensure_ascii=False)
        restored = json.loads(payload)
        self.assertEqual(len(restored), 5)
        self.assertEqual(restored[0]["answer"], problems[0].answer)

    def test_reports_shortfall_instead_of_silently_returning_fewer(self) -> None:
        cfg = Config(count=20, seed=23, ops=("+",), min_value=1, max_value=2,
                     mul_max=2, operator_counts=(1,))
        problems, hint = generate_problems(cfg)
        self.assertLess(len(problems), cfg.count)
        self.assertIsNotNone(hint)
        self.assertIn("题量不足", hint or "")
        # 缺额必须是真的：这组参数下 1⊕1 形式的加法题总共只有 4 道
        self.assertEqual(len(problems), 4)

    def test_invalid_config_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            generate_problems(Config(min_value=5, max_value=3))
        with self.assertRaises(ValueError):
            generate_problems(Config(paren="always", operator_counts=(1,)))
        with self.assertRaises(ValueError):
            generate_problems(Config(ops=("^",)))

    def test_generation_never_raises_internal_validation_error(self) -> None:
        """生成逻辑与校验逻辑必须始终一致。"""
        for seed in range(12):
            try:
                generate_problems(Config(count=200, seed=seed))
            except GenerationError as exc:  # pragma: no cover
                self.fail(f"seed={seed} 出现内部校验失败：{exc}")


class TestTypeRatio(unittest.TestCase):
    """题量必须按 ``ratio`` 精确分配到各类，且不被"某一类先抽干"拖偏。

    这是修复过的一个真实缺陷。旧实现逐题抽运算符个数、一旦撞去重就重抽个数，
    于是单运算符题（默认参数下只有约 1 万种题面）先被抽干后，它被拒绝的代价
    由双运算符题（20 万种以上）补上——5 万题规模下 1:1 的设定漂移到约 19:81。
    配比是用户的显式设定，不能被这种副作用改掉。
    """

    def test_quotas_follow_ratio_exactly(self) -> None:
        cases = [
            (100, (1, 1), {1: 50, 2: 50}),
            (100, (3, 7), {1: 30, 2: 70}),
            (101, (1, 1), {1: 51, 2: 50}),  # 余数按 operator_counts 的顺序补齐
            (10, (0, 5), {1: 0, 2: 10}),
            (7, (2, 1), {1: 5, 2: 2}),
        ]
        for count, ratio, expected in cases:
            with self.subTest(count=count, ratio=ratio):
                self.assertEqual(
                    _allocate_quotas(Config(count=count, ratio=ratio)), expected
                )

    def test_single_kind_takes_the_whole_count(self) -> None:
        self.assertEqual(
            _allocate_quotas(Config(count=37, operator_counts=(2,))), {2: 37}
        )

    def test_output_matches_ratio_at_scale(self) -> None:
        problems, hint = generate_problems(Config(count=6000, seed=101))
        kinds = collections.Counter(p.operator_count for p in problems)
        self.assertEqual((kinds[1], kinds[2]), (3000, 3000))
        self.assertIsNone(hint)

    def test_ratio_can_favour_one_kind_heavily(self) -> None:
        problems, hint = generate_problems(Config(count=4000, seed=102, ratio=(9, 1)))
        kinds = collections.Counter(p.operator_count for p in problems)
        self.assertEqual((kinds[1], kinds[2]), (3600, 400))
        self.assertIsNone(hint)

    def test_shortfall_of_one_kind_does_not_eat_the_other_kind(self) -> None:
        """某一类凑不满时，另一类的名额必须照给，配比不静默漂移。"""
        cfg = Config(count=40, seed=103, ops=("+",), min_value=1, max_value=3, mul_max=3)
        problems, hint = generate_problems(cfg)
        kinds = collections.Counter(p.operator_count for p in problems)
        self.assertEqual(kinds[1], 9, "1⊕1 形式的加法题总共只有 3×3 = 9 种")
        self.assertEqual(kinds[2], 20, "双运算符的名额被单运算符的缺口侵占了")
        self.assertIn("题量不足", hint or "")
        self.assertIn("1 个运算符", hint or "")

    def test_oversized_batch_reports_shortfall_without_shifting_ratio(self) -> None:
        """题量超出某一类的题面空间时，如实报告缺口，配比仍然站得住。"""
        cfg = Config(count=30000, seed=20260917)
        problems, hint = generate_problems(cfg)
        kinds = collections.Counter(p.operator_count for p in problems)
        self.assertEqual(kinds[2], 15000, "双运算符的名额被侵占了")
        self.assertGreater(kinds[1], 9000, "单运算符题面约 1 万种，不该只给出这么少")
        self.assertLessEqual(kinds[1], 11000)
        self.assertIn("题量不足", hint or "")

    def test_allow_repeat_tops_up_the_quota_and_says_so(self) -> None:
        cfg = Config(count=20, seed=104, ops=("+",), min_value=1, max_value=2,
                     mul_max=2, operator_counts=(1,), allow_repeat=True)
        problems, hint = generate_problems(cfg)
        self.assertEqual(len(problems), 20, "开启 allow_repeat 后应把名额凑满")
        self.assertEqual(len({p.text_norm for p in problems}), 4, "1⊕1 只有 4 种题面")
        self.assertIn("与卷中其他题目重复", hint or "")

    def test_repeat_is_off_by_default(self) -> None:
        cfg = Config(count=20, seed=105, ops=("+",), min_value=1, max_value=2,
                     mul_max=2, operator_counts=(1,))
        problems, hint = generate_problems(cfg)
        self.assertEqual(len(problems), 4)
        self.assertNotIn("与卷中其他题目重复", hint or "")


class TestParenRuleTable(unittest.TestCase):
    """计划书 §3.2 速判表的实现必须与枚举结论一致。"""

    def test_structure_a_never_needs_parens_when_inner_precedence_is_higher(self) -> None:
        for inner in "+-*/":
            for outer in "+-*/":
                expected = {"+": 1, "-": 1, "*": 2, "/": 2}[inner] >= {
                    "+": 1, "-": 1, "*": 2, "/": 2
                }[outer]
                self.assertEqual(paren_never_needed("A", inner, outer), expected)

    def test_structure_b_rule_matches_exhaustive_result(self) -> None:
        """结构 B 中"永不需括号"的结论，与穷举核验结果完全一致。

        穷举结论：内层与外层优先级相同时，只有外层为 ``+`` 或 ``×``
        才恒不需括号；外层为 ``-`` 或 ``÷`` 时括号可能必需。
        """
        never = {
            ("+", "+"),
            ("-", "+"),
            ("*", "+"),
            ("*", "-"),
            ("*", "*"),
            ("/", "+"),
            ("/", "-"),
            ("/", "*"),
        }
        for inner in "+-*/":
            for outer in "+-*/":
                self.assertEqual(
                    paren_never_needed("B", inner, outer),
                    (inner, outer) in never,
                    f"结构 B 内层 {inner}、外层 {outer} 的判定与穷举不符",
                )

    def test_normalize_text_is_stable_across_symbol_variants(self) -> None:
        self.assertEqual(normalize_text("3 × (14 + 9)"), "3*(14+9)")
        self.assertEqual(normalize_text("3 * (14 + 9)"), normalize_text("3 × (14 + 9)"))


if __name__ == "__main__":
    unittest.main()
