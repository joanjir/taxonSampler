# taxonomy/views/filters.py
from typing import Dict, Any, List, Optional

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


def norm_rank(rank: Optional[str]) -> str:
    return (rank or "").strip().lower()


def rank_index(rank: Optional[str]) -> int:
    try:
        return RANK_ORDER.index(norm_rank(rank))
    except ValueError:
        return -1


def is_leaf(node: Dict[str, Any]) -> bool:
    return not node or not node.get("children")


def shallow_clone(node: Dict[str, Any]) -> Dict[str, Any]:
    """
    Clona el nodo sin children ni _children.
    Mantiene metadata (id, external_id, etc.)
    """
    return {k: v for k, v in node.items() if k not in ("children", "_children")}


def collapse_all(node: Dict[str, Any]) -> Dict[str, Any]:
    n = shallow_clone(node)

    children = node.get("children") or []
    if not children:
        n["children"] = None
        n["_children"] = None
        return n

    n["children"] = None
    n["_children"] = [collapse_all(c) for c in children]
    return n


def cut_tree_by_rank(full_data: Dict[str, Any], rank_cut: Optional[str]) -> Dict[str, Any]:
    if not full_data:
        return full_data

    cut = norm_rank(rank_cut)

    # Caso 1: "" → solo ROOT visible
    if not cut:
        root = shallow_clone(full_data)
        children = full_data.get("children") or []
        root["children"] = None
        root["_children"] = [collapse_all(c) for c in children] if children else None
        return root

    cut_idx = rank_index(cut)

    # Rank desconocido → política conservadora (no romper UI)
    if cut_idx < 0:
        safe = shallow_clone(full_data)
        safe["children"] = [collapse_all(c) for c in (full_data.get("children") or [])]
        safe["_children"] = None
        return safe

    def build(node: Dict[str, Any], parent_idx: int) -> Dict[str, Any]:
        n = shallow_clone(node)

        if is_leaf(node):
            n["children"] = None
            n["_children"] = None
            return n

        idx = rank_index(node.get("rank"))

        # CLAVE: si rank es desconocido, hereda el índice del padre
        cur_idx = idx if idx >= 0 else parent_idx

        # species → abrir todo (si tu política es esa)
        if cut_idx == LAST_RANK_INDEX:
            n["children"] = [build(c, cur_idx) for c in node.get("children", [])]
            n["_children"] = None
            return n

        # Por encima del corte → abierto
        if cur_idx < cut_idx:
            n["children"] = [build(c, cur_idx) for c in node.get("children", [])]
            n["_children"] = None
            return n

        # En el corte o por debajo → colapsar
        n["children"] = None
        n["_children"] = [collapse_all(c) for c in node.get("children", [])]
        return n

    # ROOT "dataset" está en tu RANK_ORDER => idx válido; si no, arranca en -999
    root_idx = rank_index(full_data.get("rank"))
    root_idx = root_idx if root_idx >= 0 else -999

    return build(full_data, root_idx)


