# apps/taxonomy/tree/managers.py
"""
Pure functions for taxonomic tree manipulation (no DB).

These functions operate on D3 dicts {name, rank, children, _children, key}.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from apps.taxonomy.utils import (
    RANK_ORDER,
    LAST_RANK_INDEX,
    norm_rank,
    rank_index,
    path_key_from_parts,
)


# ============================================================
# Basic helpers
# ============================================================

def shallow_clone(node: Dict[str, Any]) -> Dict[str, Any]:
    """Clones the node without children or _children."""
    return {k: v for k, v in node.items() if k not in ("children", "_children")}


def is_leaf(node: Dict[str, Any]) -> bool:
    """Checks if the node is a leaf."""
    return not node or not node.get("children")


# ============================================================
# Collapse and cut by rank
# ============================================================

def collapse_all(node: Dict[str, Any]) -> Dict[str, Any]:
    """Collapses the entire subtree: children -> _children recursively."""
    n = shallow_clone(node)
    children = node.get("children") or []
    
    if not children:
        n["children"] = None
        n["_children"] = None
        return n
    
    n["children"] = None
    n["_children"] = [collapse_all(c) for c in children]
    return n


def cut_by_rank(tree: Dict[str, Any], rank_cut: Optional[str]) -> Dict[str, Any]:
    """
    Cuts the tree down to a specific rank.
    
    - rank_cut = "" or None -> only ROOT visible
    - rank_cut = "class"   -> expanded down to class
    - rank_cut = "species" -> fully expanded
    """
    if not tree:
        return tree
    
    cut = norm_rank(rank_cut)
    
    if not cut:
        root = shallow_clone(tree)
        children = tree.get("children") or []
        root["children"] = None
        root["_children"] = [collapse_all(c) for c in children] if children else None
        return root
    
    cut_idx = rank_index(cut)
    
    if cut_idx < 0:
        safe = shallow_clone(tree)
        safe["children"] = [collapse_all(c) for c in (tree.get("children") or [])]
        safe["_children"] = None
        return safe
    
    def build(node: Dict[str, Any], parent_idx: int) -> Dict[str, Any]:
        n = shallow_clone(node)
        
        if is_leaf(node):
            n["children"] = None
            n["_children"] = None
            return n
        
        idx = rank_index(node.get("rank"))
        cur_idx = idx if idx >= 0 else parent_idx
        
        if cut_idx == LAST_RANK_INDEX:
            n["children"] = [build(c, cur_idx) for c in node.get("children", [])]
            n["_children"] = None
            return n
        
        if cur_idx < cut_idx:
            n["children"] = [build(c, cur_idx) for c in node.get("children", [])]
            n["_children"] = None
            return n
        
        n["children"] = None
        n["_children"] = [collapse_all(c) for c in node.get("children", [])]
        return n
    
    root_idx = rank_index(tree.get("rank"))
    root_idx = root_idx if root_idx >= 0 else -999
    
    return build(tree, root_idx)


# ============================================================
# Keys and navigation
# ============================================================

def add_keys_to_tree(tree: Dict[str, Any]) -> Dict[str, Any]:
    """Adds 'key' to each node in the tree (recursive)."""
    def walk(node: Dict[str, Any], parts: List[Dict[str, str]]) -> Dict[str, Any]:
        if not node:
            return node
        
        next_parts = parts + [{"rank": node.get("rank", "?"), "name": node.get("name", "")}]
        node["key"] = path_key_from_parts(next_parts)
        
        children = node.get("children") or []
        if children:
            node["children"] = [walk(c, next_parts) for c in children]
        
        _children = node.get("_children") or []
        if _children:
            node["_children"] = [walk(c, next_parts) for c in _children]
        
        return node
    
    return walk(tree, [])


def expand_to_keys(tree: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    """Expands the tree so that paths to the keys are visible."""
    if not tree or not keys:
        return tree
    
    key_set = set(keys)
    all_needed = set()
    for k in keys:
        parts = k.split("|")
        for i in range(1, len(parts) + 1):
            all_needed.add("|".join(parts[:i]))
    
    def walk(node: Dict[str, Any], parts: List[Dict[str, str]]) -> Dict[str, Any]:
        if not node:
            return node
        
        next_parts = parts + [{"rank": node.get("rank", "?"), "name": node.get("name", "")}]
        current_key = path_key_from_parts(next_parts)
        
        needs_expand = any(
            k == current_key or k.startswith(current_key + "|")
            for k in all_needed
        )
        
        if needs_expand:
            children = node.get("children") or []
            _children = node.get("_children") or []
            
            if not children and _children:
                node["children"] = _children
                node["_children"] = None
            
            if node.get("children"):
                node["children"] = [walk(c, next_parts) for c in node["children"]]
        
        return node
    
    return walk(tree, [])


# ============================================================
# Counting and searching
# ============================================================

def count_species_under(node: Dict[str, Any]) -> int:
    """Counts species under a node."""
    if not node:
        return 0
    
    if norm_rank(node.get("rank")) in ("species", "subspecies"):
        return 1
    
    count = 0
    for child in (node.get("children") or []) + (node.get("_children") or []):
        count += count_species_under(child)
    
    return count


def count_visible_nodes(tree: Dict[str, Any]) -> int:
    """Counts visible nodes."""
    if not tree:
        return 0
    
    count = 1
    for child in (tree.get("children") or []):
        count += count_visible_nodes(child)
    
    return count


def find_node_by_key(tree: Dict[str, Any], target_key: str) -> Optional[Dict[str, Any]]:
    """Searches for a node by its key in the tree."""
    if not tree or not target_key:
        return None
    
    def walk(node: Dict[str, Any], parts: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        if not node:
            return None
        
        next_parts = parts + [{"rank": node.get("rank", "?"), "name": node.get("name", "")}]
        current_key = path_key_from_parts(next_parts)
        
        if current_key == target_key:
            return node
        
        if not target_key.startswith(current_key + "|"):
            return None
        
        for child in (node.get("children") or []) + (node.get("_children") or []):
            result = walk(child, next_parts)
            if result:
                return result
        
        return None
    
    return walk(tree, [])


def list_clades_at_rank(
    tree: Dict[str, Any],
    target_rank: str,
    root_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lists all clades of a specific rank under a root."""
    target = norm_rank(target_rank)
    if not tree or not target:
        return []
    
    if root_key:
        tree = find_node_by_key(tree, root_key)
        if not tree:
            return []
    
    results = []
    
    def walk(node: Dict[str, Any], parts: List[Dict[str, str]]):
        if not node:
            return
        
        next_parts = parts + [{"rank": node.get("rank", "?"), "name": node.get("name", "")}]
        
        if norm_rank(node.get("rank")) == target:
            results.append({
                "key": path_key_from_parts(next_parts),
                "name": node.get("name", ""),
                "rank": target,
                "species_count": count_species_under(node),
            })
            return
        
        for child in (node.get("children") or []) + (node.get("_children") or []):
            walk(child, next_parts)
    
    walk(tree, [])
    return results
