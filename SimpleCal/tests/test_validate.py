"""独立求值器与硬约束判定的核验。"""

from __future__ import annotations

import unittest

from simple_calculate.config import Config
from simple_calculate.model import Node, Problem
from simple_calculate.render import render_expr
from simple_calculate.validate import InvalidExpression, eval_text, validate_problem


class TestEvalText(unittest.TestCase):
    def test_precedence_is_standard_not_left_to_right(self) -> None:
        """计划书 §3.1 的那个陷阱：无括号时按优先级结合。

        ``6 + 7 × 5`` 必须是 41 而不是 65。求值器如果写成从左到右，
        这条断言会失败。
        """
        self.assertEqual(eval_text("6 + 7 × 5")[0], 41)
        self.assertEqual(eval_text("6 + 7 * 5")[0], 41)
        self.assertEqual(eval_text("45 + 7 × 6")[0], 87)
        self.assertEqual(eval_text("100 − 8 × 9")[0], 28)

    def test_parentheses_override_precedence(self) -> None:
        self.assertEqual(eval_text("(6 + 7) × 5")[0], 65)
        self.assertEqual(eval_text("3 × (14 + 9)")[0], 69)
        self.assertEqual(eval_text("(58 − 19) × 2")[0], 78)
        self.assertEqual(eval_text("96 ÷ (5 + 3)")[0], 12)
        self.assertEqual(eval_text("(72 − 48) ÷ 6")[0], 4)

    def test_same_precedence_traps(self) -> None:
        """同级结构中括号不可省的两种情形。"""
        self.assertEqual(eval_text("50 − (70 − 20)")[0], 0)
        self.assertNotEqual(eval_text("50 − 70 − 20")[0], 0)
        self.assertEqual(eval_text("30 − (12 + 5)")[0], 13)
        self.assertNotEqual(eval_text("30 − 12 + 5")[0], 13)

    def test_zero_participates(self) -> None:
        self.assertEqual(eval_text("0 + 7")[0], 7)
        self.assertEqual(eval_text("7 − 0")[0], 7)
        self.assertEqual(eval_text("0 × 5")[0], 0)
        self.assertEqual(eval_text("0 ÷ 5")[0], 0)

    def test_reports_all_values(self) -> None:
        value, values = eval_text("3 × (14 + 9)")
        self.assertEqual(value, 69)
        self.assertEqual(sorted(values), sorted([3, 14, 9, 23, 69]))

    def test_rejects_illegal_expressions(self) -> None:
        for text in ["7 ÷ 2", "5 ÷ 0", "(3 + 4", "3 + 4)", "9 $ 3", "", "   ", "− 5 + 3"]:
            with self.subTest(text=text):
                with self.assertRaises(InvalidExpression):
                    eval_text(text)


class TestValidateProblem(unittest.TestCase):
    def test_render_preserves_table_constraint_after_parenthesis_removal(self) -> None:
        root = Node(value=12, op="*", left=Node.leaf(2),
                    right=Node(value=6, op="/", left=Node.leaf(18), right=Node.leaf(3)))
        cfg = Config()
        self.assertEqual(render_expr(root, cfg), "2 × (18 ÷ 3)")
        self.assertEqual(validate_problem(self.make(root, "2 × (18 ÷ 3)"), cfg), [])
        errors = validate_problem(self.make(root, "2 × 18 ÷ 3"), cfg)
        self.assertTrue(any("实际乘法" in message for message in errors), errors)
        # 放宽因子区间后才允许省去这对括号。
        self.assertEqual(render_expr(root, Config(mul_max=99)), "2 × 18 ÷ 3")

    def make(self, root: Node, text: str) -> Problem:
        return Problem(
            root=root, text=text, answer=root.value, text_norm=text.replace(" ", "")
        )

    def test_accepts_a_correct_problem(self) -> None:
        """``6 × (88 ÷ 11)``：乘法两个操作数是 6 与 8，都在九九表内；
        去掉括号后虽然值相同，但过程要先算 6 × 88 = 528，所以括号必须保留。
        """
        root = Node(
            value=48,
            op="*",
            left=Node.leaf(6),
            right=Node(value=8, op="/", left=Node.leaf(88), right=Node.leaf(11)),
        )
        cfg = Config()
        self.assertEqual(validate_problem(self.make(root, "6 × (88 ÷ 11)"), cfg), [])
        # 去掉括号后值仍相等，但展开过程越界，必须被判为不合格
        self.assertNotEqual(validate_problem(self.make(root, "6 × 88 ÷ 11"), cfg), [])

    def test_detects_multiplication_outside_mul_table(self) -> None:
        root = Node(value=33, op="*", left=Node.leaf(11), right=Node.leaf(3))
        problems = validate_problem(self.make(root, "11 × 3"), Config())
        self.assertTrue(any("九九表" in item for item in problems), problems)

    def test_detects_intermediate_used_as_factor_outside_mul_table(self) -> None:
        """中间结果同样是乘法因子，超出九九表区间也要报出来。"""
        root = Node(
            value=69,
            op="*",
            left=Node.leaf(3),
            right=Node(value=23, op="+", left=Node.leaf(14), right=Node.leaf(9)),
        )
        problems = validate_problem(self.make(root, "3 × (14 + 9)"), Config())
        self.assertTrue(any("九九表" in item for item in problems), problems)
        self.assertTrue(any("23" in item for item in problems), problems)

    def test_detects_disagreement_between_text_and_answer(self) -> None:
        broken = Problem(
            root=Node(value=7, op="+", left=Node.leaf(3), right=Node.leaf(4)),
            text="3 + 4",
            answer=8,
            text_norm="3+4",
        )
        problems = validate_problem(broken, Config())
        self.assertTrue(any("回读校验" in item for item in problems), problems)

    def test_detects_zero_result_when_forbidden(self) -> None:
        root = Node(value=0, op="-", left=Node.leaf(5), right=Node.leaf(5))
        cfg = Config(allow_zero_result=False)
        problems = validate_problem(self.make(root, "5 − 5"), cfg)
        self.assertTrue(any("结果为 0" in item for item in problems), problems)


if __name__ == "__main__":
    unittest.main()
