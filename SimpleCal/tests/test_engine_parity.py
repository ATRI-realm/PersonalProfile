"""内联在单文件页面里的出题引擎 × Python 实现的交叉验证。

`口算练习.html` 里内联着一份浏览器版出题引擎（`id="sc-engine"` 那段脚本）。
它的存在是为了让这张页面双击就能用——`file://` 下浏览器既不允许页面去抓
本地服务，也不允许跑 ES module。代价是生成逻辑有了两份实现，所以这里不靠
"照着抄了一遍"的自觉，而是把引擎从页面里抠出来、在 Node 下成批出题，
再全部交回 Python 那份**独立校验器**逐题复核：

    页面内联引擎出题 → 导回 Python → validate_problem 逐题判定

校验器本来就不依赖生成器，所以这条链是有意义的独立复核，而不是自说自话。
顺带锁住三件容易悄悄漂移的事：配置默认值、题面排版、单双运算符配比。

需要本机有 node；找不到时整类跳过——不把可选工具变成硬依赖。
但页面本身找不到、或页面上找不到那个标记时，一律**报错而不是跳过**：
那说明交付物坏了，不该被一次"跳过"悄悄盖过去。
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from simple_calculate.config import ALL_OPS, OP_DISPLAY, PAREN_MODES, Config
from simple_calculate.generator import normalize_text
from simple_calculate.model import Node, Problem
from simple_calculate.render import render_sheet
from simple_calculate.validate import validate_problem

PAGE = ROOT / "口算练习.html"

# 引擎是页面里第一段内联脚本，标记独占一行且顶格。锚定行首是为了不受
# 注释里出现的同名文字影响。
ENGINE_MARK = re.compile(r'^<script id="sc-engine">\s*$(.*?)^</script>\s*$',
                         re.S | re.M)


def extract_engine(html: str) -> str:
    """把内联的引擎脚本从页面里抠出来，供 Node 加载。"""
    match = ENGINE_MARK.search(html)
    if match is None:
        raise AssertionError(
            '口算练习.html 里找不到 <script id="sc-engine"> 标记：'
            "交叉验证失去了对象。这属于交付物损坏，不按跳过处理"
        )
    return match.group(1)

# Node 侧的小驱动：加载 engine.js，按给定参数成批出题，把结果（含表达式树）写出来。
DRIVER = r"""
const fs = require('fs');
const vm = require('vm');

vm.runInThisContext(fs.readFileSync(process.argv[2], 'utf8'), { filename: 'engine.js' });
const cases = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));

const out = { meta: SCEngine.meta(), cases: {} };
for (const item of cases) {
  const result = SCEngine.generate(item.payload);
  out.cases[item.name] = {
    payload: item.payload,
    requested: result.requested,
    produced: result.produced,
    hint: result.hint,
    sheet: result.sheet,
    problems: result.problems.map((p) => ({
      text: p.text,
      answer: p.answer,
      operatorCount: p.operatorCount,
      tree: p.tree,
    })),
  };
}
fs.writeFileSync(process.argv[4], JSON.stringify(out), 'utf8');
"""

# 参数组合刻意铺开：运算符子集、单/双运算符、配比、三种括号模式、
# 数值范围、九九表的四组边界、三条过滤开关、加权抽样，以及最宽约束。
CASES = [
    {"name": "default", "payload": {"count": 150, "seed": 20260923}},
    {"name": "ops-addsub", "payload": {"count": 150, "seed": 11, "ops": ["+", "-"]}},
    {"name": "ops-mul", "payload": {"count": 150, "seed": 12, "ops": ["*"]}},
    {"name": "ops-div", "payload": {"count": 150, "seed": 13, "ops": ["/"]}},
    {"name": "single-only", "payload": {"count": 150, "seed": 14, "operator_counts": [1]}},
    {"name": "double-only", "payload": {"count": 150, "seed": 15, "operator_counts": [2]}},
    {"name": "ratio-9-1", "payload": {"count": 150, "seed": 16, "operator_counts": [1, 2], "ratio": [9, 1]}},
    {"name": "paren-none", "payload": {"count": 150, "seed": 17, "paren": "none"}},
    {"name": "paren-always", "payload": {"count": 150, "seed": 18, "paren": "always", "operator_counts": [2]}},
    {"name": "min-value-1", "payload": {"count": 150, "seed": 19, "min_value": 1}},
    {"name": "max-value-20", "payload": {"count": 150, "seed": 20, "max_value": 20}},
    {"name": "mul-min-0", "payload": {"count": 150, "seed": 21, "mul_min": 0}},
    {"name": "mul-wide-open", "payload": {"count": 150, "seed": 22, "mul_min": 0, "mul_max": 99}},
    {"name": "no-zero-result", "payload": {"count": 150, "seed": 23, "allow_zero_result": False}},
    {"name": "keep-trivial", "payload": {"count": 150, "seed": 24, "exclude_trivial": False}},
    {"name": "zero-as-answer-only", "payload": {"count": 150, "seed": 25, "exclude_zero_forms": True}},
    {"name": "weighted", "payload": {"count": 150, "seed": 26, "weights": {"+": 5, "-": 1, "*": 1, "/": 1}}},
    {
        "name": "widest",
        "payload": {
            "count": 150, "seed": 27, "mul_min": 0, "mul_max": 99,
            "exclude_trivial": False, "exclude_zero_forms": False,
        },
    },
]

TUPLE_KEYS = {"ops", "operator_counts", "ratio"}


def find_node() -> str | None:
    for candidate in (os.environ.get("SC_NODE"), shutil.which("node"), shutil.which("node.exe")):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def to_node(payload: dict) -> Node:
    if payload["kind"] == "leaf":
        return Node.leaf(payload["value"])
    return Node(
        value=payload["value"],
        op=payload["op"],
        left=to_node(payload["left"]),
        right=to_node(payload["right"]),
    )


def to_config(payload: dict) -> Config:
    return Config(**{
        key: (tuple(value) if key in TUPLE_KEYS else value)
        for key, value in payload.items()
    })


def to_problem(item: dict) -> Problem:
    return Problem(
        root=to_node(item["tree"]),
        text=item["text"],
        answer=item["answer"],
        text_norm=normalize_text(item["text"]),
    )


class TestBrowserEngineParity(unittest.TestCase):
    """浏览器引擎的产出必须能通过 Python 的独立校验器。"""

    data: dict

    @classmethod
    def setUpClass(cls) -> None:
        node = find_node()
        if node is None:
            raise unittest.SkipTest("未找到 node，跳过浏览器引擎的交叉验证")
        if not PAGE.is_file():
            raise AssertionError(f"未找到页面 {PAGE.name}——它才是这份交付物本身")

        engine_source = extract_engine(PAGE.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            driver = tmp_path / "driver.js"
            engine = tmp_path / "engine.js"
            cases = tmp_path / "cases.json"
            result = tmp_path / "out.json"
            driver.write_text(DRIVER, encoding="utf-8")
            engine.write_text(engine_source, encoding="utf-8")
            cases.write_text(json.dumps(CASES, ensure_ascii=False), encoding="utf-8")

            proc = subprocess.run(
                [node, str(driver), str(engine), str(cases), str(result)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if proc.returncode != 0:
                raise AssertionError(f"浏览器引擎执行失败：\n{proc.stdout}\n{proc.stderr}")
            cls.data = json.loads(result.read_text(encoding="utf-8"))

    def test_every_problem_passes_python_validator(self) -> None:
        """核心断言：浏览器出的每一道题都要过 Python 的独立校验器。"""
        total = 0
        violations: list[str] = []
        for name, entry in self.data["cases"].items():
            cfg = to_config(entry["payload"])
            for item in entry["problems"]:
                total += 1
                errors = validate_problem(to_problem(item), cfg)
                if errors:
                    violations.append(f"[{name}] {item['text']}：{'；'.join(errors)}")

        self.assertGreater(total, 2000, "交叉验证样本过小，覆盖不足")
        self.assertEqual(
            violations[:5], [],
            f"{len(violations)} / {total} 道题未通过 Python 校验器",
        )

    def test_sheet_layout_matches_python(self) -> None:
        """纯文本题面的排版必须与 Python 的 render_sheet 逐字符一致。"""
        for name, entry in self.data["cases"].items():
            cfg = to_config(entry["payload"])
            problems = [to_problem(item) for item in entry["problems"]]
            expected = render_sheet(problems, per_line=cfg.per_line, show_answer=False)
            self.assertEqual(entry["sheet"], expected, f"[{name}] 题面排版不一致")

    def test_ratio_is_exact_when_quota_can_be_met(self) -> None:
        """配比是显式设定，必须精确兑现——除非那一类的题面空间确实不够。"""
        for name, entry in self.data["cases"].items():
            cfg = to_config(entry["payload"])
            if len(cfg.operator_counts) < 2:
                continue
            if entry["produced"] < entry["requested"]:
                continue  # 有缺额时配比本就无法保证，另由 hint 如实报告

            counts = Counter(item["operatorCount"] for item in entry["problems"])
            total_weight = sum(cfg.ratio)
            for kind, weight in zip(cfg.operator_counts, cfg.ratio):
                expected = cfg.count * weight / total_weight
                self.assertAlmostEqual(
                    counts.get(kind, 0), expected, delta=1.0,
                    msg=f"[{name}] {kind} 个运算符的题 {counts.get(kind, 0)} 道，期望 {expected}",
                )

    def test_shortfall_is_reported_not_hidden(self) -> None:
        """凑不满时必须给提示，不能静默少给。"""
        for name, entry in self.data["cases"].items():
            if entry["produced"] < entry["requested"]:
                self.assertIsNotNone(entry["hint"], f"[{name}] 有缺额却没有提示")

    def test_defaults_match_python_config(self) -> None:
        """默认值必须逐字段一致，否则页面显示的默认与实际出题用的默认会分叉。"""
        js_defaults = self.data["meta"]["defaults"]
        for field in dataclasses.fields(Config):
            value = None if field.default is dataclasses.MISSING else field.default
            if isinstance(value, tuple):
                value = list(value)
            self.assertEqual(
                js_defaults.get(field.name, "<缺失>"), value,
                f"默认值 {field.name} 两侧不一致",
            )

    def test_metadata_matches_python(self) -> None:
        self.assertEqual(self.data["meta"]["ops"], list(ALL_OPS))
        self.assertEqual(self.data["meta"]["opDisplay"], OP_DISPLAY)
        self.assertEqual(self.data["meta"]["parenModes"], list(PAREN_MODES))


if __name__ == "__main__":
    unittest.main()
