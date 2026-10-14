"""题目生成器。

三种结构（对应计划书 §4.3）：

* 单运算符：``a ⊕ b``
* 结构 A：``(a ⊕ b) ⊗ c`` —— 先算左
* 结构 B：``a ⊕ (b ⊗ c)`` —— 先算右

三者的数值都只通过 ``core.gen_pair`` 这一个原语产生，
"约束不越界"由构造方式保证，而不是靠事后筛选。

出题分两步，这个顺序是刻意的（对应计划书 §4.4）：

1. **先把题量按 ``ratio`` 分配到每一种运算符个数上**（``_allocate_quotas``），
   再让每一类各自去凑自己的名额；
2. 每一类内部独立去重，互不干扰。

第 1 步不能省。若改成"逐题抽类型、一旦撞去重就重抽类型"，那么当某一类的
题面空间先被抽干时，它被拒绝的代价会由另一类补上，配比就被悄悄改掉了——
实测在 5 万题规模下，1:1 的设定会漂移到约 19:81。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .config import Config, OP_PRECEDENCE
from .core import (
    NoSolution,
    apply_op,
    gen_pair,
    left_candidates,
    ops_with_left_candidate,
    ops_with_right_candidate,
    pick_weighted,
    right_candidates,
    solvable_ops,
)
from .model import Node, Problem
from .render import render_expr
from .validate import validate_problem


class GenerationError(RuntimeError):
    """生成结果与独立校验结果不一致——属于程序缺陷，正常情况下不应出现。"""


# 连续多少次"抽到的题面已经出现过"就判定该类的题面空间已被抽干。
#
# 这个判据只能在"几乎抽干"和"完全抽干"之间取一个平衡：空间剩得越少，
# 连续撞车越容易发生，两者在行为上本就难以区分。取值偏小会过早收手
# （实测 200 时，单运算符题在还剩约 7% 空间时就停了），偏大则空间真的
# 用尽后要多做几次无谓尝试。1000 在两边都比较从容：空间够用时它不可能
# 被触发，空间用尽后也只多花不到 0.1 秒。
_DEDUP_STRIKES_BEFORE_EXHAUSTED = 1000

_NORMALIZE_TABLE = str.maketrans({"×": "*", "÷": "/", "−": "-", "⋅": "*", "·": "*"})


def normalize_text(text: str) -> str:
    """把题面归一到可比较的形式，用于同一份卷子内去重。"""
    return "".join(text.split()).translate(_NORMALIZE_TABLE)


def paren_never_needed(shape: str, op_inner: str, op_outer: str) -> bool:
    """判断某结构是否在**任何取值下**都不需要括号。

    这是计划书 §3.2 速判表的实现，仅用于 ``paren="none"`` 模式下预先筛掉
    必然带括号的结构。实际是否写括号，仍由渲染层的求值比对决定。
    """
    inner = OP_PRECEDENCE[op_inner]
    outer = OP_PRECEDENCE[op_outer]
    if shape == "A":  # (a op_inner b) op_outer c
        return inner >= outer
    # shape == "B": a op_outer (b op_inner c)
    if outer < inner:
        return True
    if outer == inner:
        return op_outer in ("+", "*")
    return False


def _allocate_quotas(cfg: Config) -> dict[int, int]:
    """按 ``ratio`` 把 ``count`` 个名额精确分配给各运算符个数。

    用最大余数法：先取整，再把没分完的名额按小数部分从大到小补上。
    这样总和恒等于 ``count``，且与设定比例最接近——配比是用户的显式设定，
    必须精确兑现，不能让"某一类题先被抽干"这类副作用改变它。
    """
    kinds = list(cfg.operator_counts)
    if len(kinds) == 1:
        return {kinds[0]: cfg.count}

    weights = list(cfg.ratio)
    total = sum(weights)
    exact = [cfg.count * weight / total for weight in weights]
    quota = [int(value) for value in exact]
    shortfall = cfg.count - sum(quota)
    # 小数部分大的先补；并列时按 operator_counts 的顺序，保证结果可复现
    order = sorted(range(len(kinds)), key=lambda i: (-(exact[i] - quota[i]), i))
    for index in order[:shortfall]:
        quota[index] += 1
    return dict(zip(kinds, quota))


def _allowed_outer_ops(
    cfg: Config, shape: str, op_inner: str, outer_pool: list[str]
) -> list[str]:
    """按括号模式过滤外层运算符。

    ``paren="none"`` 时只保留"在任何取值下都不必加括号"的组合；
    因此无括号模式不需要靠重试来撞，而是从源头就不生成带括号的结构。
    """
    if cfg.paren != "none":
        return list(outer_pool)
    return [op for op in outer_pool if paren_never_needed(shape, op_inner, op)]


def _build_two_number(cfg: Config, rng: random.Random, op: str) -> Node:
    left, right = gen_pair(cfg, rng, op)
    return Node(
        value=apply_op(op, left, right),
        op=op,
        left=Node.leaf(left),
        right=Node.leaf(right),
    )


def _build_shape_a(cfg: Config, rng: random.Random) -> Node:
    """结构 A：``(a ⊕ b) ⊗ c``。"""
    pool = solvable_ops(cfg)
    inner_pool = [op for op in pool if _allowed_outer_ops(cfg, "A", op, pool)]
    if not inner_pool:
        raise NoSolution("A", 0)
    op1 = pick_weighted(rng, inner_pool, cfg.weights)
    inner = _build_two_number(cfg, rng, op1)

    outer_pool = _allowed_outer_ops(
        cfg, "A", op1, ops_with_right_candidate(cfg, inner.value)
    )
    if not outer_pool:
        raise NoSolution(op1, inner.value)
    op2 = pick_weighted(rng, outer_pool, cfg.weights)
    third = rng.choice(right_candidates(cfg, op2, inner.value))
    return Node(
        value=apply_op(op2, inner.value, third),
        op=op2,
        left=inner,
        right=Node.leaf(third),
    )


def _build_shape_b(cfg: Config, rng: random.Random) -> Node:
    """结构 B：``a ⊕ (b ⊗ c)``。"""
    pool = solvable_ops(cfg)
    inner_pool = [op for op in pool if _allowed_outer_ops(cfg, "B", op, pool)]
    if not inner_pool:
        raise NoSolution("B", 0)
    op2 = pick_weighted(rng, inner_pool, cfg.weights)
    inner = _build_two_number(cfg, rng, op2)

    outer_pool = _allowed_outer_ops(
        cfg, "B", op2, ops_with_left_candidate(cfg, inner.value)
    )
    if not outer_pool:
        raise NoSolution(op2, inner.value)
    op1 = pick_weighted(rng, outer_pool, cfg.weights)
    first = rng.choice(left_candidates(cfg, op1, inner.value))
    return Node(
        value=apply_op(op1, first, inner.value),
        op=op1,
        left=Node.leaf(first),
        right=inner,
    )


def build_expression(cfg: Config, rng: random.Random, operator_count: int) -> Node:
    if operator_count == 1:
        pool = solvable_ops(cfg)
        if not pool:
            raise NoSolution("single", 0)
        op = pick_weighted(rng, pool, cfg.weights)
        return _build_two_number(cfg, rng, op)
    if operator_count == 2:
        return _build_shape_a(cfg, rng) if rng.random() < 0.5 else _build_shape_b(cfg, rng)
    raise ValueError(f"运算符个数只能是 1 或 2，收到 {operator_count}")


def _has_trivial_form(root: Node) -> bool:
    """识别没有训练价值的形式：``n × 1``、``1 × n``、``n ÷ 1``、``0 ⊕ 0``。"""
    for node in root.iter_operators():
        left = node.left.value  # type: ignore[union-attr]
        right = node.right.value  # type: ignore[union-attr]
        if node.op == "*" and (left == 1 or right == 1):
            return True
        if node.op == "/" and right == 1:
            return True
        if left == 0 and right == 0:
            return True
    return False


def _zero_only_as_answer(root: Node) -> bool:
    """True 表示 0 只作为最终结果出现，没有任何一处让 0 参与运算。"""
    for node in root.iter_nodes():
        if node.is_leaf and node.value == 0:
            return False
        if not node.is_leaf and node is not root and node.value == 0:
            return False
    return True


def _accept(cfg: Config, root: Node) -> str | None:
    """返回拒绝理由；``None`` 表示通过全部过滤。"""
    text = render_expr(root, cfg)
    if cfg.paren == "none" and "(" in text:
        return "无括号模式下出现了括号"
    if cfg.paren == "always" and "(" not in text:
        return "括号模式下未能生成含括号的题"
    if cfg.exclude_trivial and _has_trivial_form(root):
        return "命中平凡题过滤"
    if cfg.exclude_zero_forms and not _zero_only_as_answer(root):
        return "命中 0 形式过滤"
    if not cfg.allow_zero_result and root.value == 0:
        return "结果为 0，但配置不允许"
    return None


@dataclass
class _KindReport:
    """某一个运算符个数（一类题）的产出情况。"""

    kind: int
    wanted: int
    produced: int
    repeats: int
    exhausted: bool

    @property
    def missing(self) -> int:
        return self.wanted - self.produced


def _generate_kind(
    cfg: Config, rng: random.Random, kind: int, quota: int, seen: set[str]
) -> tuple[list[Problem], _KindReport]:
    """为一类题生成至多 ``quota`` 道题面互不重复的题目。

    ``seen`` 是整份卷子共享的已用题面集合：同一份卷子里 ``3 + 4`` 与 ``3 × 4``
    是两道不同的题，但两道 ``3 + 4`` 不行。

    一类的题面空间是有限的（默认参数下，单运算符题约 1 万种，双运算符题 20 万种以上）。
    空间被抽干时：

    * 默认（``allow_repeat=False``）停止本类，由调用方如实报告缺口；
    * ``allow_repeat=True`` 时允许重复使用已出过的题面，先把题量凑满。
    """
    problems: list[Problem] = []
    repeats = 0
    strikes = 0
    exhausted = False
    attempts = 0
    attempt_limit = max(quota * cfg.attempts_per_problem, cfg.attempts_per_problem)

    while len(problems) < quota and attempts < attempt_limit:
        attempts += 1
        try:
            root = build_expression(cfg, rng, kind)
        except NoSolution:
            continue
        if _accept(cfg, root) is not None:
            continue

        text = render_expr(root, cfg)
        key = normalize_text(text)
        if key in seen:
            strikes += 1
            if strikes >= _DEDUP_STRIKES_BEFORE_EXHAUSTED:
                exhausted = True
            if not cfg.allow_repeat:
                if exhausted:
                    break  # 空间已尽，再抽也抽不到新题面
                continue
            repeats += 1
        else:
            strikes = 0
            seen.add(key)

        problem = Problem(root=root, text=text, answer=root.value, text_norm=key)
        errors = validate_problem(problem, cfg)
        if errors:
            raise GenerationError(
                f"生成结果未通过自校验（题面 {text!r}）：" + "；".join(errors)
            )
        problems.append(problem)

    return problems, _KindReport(
        kind=kind,
        wanted=quota,
        produced=len(problems),
        repeats=repeats,
        exhausted=exhausted,
    )


def _build_hint(reports: list[_KindReport]) -> str | None:
    """把产出情况写成一句人话；一切正常时返回 ``None``。"""
    notes: list[str] = []
    missing = [report for report in reports if report.missing > 0]
    if missing:
        detail = "、".join(
            f"{report.kind} 个运算符的题需要 {report.wanted} 道，"
            f"不重复的题面只够 {report.produced} 道"
            for report in missing
        )
        notes.append(f"题量不足：{detail}")

    repeated = sum(report.repeats for report in reports)
    if repeated:
        notes.append(f"有 {repeated} 道题目与卷中其他题目重复")

    if not notes:
        return None

    advices = ["放宽数值范围", "增加可用的运算符", "减少题量"]
    if repeated == 0:
        advices.insert(0, "允许题面重复")
    return "；".join(notes) + "。可尝试：" + "、".join(advices) + "。"


def generate_problems(
    cfg: Config, rng: random.Random | None = None
) -> tuple[list[Problem], str | None]:
    """生成一份题面。

    返回 ``(题目列表, 提示信息)``。提示信息在"没能如数凑满"或"出现了重复题面"
    时非空——宁可直接说明，也不静默少给、更不静默改变题型配比。
    """
    cfg.validate_config()
    generator = rng if rng is not None else random.Random(cfg.seed)

    quotas = _allocate_quotas(cfg)
    seen: set[str] = set()
    problems: list[Problem] = []
    reports: list[_KindReport] = []

    for kind in sorted(quotas):
        quota = quotas[kind]
        if quota <= 0:
            continue
        batch, report = _generate_kind(cfg, generator, kind, quota, seen)
        problems.extend(batch)
        reports.append(report)

    # 各类是分段凑出来的，混排一下，卷面上不至于前半页全是单运算符题。
    generator.shuffle(problems)
    return problems, _build_hint(reports)
