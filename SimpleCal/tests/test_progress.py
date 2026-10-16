"""从最终单文件页面验证闯关、积分、兑换及本地存储事务。"""
import json
import subprocess
import unittest
from pathlib import Path

from test_engine_parity import PAGE, find_node, to_config, to_problem
from simple_calculate.validate import validate_problem


class TestProgress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = find_node()
        if node is None:
            raise unittest.SkipTest("未找到 node")
        result = subprocess.run(
            [node, str(Path(__file__).with_name("progress_checks.js")), str(PAGE)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.data = json.loads(result.stdout)

    def test_progress_shop_and_storage_behaviors(self):
        self.assertGreaterEqual(len(self.data["cases"]), 20)
        for name, error in self.data["cases"].items():
            with self.subTest(name=name):
                self.assertIsNone(error, error)

    def test_all_level_questions_pass_independent_python_validator(self):
        total = 0
        for sample in self.data["samples"]:
            cfg = to_config(sample["config"])
            for problem in sample["problems"]:
                errors = validate_problem(to_problem(problem), cfg)
                self.assertEqual(errors, [], f"{problem['text']}：{errors}")
                total += 1
        self.assertEqual(total, 1200)
