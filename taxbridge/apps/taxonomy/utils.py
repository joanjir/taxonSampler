# apps/taxonomy/utils.py
"""
Pure taxonomy utilities (no model dependencies).

Functions for manipulation of taxonomic ranks and keys.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# Global taxonomy constants
# ============================================================

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

ROOT_RANKS = {"domain", "superkingdom", "kingdom"}

LAST_RANK_INDEX = len(RANK_ORDER) - 1


# ============================================================
# Rank normalization functions
# ============================================================

def norm_rank(rank: Optional[str]) -> str:
    """Normalizes a rank to lowercase."""
    return (rank or "").strip().lower()


def rank_index(rank: Optional[str]) -> int:
    """Returns the index of the rank in RANK_ORDER, or -1 if not found."""
    r = norm_rank(rank)
    try:
        return RANK_ORDER.index(r)
    except ValueError:
        return -1


def is_valid_rank(rank: Optional[str]) -> bool:
    """Checks if a rank is valid."""
    return rank_index(rank) >= 0


def rank_depth(rank: Optional[str]) -> int:
    """Returns the depth of the rank (synonym of rank_index)."""
    return rank_index(rank)


# ============================================================
# Key handling functions (path-based keys)
# ============================================================

def path_key_from_parts(parts: List[Dict[str, str]]) -> str:
    """
    Builds a key path from parts [{rank, name}, ...].
    
    Example:
        >>> path_key_from_parts([{"rank": "dataset", "name": "Root"}, {"rank": "kingdom", "name": "Animalia"}])
        "dataset:Root|kingdom:Animalia"
    """
    return "|".join(
        f"{norm_rank(p.get('rank', '?'))}:{p.get('name', '')}"
        for p in parts
    )


def parse_key_parts(key: str) -> List[Dict[str, str]]:
    """
    Parses a key path to a list of {rank, name}.
    
    Example:
        >>> parse_key_parts("dataset:Root|kingdom:Animalia")
        [{"rank": "dataset", "name": "Root"}, {"rank": "kingdom", "name": "Animalia"}]
    """
    s = (key or "").strip()
    if not s:
        return []
    
    parts = []
    for seg in s.split("|"):
        idx = seg.find(":")
        if idx < 0:
            parts.append({"rank": norm_rank(seg), "name": ""})
        else:
            parts.append({
                "rank": norm_rank(seg[:idx]),
                "name": seg[idx + 1:]
            })
    return parts


def is_prefix_key(parent_key: str, child_key: str) -> bool:
    """Checks if parent_key is a prefix of child_key."""
    if not parent_key or not child_key:
        return False
    if parent_key == child_key:
        return True
    return child_key.startswith(parent_key + "|")


def key_depth(key: str) -> int:
    """Returns the depth of the key (number of segments)."""
    if not key:
        return 0
    return len(key.split("|"))


def get_parent_key(key: str) -> Optional[str]:
    """Gets the parent key."""
    parts = key.rsplit("|", 1)
    return parts[0] if len(parts) > 1 else None


def ancestor_key_at_rank(key: str, rank: str) -> Optional[str]:
    """Gets the ancestor of a key at the specified rank."""
    target = norm_rank(rank)
    parts = parse_key_parts(key)
    
    for i, p in enumerate(parts):
        if p["rank"] == target:
            return path_key_from_parts(parts[:i + 1])
    return None


# ============================================================
# classification_path normalization functions
# ============================================================

def _is_path_leaf_to_root(path: List[Dict[str, Any]]) -> bool:
    """Detects if the path is in leaf->root order."""
    if not path:
        return False
    last_rank = (path[-1].get("rank") or "").strip().lower()
    return last_rank in ROOT_RANKS


def normalize_classification_path(path: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """
    Normalizes a classification_path to a list of (rank, name).
    Handles paths in both directions and removes duplicates.
    """
    if not isinstance(path, list):
        return []
    
    clean: List[Tuple[str, str]] = []
    for x in path:
        if not isinstance(x, dict):
            continue
        rank = (x.get("rank") or "").strip()
        name = (x.get("name") or "").strip()
        if not rank or not name:
            continue
        clean.append((rank.lower(), name))
    
    # Reverse if in leaf->root order
    if _is_path_leaf_to_root(path):
        clean.reverse()
    
    # Remove consecutive duplicates
    out: List[Tuple[str, str]] = []
    prev = None
    for item in clean:
        if item != prev:
            out.append(item)
        prev = item
    
    return out


def parts_to_label(parts: List[Dict[str, str]]) -> str:
    """Generates a readable label from parts."""
    return " / ".join([f"{p.get('rank') or '?'}:{p.get('name') or ''}" for p in parts])


# ============================================================
# ETE3 Tree Utilities (Orthology)
# ============================================================
import re


def _parse_orthology_key_path(key: str) -> List[Tuple[str, str]]:
    """
    Expected key: "rank:name|rank:name|...".
    Returns list [(rank_lower, name_str), ...] in order.
    """
    if not key:
        return []
    out = []
    for seg in key.split("|"):
        seg = seg.strip()
        if not seg or ":" not in seg:
            continue
        r, name = seg.split(":", 1)
        out.append((r.strip().lower(), name.strip()))
    return out


def _safe_token(label: str) -> str:
    """
    Sanitizes to a compatible identifier (ETE3 + Newick + orthology pipelines):
    - no spaces
    - safe characters: A-Za-z0-9_.-
    """
    s = (label or "").strip().replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9_.-]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "Unknown"


def _safe_internal(rank: str, tax: str) -> str:
    """
    Internal node name: rank__Taxon (rank optional, but useful for debug/visualization).
    """
    r = _safe_token(rank.lower() if rank else "node")
    t = _safe_token(tax)
    return f"{r}__{t}" if t else r


def _dedupe_name(name: str, used: dict) -> str:
    """
    Avoids label collisions in leaves (and optionally, in internal nodes too).
    """
    base = name or "Unknown"
    if base in used:
        used[base] += 1
        return f"{base}__{used[base]}"
    used[base] = 1
    return base


def sampling_to_tree_artifacts(
    sampling: dict,
    include_outgroup: bool = True,
    branch_len: float = 1.0,
    with_branch_lengths: bool = False,
    internal_name_style: str = "rank__taxon",
) -> Tuple[str, Dict[str, Any]]:
    """
    Produces an "ETE3-safe" and "ortho-safe" tree from a sampling dict:

    - Leaves: ONLY species (clean identifier) => ideal for OrthoFinder/OMA/FastOMA.
    - Internal nodes: higher taxa, optionally with rank (useful for debugging).
    - No spaces or special characters.
    - Branch lengths: constant (cladogram) if with_branch_lengths=True.

    Returns: (newick_str, tree_json)
    """
    from ete3 import Tree

    ing = sampling.get("ingroup", {}).get("picked", []) or []
    out = sampling.get("outgroupPicked", []) or []
    picked = list(ing) + (list(out) if include_outgroup else [])
    if not picked:
        raise ValueError("Empty sampling: no selected taxa.")

    root = Tree()
    root.name = "Root"
    root.dist = 0.0

    # index to reuse internal nodes by accumulated path (excluding species)
    node_index = {"": root}

    # to deduplicate leaves and avoid collisions
    used_leaf_names: Dict[str, int] = {}

    for it in picked:
        key = it.get("key") or ""
        name = it.get("name") or ""
        rank_hint = (it.get("rank") or "").strip().lower()

        path = _parse_orthology_key_path(key)

        # fallback: if no path, treat as species
        if not path:
            leaf_name = _dedupe_name(_safe_token(name), used_leaf_names)
            leaf = root.add_child(name=leaf_name)
            leaf.add_feature("rank", "species")
            leaf.dist = branch_len if with_branch_lengths else 0.0
            continue

        # Build internal nodes up to the parent of species.
        acc = []
        parent = root
        species_tax = None

        for (rank, tax) in path:
            if rank == "species":
                species_tax = tax
                break

            # internal key accumulator (only ranks != species)
            acc.append(f"{rank}:{tax}")
            acc_key = "|".join(acc)

            if acc_key in node_index:
                parent = node_index[acc_key]
                continue

            if internal_name_style == "taxon":
                internal_name = _safe_token(tax)
            else:
                internal_name = _safe_internal(rank, tax)

            n = parent.add_child(name=internal_name)
            n.add_feature("rank", rank)
            n.dist = branch_len if with_branch_lengths else 0.0

            node_index[acc_key] = n
            parent = n

        # Determine species (priority: species from path)
        if not species_tax:
            if rank_hint == "species":
                species_tax = name
            else:
                species_tax = name

        leaf_name = _dedupe_name(_safe_token(species_tax), used_leaf_names)
        leaf = parent.add_child(name=leaf_name)
        leaf.add_feature("rank", "species")
        leaf.dist = branch_len if with_branch_lengths else 0.0

    # Export Newick
    newick = root.write(format=9 if not with_branch_lengths else 1).strip()

    def to_json(n: Tree) -> Dict[str, Any]:
        obj: Dict[str, Any] = {"name": n.name, "rank": getattr(n, "rank", None)}
        if n.children:
            obj["children"] = [to_json(c) for c in n.children]
        return obj

    tree_json = to_json(root)
    return newick, tree_json
