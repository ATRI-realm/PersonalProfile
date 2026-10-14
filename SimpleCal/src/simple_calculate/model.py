"""表达式树与题目的数据结构。

``Node`` 同时表示叶子（``op is None``，值即字面量）与内部节点。
每棵子树在构造时就把 ``value`` 算好并缓存，后续校验、渲染、判重都直接复用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator


@dataclass
class Node:
    value: int
    op: str | None = None
    left: "Node | None" = None
    right: "Node | None" = None

    @staticmethod
    def leaf(number: int) -> "Node":
        return Node(value=number)

    @property
    def is_leaf(self) -> bool:
        return self.op is None

    def iter_nodes(self) -> Iterator["Node"]:
        """先序遍历自身与全部后代。"""
        yield self
        if self.left is not None:
            yield from self.left.iter_nodes()
        if self.right is not None:
            yield from self.right.iter_nodes()

    def iter_operators(self) -> Iterator["Node"]:
        for node in self.iter_nodes():
            if not node.is_leaf:
                yield node

    def leaves(self) -> list[int]:
        return [node.value for node in self.iter_nodes() if node.is_leaf]

    def operator_count(self) -> int:
        return sum(1 for _ in self.iter_operators())

    def depth(self) -> int:
        if self.is_leaf:
            return 0
        children = [child for child in (self.left, self.right) if child is not None]
        return 1 + max(child.depth() for child in children)

    def to_dict(self) -> dict[str, Any]:
        if self.is_leaf:
            return {"kind": "leaf", "value": self.value}
        return {
            "kind": "operator",
            "op": self.op,
            "value": self.value,
            "left": self.left.to_dict() if self.left else None,
            "right": self.right.to_dict() if self.right else None,
        }


@dataclass
class Problem:
    """一道题。

    ``text`` 是**不含等号**的算式本身（例如 ``3 × (14 + 9)``），
    这样它可以被独立求值器直接解析，用于回读校验；
    题号与等号由渲染层负责添加。
    """

    root: Node
    text: str
    answer: int
    text_norm: str

    @property
    def operator_count(self) -> int:
        return self.root.operator_count()

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "answer": self.answer,
            "operatorCount": self.operator_count,
            "leaves": self.root.leaves(),
            "tree": self.root.to_dict(),
        }
