"""命令行入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ALL_OPS, PAREN_MODES, Config
from .generator import GenerationError, generate_problems
from .render import render_sheet

_ALIASES = {
    "×": "*",
    "÷": "/",
    "−": "-",
    "⋅": "*",
    "·": "*",
    "加": "+",
    "减": "-",
    "乘": "*",
    "除": "/",
}


def _parse_ops(raw: str) -> tuple[str, ...]:
    text = raw.strip()
    if text.lower() in ("all", ""):
        return ALL_OPS
    ops: list[str] = []
    for char in text.replace(",", "").replace(" ", ""):
        normalized = _ALIASES.get(char, char)
        if normalized in ALL_OPS:
            if normalized not in ops:
                ops.append(normalized)
        else:
            raise argparse.ArgumentTypeError(f"无法识别的运算符 {char!r}")
    if not ops:
        raise argparse.ArgumentTypeError("至少需要指定一个运算符")
    return tuple(sorted(ops, key=ALL_OPS.index))


def _parse_weights(raw: str) -> dict[str, int]:
    weights: dict[str, int] = {}
    for chunk in raw.replace(" ", "").split(","):
        if not chunk:
            continue
        if "=" not in chunk:
            raise argparse.ArgumentTypeError(
                f"权重格式应为“运算符=数值”，例如 “+=3,-=3,*=2,/=2”，收到 {chunk!r}"
            )
        op, _, value = chunk.partition("=")
        op = _ALIASES.get(op, op)
        if op not in ALL_OPS:
            raise argparse.ArgumentTypeError(f"权重中的运算符 {op!r} 无法识别")
        try:
            weights[op] = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"权重 {value!r} 不是整数") from exc
    if not weights:
        raise argparse.ArgumentTypeError("权重不能为空")
    return weights


def _parse_operator_counts(raw: str) -> tuple[int, ...]:
    counts: list[int] = []
    for chunk in raw.replace(" ", "").split(","):
        if not chunk:
            continue
        if chunk not in ("1", "2"):
            raise argparse.ArgumentTypeError("运算符个数只能取 1 或 2")
        counts.append(int(chunk))
    if not counts:
        raise argparse.ArgumentTypeError("至少需要指定一种运算符个数")
    return tuple(sorted(set(counts)))


def _parse_ratio(raw: str) -> tuple[int, ...]:
    parts = [chunk for chunk in raw.replace(" ", "").split(",") if chunk]
    try:
        values = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"比例 {raw!r} 含非整数") from exc
    if not values or any(value < 0 for value in values):
        raise argparse.ArgumentTypeError("比例必须是非负整数")
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simple-calculate",
        description="面向小学生的四则运算题目生成器（本版只输出题面，不输出答案）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  simple-calculate -n 20 --seed 42\n"
            "  simple-calculate -n 12 --operators 2 --paren necessary --per-line 2\n"
            "  simple-calculate -n 30 --ops +- --mul-min 0 --out 题目.txt\n"
        ),
    )
    parser.add_argument("-n", "--count", type=int, default=20, help="题目数量（默认 20）")
    parser.add_argument(
        "--ops",
        type=_parse_ops,
        default=ALL_OPS,
        help="参与抽取的运算符集合，默认为全部四则运算（例如 --ops +- 或 --ops 加减乘除）",
    )
    parser.add_argument(
        "--weights",
        type=_parse_weights,
        default=None,
        help="各运算符权重，例如 +=3,-=3,*=2,/=2；缺省的运算符按 1 计",
    )
    parser.add_argument(
        "--operators",
        type=_parse_operator_counts,
        default=(1, 2),
        help="每题的运算符个数，取 1 / 2 / 1,2（默认 1,2 混合）",
    )
    parser.add_argument(
        "--ratio",
        type=_parse_ratio,
        default=(1, 1),
        help="与 --operators 对应的比例，例如 --operators 1,2 --ratio 3,7（默认 1,1）",
    )
    parser.add_argument(
        "--min-value", type=int, default=1,
        help="叶子操作数下界（默认 1；要让 0 参与运算，设为 0 并加 --no-exclude-zero-forms）"
    )
    parser.add_argument(
        "--max-value", type=int, default=99, help="叶子操作数上界（默认 99）"
    )
    parser.add_argument(
        "--max-result",
        type=int,
        default=100,
        help="中间结果与最终结果的硬上界（默认 100）",
    )
    parser.add_argument(
        "--mul-min", type=int, default=1, help="乘法因数下界（默认 1，即九九表不含 0）"
    )
    parser.add_argument(
        "--mul-max", type=int, default=9, help="乘法因数上界（默认 9，即九九表）"
    )
    parser.add_argument(
        "--paren",
        choices=PAREN_MODES,
        default="necessary",
        help=(
            "括号模式：none 只出无括号题；necessary（默认）括号只出现在必需处；"
            "always 只出含（必要）括号的双运算符题"
        ),
    )
    parser.add_argument(
        "--no-zero-result", dest="allow_zero_result", action="store_false",
        help="禁止结果为 0（默认允许）",
    )
    parser.add_argument(
        "--exclude-trivial",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="过滤 n×1、1×n、n÷1、0⊕0 这类无训练价值的形式（默认开启）",
    )
    parser.add_argument(
        "--exclude-zero-forms",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="让 0 只能作为最终结果出现，不参与任何运算（默认开启）",
    )
    parser.add_argument(
        "--allow-repeat",
        action="store_true",
        help=(
            "题面不重复的空间不够时，允许重复使用已出过的题面把题量凑满。"
            "默认不允许——凑不满会如实报告缺口，而不是静默少给或改变题型配比"
        ),
    )
    parser.add_argument("--per-line", type=int, default=4, help="每行排几道题（默认 4）")
    parser.add_argument("--seed", type=int, default=None, help="随机种子，用于复现同一份题面")
    parser.add_argument("--out", type=Path, default=None, help="把题面写入文件（.txt / .md）")
    parser.add_argument(
        "--no-blank-line",
        dest="blank_between_rows",
        action="store_false",
        help="行与行之间不留空行",
    )
    parser.add_argument(
        "--show-answer",
        action="store_true",
        help="连同答案一起输出（默认只出题面）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cfg = Config(
        count=args.count,
        ops=args.ops,
        weights=args.weights,
        operator_counts=args.operators,
        ratio=args.ratio,
        min_value=args.min_value,
        max_value=args.max_value,
        max_result=args.max_result,
        mul_min=args.mul_min,
        mul_max=args.mul_max,
        paren=args.paren,
        allow_zero_result=args.allow_zero_result,
        exclude_trivial=args.exclude_trivial,
        exclude_zero_forms=args.exclude_zero_forms,
        allow_repeat=args.allow_repeat,
        per_line=args.per_line,
        seed=args.seed,
    )

    try:
        cfg.validate_config()
    except ValueError as exc:
        print(f"参数有误：{exc}", file=sys.stderr)
        return 2

    try:
        problems, hint = generate_problems(cfg)
    except GenerationError as exc:
        print(f"生成失败：{exc}", file=sys.stderr)
        return 1

    sheet = render_sheet(
        problems,
        per_line=cfg.per_line,
        show_answer=args.show_answer,
        blank_between_rows=args.blank_between_rows,
    )

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(sheet + "\n", encoding="utf-8")
        print(f"已写入 {args.out}（共 {len(problems)} 题）", file=sys.stderr)
    else:
        print(sheet)

    if hint:
        print(hint, file=sys.stderr)
    if cfg.seed is None:
        print("如需复现本次题面，请加上 --seed <整数> 重新生成。", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
