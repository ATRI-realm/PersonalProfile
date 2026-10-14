"""面向小学生的四则运算题目生成器。

核心层是纯函数：不做 IO、不使用全局随机状态、随机源由调用方注入。
因此它既可以被命令行直接调用，也可以被后续的接口层或前端复用。

``Problem`` 始终同时持有题面与答案，**是否显示答案由渲染层决定**——
命令行用 ``--show-answer``、网页版用顶栏那个开关，都只是把它带出来或按下去，
生成逻辑本身不关心这件事。
"""

from .config import ALL_OPS, OP_DISPLAY, PAREN_MODES, Config
from .generator import GenerationError, generate_problems
from .model import Node, Problem
from .render import render_problem, render_sheet
from .validate import InvalidExpression, eval_text, validate_problem

__version__ = "0.1.0"

__all__ = [
    "ALL_OPS",
    "Config",
    "GenerationError",
    "InvalidExpression",
    "Node",
    "OP_DISPLAY",
    "PAREN_MODES",
    "Problem",
    "__version__",
    "eval_text",
    "generate_problems",
    "render_problem",
    "render_sheet",
    "validate_problem",
]
