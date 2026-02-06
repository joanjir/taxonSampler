# taxonomy/tree/filters.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

TreeNode = Dict[str, Any]

RANK_ORDER = [
    "dataset",
    "domain",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
]

LAST_RANK_INDEX = len(RANK_ORDER) - 1


def norm_rank(rank: Any) -> str:
    return str(rank or "").strip().lower()


def rank_index(rank: Any) -> int:
    r = norm_rank(rank)
    try:
        return RANK_ORDER.index(r)
    except ValueError:
        return -1


def is_leaf(node: Optional[TreeNode]) -> bool:
    if not node:
        return True
    ch = node.get("children")
    return not isinstance(ch, list) or len(ch) == 0


def shallow_clone(node: Optional[TreeNode]) -> TreeNode:
    node = node or {}
    out = dict(node)
    out.pop("children", None)
    out.pop("_children", None)
    return out


def collapse_all(node: TreeNode) -> TreeNode:
    n = shallow_clone(node)

    children = node.get("children")
    if not isinstance(children, list) or len(children) == 0:
        n["children"] = None
        n["_children"] = None
        return n

    n["children"] = None
    n["_children"] = [collapse_all(c) for c in children]
    return n


def cut_tree_by_rank(full_data: Optional[TreeNode], rank_cut: Any) -> Optional[TreeNode]:
    if not full_data:
        return None

    cut = norm_rank(rank_cut)

    # "" => solo root visible (todo en _children)
    if not cut:
        root_only = shallow_clone(full_data)
        children = full_data.get("children")
        if isinstance(children, list) and children:
            root_only["children"] = None
            root_only["_children"] = [collapse_all(c) for c in children]
        else:
            root_only["children"] = None
            root_only["_children"] = None
        return root_only

    cut_idx = rank_index(cut)

    # rank desconocido => conservador
    if cut_idx < 0:
        safe = shallow_clone(full_data)
        children = full_data.get("children")
        safe["children"] = [collapse_all(c) for c in children] if isinstance(children, list) else None
        safe["_children"] = None
        return safe

    def build(node: TreeNode) -> TreeNode:
        n = shallow_clone(node)

        if is_leaf(node):
            n["children"] = None
            n["_children"] = None
            return n

        idx = rank_index(node.get("rank"))
        safe_idx = -999 if idx < 0 else idx

        # species => abre todo
        if cut_idx == LAST_RANK_INDEX:
            n["children"] = [build(c) for c in node["children"]]
            n["_children"] = None
            return n

        # por encima del corte => hijos visibles
        if safe_idx < cut_idx:
            n["children"] = [build(c) for c in node["children"]]
            n["_children"] = None
            return n

        # en el corte o por debajo => colapsa
        n["children"] = None
        n["_children"] = [collapse_all(c) for c in node["children"]]
        return n

    return build(full_data)


def count_visible_nodes(tree: Optional[TreeNode]) -> int:
    if not tree:
        return 0
    c = 0
    stack: List[TreeNode] = [tree]
    while stack:
        n = stack.pop()
        c += 1
        ch = n.get("children")
        if isinstance(ch, list) and ch:
            stack.extend(ch)
    return c
