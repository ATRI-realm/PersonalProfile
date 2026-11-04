"""专项题库与讲解用 Python 独立枚举、求值复核。"""
import json
import re
import subprocess
import unittest
from pathlib import Path

from test_engine_parity import PAGE, find_node


class TestSpecialties(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = find_node()
        if node is None:
            raise unittest.SkipTest("未找到 node")
        result = subprocess.run(
            [node, str(Path(__file__).with_name("specialty_checks.js")), str(PAGE)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.data = json.loads(result.stdout)

    def test_specialty_recommendation_storage_and_hint_rules(self):
        for name, error in self.data["cases"].items():
            with self.subTest(name=name):
                self.assertIsNone(error, error)

    def test_complete_fact_sets_and_every_explanation_equation(self):
        expected = {
            "carry20": {(a, b, a + b) for a in range(1, 10) for b in range(1, 10) if a + b > 10},
            "borrow20": {(a, b, a - b) for a in range(11, 20) for b in range(1, 10) if a % 10 < b},
        }
        for skill, questions in self.data["pools"].items():
            actual = set()
            for question in questions:
                a, b = map(int, re.findall(r"\d+", question["text"]))
                actual.add((a, b, question["answer"]))
                for step in question["steps"]:
                    expression, result = step["equation"].split(" = ")
                    def calculate(side):
                        terms = list(map(int, re.findall(r"\d+", side)))
                        if "+" in side:
                            return sum(terms)
                        if "−" in side:
                            return terms[0] - terms[1]
                        return terms[0]

                    values = list(map(int, re.findall(r"\d+", step["equation"])))
                    self.assertEqual(calculate(expression), calculate(result), step)
                    self.assertTrue(all(0 <= value <= 20 for value in values))
                self.assertEqual(int(question["steps"][-1]["equation"].split(" = ")[1]), question["answer"])
            self.assertEqual(actual, expected[skill])
            self.assertEqual(len(questions), 36)
