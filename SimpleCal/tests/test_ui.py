"""执行最终页面的实际事件处理器，使用 DOM 替身验证功能流程。"""
import subprocess
import unittest
from pathlib import Path

from test_engine_parity import PAGE, find_node


class TestPageInteractions(unittest.TestCase):
    def test_learning_flow_and_existing_level_rewards(self):
        node = find_node()
        if node is None:
            self.skipTest("未找到 node")
        result = subprocess.run(
            [node, str(Path(__file__).with_name("ui_checks.js")), str(PAGE)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS: GitHub Pages cloud endpoint", result.stdout)
