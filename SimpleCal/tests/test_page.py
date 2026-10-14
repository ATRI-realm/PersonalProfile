"""单文件页面本身的结构保证。

页面就是这份交付物的本体：双击打开、零依赖、离线可用。这里锁住几件一旦被
改动就会悄悄破坏它的事——外部资源引用、内联脚本的标记、答案开关的默认态，
以及"HTTP 服务已下线"这个前提（页面上不该再有任何网络调用）。

跟交叉验证（`test_engine_parity`）的分工：那边管"算出来的题对不对"，
这边管"这张页面还是不是一张能独立打开的页面"。
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_engine_parity import PAGE, extract_engine  # noqa: E402


class TestSingleFilePage(unittest.TestCase):
    """页面必须是自包含的，且标记与默认态稳定。"""

    html: str

    @classmethod
    def setUpClass(cls) -> None:
        if not PAGE.is_file():
            raise AssertionError(f"未找到页面 {PAGE.name}——它才是这份交付物本身")
        cls.html = PAGE.read_text(encoding="utf-8")

    def test_every_subresource_is_inlined(self) -> None:
        """页面只能引用内联资源。出现任何外链，"双击就能用"的承诺就破了。"""
        refs = re.findall(r'(?:src|href)\s*=\s*"([^"]*)"', self.html)
        external = [url for url in refs if url and not url.startswith(("data:", "#"))]
        self.assertEqual(external, [], f"页面引用了外部资源：{external}")

        self.assertEqual(
            re.findall(r"<script[^>]*\ssrc\s*=", self.html), [],
            "不该用 <script src>：引擎与界面脚本都该内联在页面里",
        )
        self.assertEqual(
            len(re.findall(r"<style[^>]*>", self.html)), 1,
            "样式应恰好内联成一块 <style>",
        )

    def test_inline_scripts_keep_their_markers(self) -> None:
        """两段脚本靠 id 定位；交叉验证正是按 sc-engine 把引擎抠出来的。"""
        for marker in ("sc-engine", "sc-app"):
            found = re.findall(r'^<script id="%s">\s*$' % marker, self.html, re.M)
            self.assertEqual(len(found), 1, f"标记 {marker} 应恰好出现一次")

    def test_engine_source_is_not_truncated(self) -> None:
        """抠出来的引擎要像引擎：长度合理，且确实挂在 SCEngine 上。"""
        source = extract_engine(self.html)
        self.assertGreater(len(source), 20000, "引擎源码过短，像是被截断了")
        self.assertIn("global.SCEngine", source)

    def test_page_makes_no_network_calls(self) -> None:
        """本地服务已下线，页面只靠内联引擎出题。"""
        self.assertNotIn("fetch(", self.html, "页面上不该再有网络请求")
        self.assertNotIn("/api/", self.html, "页面上不该再有服务端接口路径")

    def test_answer_switch_defaults_to_hidden(self) -> None:
        """默认不给答案——这是本版的产品决定，不是渲染层的偶然。"""
        buttons = re.findall(r"<button[^>]*id=\"answerBtn\"[^>]*>", self.html, re.S)
        self.assertEqual(len(buttons), 1, "应当恰好有一个答案开关按钮")
        self.assertIn('aria-pressed="false"', buttons[0], "开关默认为未打开")
        self.assertRegex(self.html, r"showAnswers:\s*false", "视图状态默认不给答案")


if __name__ == "__main__":
    unittest.main()
