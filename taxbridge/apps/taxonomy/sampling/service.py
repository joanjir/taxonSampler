# taxonomy/services/sampling.py
"""
Taxonomic sampling service.
Migrated from sampling_filters.js to centralize logic in the backend.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Set
from functools import lru_cache

from apps.taxonomy.utils import (
    RANK_ORDER,
    LAST_RANK_INDEX,
    norm_rank,
    rank_index,
    path_key_from_parts,
    parse_key_parts,
    is_prefix_key,
    ancestor_key_at_rank,
)


def parent_key_above_rank(key: str, rank: str) -> Optional[str]:
    """Gets the parent key above the specified rank."""
    target = norm_rank(rank)
    parts = parse_key_parts(key)
    
    for i, p in enumerate(parts):
        if p["rank"] == target:
            if i <= 0:
                return None
            return path_key_from_parts(parts[:i])
    return None


# ============================================================
# Indexes and node cache
# ============================================================

class TreeIndex:
    """
    Bidirectional index for fast node lookup by key.
    Built once when loading the tree.
    """
    
    def __init__(self):
        self._node_by_key: Dict[str, Dict[str, Any]] = {}
        self._count_cache: Dict[str, Dict[str, int]] = {}  # key -> {rank -> count}
    
    def build(self, root: Dict[str, Any]) -> None:
        """Builds the index from the tree root."""
        self._node_by_key.clear()
        self._count_cache.clear()
        
        if root:
            self._walk_and_index(root, [])
    
    def _walk_and_index(self, node: Dict[str, Any], parts: List[Dict[str, str]]) -> None:
        """Walks the tree indexing each node."""
        next_parts = parts + [{"rank": node.get("rank", "?"), "name": node.get("name", "")}]
        key = path_key_from_parts(next_parts)
        
        self._node_by_key[key] = node
        
        children = node.get("children") or []
        for child in children:
            self._walk_and_index(child, next_parts)
    
    def get_node(self, key: str) -> Optional[Dict[str, Any]]:
        """Gets a node by its key."""
        return self._node_by_key.get(key)
    
    def get_key(self, node: Dict[str, Any]) -> Optional[str]:
        """Gets the key of a node (reverse lookup)."""
        # O(n) lookup, but we generally use get_node
        for k, n in self._node_by_key.items():
            if n is node:
                return k
        return None
    
    def count_rank_under(self, node: Dict[str, Any], target_rank: str) -> int:
        """Counts nodes of a specific rank under a node (memoized)."""
        if not node:
            return 0
        
        # We use the dict id as identifier (for memoization)
        node_id = id(node)
        target = norm_rank(target_rank)
        
        cache_key = f"{node_id}"
        if cache_key not in self._count_cache:
            self._count_cache[cache_key] = {}
        
        if target in self._count_cache[cache_key]:
            return self._count_cache[cache_key][target]
        
        count = self._count_recursive(node, target)
        self._count_cache[cache_key][target] = count
        return count
    
    def _count_recursive(self, node: Dict[str, Any], target_rank: str) -> int:
        """Recursively counts nodes of the given rank."""
        if not node:
            return 0
        
        rank = norm_rank(node.get("rank", ""))
        # When counting "species", also include infraspecific ranks
        if target_rank == "species":
            count = 1 if rank in ("species", "subspecies", "variety", "form") else 0
        else:
            count = 1 if rank == target_rank else 0
        
        children = node.get("children") or []
        for child in children:
            count += self._count_recursive(child, target_rank)
        
        return count


def list_nodes_at_rank_under(root: Dict[str, Any], target_rank: str) -> List[Dict[str, Any]]:
    """Lists all nodes of a specific rank under root."""
    target = norm_rank(target_rank)
    if not root:
        return []
    
    result = []
    stack = [root]
    
    while stack:
        node = stack.pop()
        if not node:
            continue
        
        rank = norm_rank(node.get("rank", ""))
        if rank == target:
            result.append(node)
        
        children = node.get("children") or []
        for child in reversed(children):
            stack.append(child)
    
    return result


# ============================================================
# Quota Calculation
# ============================================================

@dataclass
class CladeQuota:
    """Represents a clade with its assigned quota."""
    key: str
    name: str
    rank: str
    species: int
    quota: int
    node: Optional[Dict[str, Any]] = None


def compute_quotas(
    K: int,
    allocation: str,
    min_one_per_clade: bool,
    clades: List[Dict[str, Any]]
) -> Tuple[List[CladeQuota], str]:
    """
    Calculates the distribution of K species among clades.
    
    Args:
        K: Total number of species to select
        allocation: "balanced" or "proportional"
        min_one_per_clade: If True, guarantees at least 1 per clade
        clades: List of {key, name, rank, species, node}
    
    Returns:
        Tuple of (list of CladeQuota, note/message)
    """
    # Filter clades with species and sort by richness descending
    items = [c for c in clades if (c.get("species") or 0) > 0]
    items.sort(key=lambda c: c.get("species", 0), reverse=True)
    
    m = len(items)
    if m == 0:
        return [], "no clades with species"
    
    quotas = [0] * m
    
    # Special case: K < number of clades with minOnePerClade
    if min_one_per_clade and K < m:
        for i in range(min(K, m)):
            quotas[i] = 1
        return [
            CladeQuota(
                key=items[i].get("key", ""),
                name=items[i].get("name", ""),
                rank=items[i].get("rank", ""),
                species=items[i].get("species", 0),
                quota=quotas[i],
                node=items[i].get("node")
            )
            for i in range(m)
        ], f"minOnePerClade ON but K ({K}) < #clades ({m}) => assigned 1 to top-K clades only"
    
    # Distribution according to mode
    if allocation == "balanced":
        base = K // m
        rem = K % m
        for i in range(m):
            quotas[i] = base + (1 if i < rem else 0)
    else:
        # Proportional to richness
        total = sum(c.get("species", 0) for c in items) or 1
        raw = [(K * c.get("species", 0)) / total for c in items]
        
        # Floor values
        floor_vals = [int(x) for x in raw]
        quotas = floor_vals.copy()
        
        # Distribute remainder by highest fractions
        used = sum(floor_vals)
        rem = K - used
        
        frac_order = sorted(
            range(len(raw)),
            key=lambda i: raw[i] - floor_vals[i],
            reverse=True
        )
        
        for k in range(min(rem, len(frac_order))):
            quotas[frac_order[k]] += 1
    
    # Apply minimum 1 per clade if enabled
    if min_one_per_clade:
        for i in range(m):
            quotas[i] = max(1, quotas[i])
        
        # Reduce if exceeds K
        total_sum = sum(quotas)
        while total_sum > K:
            reduced = False
            for i in range(m - 1, -1, -1):
                if total_sum <= K:
                    break
                if quotas[i] > 1:
                    quotas[i] -= 1
                    total_sum -= 1
                    reduced = True
            if not reduced:
                break
    
    # Limit quota to available species
    for i in range(m):
        quotas[i] = min(quotas[i], items[i].get("species", 0))
    
    result = [
        CladeQuota(
            key=items[i].get("key", ""),
            name=items[i].get("name", ""),
            rank=items[i].get("rank", ""),
            species=items[i].get("species", 0),
            quota=quotas[i],
            node=items[i].get("node")
        )
        for i in range(m)
    ]
    
    return result, "ok"


# ============================================================
# Tip Selection (species)
# ============================================================

def pick_tips_in_clade(
    clade_node: Dict[str, Any],
    target_rank: str,
    quota: int,
    index: TreeIndex
) -> List[Dict[str, str]]:
    """
    Deterministically selects `quota` tips of the given rank under the clade.
    Sorted alphabetically by key for reproducibility.
    """
    tips = list_nodes_at_rank_under(clade_node, target_rank)
    
    enriched = []
    for n in tips:
        key = index.get_key(n) or f"{norm_rank(n.get('rank', '?'))}:{n.get('name', '')}"
        enriched.append({
            "name": n.get("name", ""),
            "rank": norm_rank(n.get("rank", "")),
            "key": key,
        })
    
    # Sort by key and take quota
    enriched.sort(key=lambda x: x["key"])
    selected = enriched[:quota]
    
    return [{"name": x["name"], "rank": x["rank"], "key": x["key"]} for x in selected]


# ============================================================
# Ingroup Sampling
# ============================================================

@dataclass
class IngroupResult:
    """Ingroup sampling result."""
    note: str
    allocation_rank: str
    target_rank: str
    quotas: List[Dict[str, Any]]
    picked: List[Dict[str, str]]
    scope_root_key: Optional[str]
    extra: Dict[str, Any] = field(default_factory=dict)


def run_ingroup_sampling(
    config: Dict[str, Any],
    scope_node: Dict[str, Any],
    scope_root_key: Optional[str],
    target_keys: List[str],
    index: TreeIndex
) -> IngroupResult:
    """
    Executes ingroup sampling.
    
    Args:
        config: {K, allocation_rank, target_rank, allocation, min_one_per_clade}
        scope_node: Root node of the scope
        scope_root_key: Key of the scope root
        target_keys: List of target clade keys (optional)
        index: TreeIndex for lookups
    
    Returns:
        IngroupResult with the selected taxa
    """
    alloc_rank = norm_rank(config.get("allocation_rank", "family"))
    target_rank = norm_rank(config.get("target_rank", "species"))
    K = max(2, int(config.get("K", 50)))
    allocation = config.get("allocation", "proportional")
    min_one_per_clade = bool(config.get("min_one_per_clade", True))
    
    targets = [k for k in (target_keys or []) if k]
    use_targets = len(targets) > 0
    
    # Resolve target scopes
    target_scopes = []
    if use_targets:
        for k in targets:
            node = index.get_node(k)
            if not node:
                continue
            sp = index.count_rank_under(node, "species")
            if sp > 0:
                target_scopes.append({
                    "key": k,
                    "node": node,
                    "species": sp,
                    "name": node.get("name", ""),
                    "rank": norm_rank(node.get("rank", ""))
                })
    
    # If there are no valid targets, use the full scope
    if not target_scopes:
        target_scopes = [{
            "key": scope_root_key,
            "node": scope_node,
            "species": index.count_rank_under(scope_node, "species"),
            "name": scope_node.get("name", "") if scope_node else "",
            "rank": norm_rank(scope_node.get("rank", "")) if scope_node else ""
        }]
    
    # Distribute K among scopes
    total_species_scopes = sum(s["species"] for s in target_scopes) or 1
    
    if len(target_scopes) == 1:
        scopes_with_k = [{"K": K, **target_scopes[0]}]
    elif allocation == "balanced":
        m = len(target_scopes)
        base = K // m
        rem = K % m
        scopes_with_k = [
            {"K": base + (1 if i < rem else 0), **s}
            for i, s in enumerate(target_scopes)
        ]
    else:
        # Proportional
        raw = [(K * s["species"]) / total_species_scopes for s in target_scopes]
        floor_vals = [int(x) for x in raw]
        used = sum(floor_vals)
        rem = K - used
        
        frac_order = sorted(
            range(len(raw)),
            key=lambda i: raw[i] - floor_vals[i],
            reverse=True
        )
        
        k_arr = floor_vals.copy()
        for k in range(min(rem, len(frac_order))):
            k_arr[frac_order[k]] += 1
        
        scopes_with_k = [
            {"K": max(1, k_arr[i]), **s}
            for i, s in enumerate(target_scopes)
        ]
    
    # Sample each scope
    picked_by_scopes = []
    for scope in scopes_with_k:
        scope_rank = norm_rank(scope["node"].get("rank", "") if scope["node"] else "")
        
        # Get nodes at allocation rank
        if scope["node"] and scope_rank == alloc_rank:
            alloc_nodes = [scope["node"]]
        else:
            alloc_nodes = list_nodes_at_rank_under(scope["node"], alloc_rank)
        
        # Build list of clades
        clades = []
        for n in alloc_nodes:
            key = index.get_key(n) or f"{alloc_rank}:{n.get('name', '')}"
            species = index.count_rank_under(n, "species")
            clades.append({
                "key": key,
                "name": n.get("name", ""),
                "rank": alloc_rank,
                "species": species,
                "node": n
            })
        
        # Calculate quotas
        quota_result, note = compute_quotas(scope["K"], allocation, min_one_per_clade, clades)
        
        # Select tips per clade
        picked_by_clade = []
        for qrow in quota_result:
            picked = pick_tips_in_clade(qrow.node, target_rank, qrow.quota, index)
            picked_by_clade.append({
                "key": qrow.key,
                "name": qrow.name,
                "rank": qrow.rank,
                "species_avail": qrow.species,
                "quota": qrow.quota,
                "picked": picked
            })
        
        flat = []
        for c in picked_by_clade:
            flat.extend(c["picked"])
        
        picked_by_scopes.append({
            "scope_key": scope["key"],
            "scope_name": scope["name"],
            "scope_rank": scope["rank"],
            "K": scope["K"],
            "note": note,
            "quotas": picked_by_clade,
            "picked": flat
        })
    
    # Merge and deduplicate
    seen: Set[str] = set()
    ingroup_picked = []
    for blk in picked_by_scopes:
        for t in blk["picked"]:
            if not t.get("key") or t["key"] in seen:
                continue
            seen.add(t["key"])
            ingroup_picked.append(t)
    
    return IngroupResult(
        note="targets" if len(scopes_with_k) > 1 else (picked_by_scopes[0]["note"] if picked_by_scopes else "ok"),
        allocation_rank=alloc_rank,
        target_rank=target_rank,
        quotas=picked_by_scopes[0]["quotas"] if picked_by_scopes else [],
        picked=ingroup_picked,
        scope_root_key=scope_root_key,
        extra={
            "scopes": picked_by_scopes,
            "targets_used": targets
        }
    )


# ============================================================
# Outgroup Sampling
# ============================================================

@dataclass
class OutgroupResult:
    """Outgroup sampling result."""
    picked: List[Dict[str, str]]
    meta: Dict[str, Any]


def run_outgroup_sampling(
    config: Dict[str, Any],
    scope_root_key: Optional[str],
    target_rank: str,
    index: TreeIndex
) -> OutgroupResult:
    """
    Executes outgroup sampling.
    
    Args:
        config: {outgroup_rank, outgroup_n}
        scope_root_key: Key of the scope root
        target_rank: Rank of species to sample
        index: TreeIndex for lookups
    
    Returns:
        OutgroupResult with the selected taxa
    """
    out_rank = norm_rank(config.get("outgroup_rank", ""))
    n = int(config.get("outgroup_n", 2))
    
    if not out_rank:
        return OutgroupResult(
            picked=[],
            meta={"rank_distance": None, "n": n}
        )
    
    if not scope_root_key:
        return OutgroupResult(
            picked=[],
            meta={"rank_distance": out_rank, "n": n, "note": "no scope_root_key"}
        )
    
    scope_at_out = ancestor_key_at_rank(scope_root_key, out_rank)
    parent_key = parent_key_above_rank(scope_root_key, out_rank)
    parent_node = index.get_node(parent_key) if parent_key else None
    
    if not parent_node:
        return OutgroupResult(
            picked=[],
            meta={"rank_distance": out_rank, "n": n, "note": "parent not found"}
        )
    
    # Get candidate clades
    cand_nodes = list_nodes_at_rank_under(parent_node, out_rank)
    
    candidates = []
    for node in cand_nodes:
        key = index.get_key(node) or f"{out_rank}:{node.get('name', '')}"
        species = index.count_rank_under(node, "species")
        
        if species <= 0:
            continue
        if scope_at_out and key == scope_at_out:
            continue
        
        candidates.append({
            "node": node,
            "name": node.get("name", ""),
            "rank": out_rank,
            "key": key,
            "species": species
        })
    
    # Sort by richness descending, then by key
    candidates.sort(key=lambda c: (-c["species"], c["key"]))
    
    if not candidates:
        return OutgroupResult(
            picked=[],
            meta={"rank_distance": out_rank, "n": n, "note": "no candidates"}
        )
    
    # Select outgroup
    outgroup_picked = []
    idx = 0
    max_iterations = n * 10
    
    while len(outgroup_picked) < n and candidates and idx < max_iterations:
        c = candidates[idx % len(candidates)]
        picks = pick_tips_in_clade(c["node"], norm_rank(target_rank), 1, index)
        if picks:
            outgroup_picked.append(picks[0])
        idx += 1
    
    return OutgroupResult(
        picked=outgroup_picked,
        meta={"rank_distance": out_rank, "n": n, "candidates": len(candidates)}
    )


# ============================================================
# Main API
# ============================================================

@dataclass
class SamplingResult:
    """Complete sampling result."""
    ingroup: IngroupResult
    outgroup: OutgroupResult


def run_sampling(
    tree_data: Dict[str, Any],
    config: Dict[str, Any]
) -> SamplingResult:
    """
    Executes complete sampling (ingroup + outgroup).
    
    Args:
        tree_data: Complete tree (dict with children)
        config: {
            scope_key: str (optional),
            targets: List[str] (optional),
            K: int,
            allocation_rank: str,
            target_rank: str,
            allocation: "balanced" | "proportional",
            min_one_per_clade: bool,
            outgroup_rank: str (optional),
            outgroup_n: int
        }
    
    Returns:
        SamplingResult with ingroup and outgroup
    """
    # Build index
    index = TreeIndex()
    index.build(tree_data)
    
    # Resolve scope
    scope_key = config.get("scope_key")
    if scope_key:
        scope_node = index.get_node(scope_key)
    else:
        scope_node = tree_data
    
    if not scope_node:
        scope_node = tree_data
        scope_key = None
    
    # Ingroup
    ingroup = run_ingroup_sampling(
        config=config,
        scope_node=scope_node,
        scope_root_key=scope_key,
        target_keys=config.get("target_keys", []),
        index=index
    )
    
    # Outgroup
    outgroup = run_outgroup_sampling(
        config=config,
        scope_root_key=scope_key,
        target_rank=config.get("target_rank", "species"),
        index=index
    )
    
    return SamplingResult(ingroup=ingroup, outgroup=outgroup)
