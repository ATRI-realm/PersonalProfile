"""最终离线页面的学生档案与备份恢复检查。"""
import json
import subprocess
import unittest
from pathlib import Path

from test_engine_parity import PAGE, find_node


class TestStudents(unittest.TestCase):
    def test_student_storage_migration_and_backup_transactions(self):
        node = find_node()
        if node is None:
            self.skipTest("未找到 node")
        result = subprocess.run(
            [node, str(Path(__file__).with_name("student_checks.js")), str(PAGE)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        cases = json.loads(result.stdout)
        self.assertGreaterEqual(len(cases), 20)
        for name, error in cases.items():
            with self.subTest(name=name):
                self.assertIsNone(error, error)
