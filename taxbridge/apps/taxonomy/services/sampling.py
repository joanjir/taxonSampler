# taxonomy/services/sampling.py
"""
Servicio de muestreo taxonómico (Sampling).
Migrado desde sampling_filters.js para centralizar lógica en backend.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Set
from functools import lru_cache

from apps.taxonomy.services.taxonomy_core import (
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
    """Obtiene el key padre por encima del rank especificado."""
    target = norm_rank(rank)
    parts = parse_key_parts(key)
    
    for i, p in enumerate(parts):
        if p["rank"] == target:
            if i <= 0:
                return None
            return path_key_from_parts(parts[:i])
    return None


# ============================================================
# Índices y cache de nodos
# ============================================================

class TreeIndex:
    """
    Índice bidireccional para búsqueda rápida de nodos por key.
    Construido una vez al cargar el árbol.
    """
    
    def __init__(self):
        self._node_by_key: Dict[str, Dict[str, Any]] = {}
        self._count_cache: Dict[str, Dict[str, int]] = {}  # key -> {rank -> count}
    
    def build(self, root: Dict[str, Any]) -> None:
        """Construye el índice desde la raíz del árbol."""
        self._node_by_key.clear()
        self._count_cache.clear()
        
        if root:
            self._walk_and_index(root, [])
    
    def _walk_and_index(self, node: Dict[str, Any], parts: List[Dict[str, str]]) -> None:
        """Recorre el árbol indexando cada nodo."""
        next_parts = parts + [{"rank": node.get("rank", "?"), "name": node.get("name", "")}]
        key = path_key_from_parts(next_parts)
        
        self._node_by_key[key] = node
        
        children = node.get("children") or []
        for child in children:
            self._walk_and_index(child, next_parts)
    
    def get_node(self, key: str) -> Optional[Dict[str, Any]]:
        """Obtiene un nodo por su key."""
        return self._node_by_key.get(key)
    
    def get_key(self, node: Dict[str, Any]) -> Optional[str]:
        """Obtiene el key de un nodo (búsqueda inversa)."""
        # Búsqueda O(n), pero generalmente usamos get_node
        for k, n in self._node_by_key.items():
            if n is node:
                return k
        return None
    
    def count_rank_under(self, node: Dict[str, Any], target_rank: str) -> int:
        """Cuenta nodos de un rank específico bajo un nodo (memoizado)."""
        if not node:
            return 0
        
        # Usamos id del dict como identificador (para memo)
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
        """Cuenta recursivamente nodos del rank dado."""
        if not node:
            return 0
        
        rank = norm_rank(node.get("rank", ""))
        count = 1 if rank == target_rank else 0
        
        children = node.get("children") or []
        for child in children:
            count += self._count_recursive(child, target_rank)
        
        return count


def list_nodes_at_rank_under(root: Dict[str, Any], target_rank: str) -> List[Dict[str, Any]]:
    """Lista todos los nodos de un rank específico bajo root."""
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
# Cálculo de Quotas
# ============================================================

@dataclass
class CladeQuota:
    """Representa un clado con su quota asignada."""
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
    Calcula la distribución de K especies entre clados.
    
    Args:
        K: Total de especies a seleccionar
        allocation: "balanced" o "proportional"
        min_one_per_clade: Si True, garantiza al menos 1 por clado
        clades: Lista de {key, name, rank, species, node}
    
    Returns:
        Tuple de (lista de CladeQuota, nota/mensaje)
    """
    # Filtrar clados con especies y ordenar por riqueza descendente
    items = [c for c in clades if (c.get("species") or 0) > 0]
    items.sort(key=lambda c: c.get("species", 0), reverse=True)
    
    m = len(items)
    if m == 0:
        return [], "no clades with species"
    
    quotas = [0] * m
    
    # Caso especial: K < número de clados con minOnePerClade
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
    
    # Distribución según modo
    if allocation == "balanced":
        base = K // m
        rem = K % m
        for i in range(m):
            quotas[i] = base + (1 if i < rem else 0)
    else:
        # Proporcional a la riqueza
        total = sum(c.get("species", 0) for c in items) or 1
        raw = [(K * c.get("species", 0)) / total for c in items]
        
        # Floor values
        floor_vals = [int(x) for x in raw]
        quotas = floor_vals.copy()
        
        # Distribuir resto por fracciones más altas
        used = sum(floor_vals)
        rem = K - used
        
        frac_order = sorted(
            range(len(raw)),
            key=lambda i: raw[i] - floor_vals[i],
            reverse=True
        )
        
        for k in range(min(rem, len(frac_order))):
            quotas[frac_order[k]] += 1
    
    # Aplicar mínimo 1 por clado si está habilitado
    if min_one_per_clade:
        for i in range(m):
            quotas[i] = max(1, quotas[i])
        
        # Reducir si excede K
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
    
    # Limitar quota a especies disponibles
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
# Selección de Tips (especies)
# ============================================================

def pick_tips_in_clade(
    clade_node: Dict[str, Any],
    target_rank: str,
    quota: int,
    index: TreeIndex
) -> List[Dict[str, str]]:
    """
    Selecciona determinísticamente `quota` tips del rank dado bajo el clado.
    Ordenados alfabéticamente por key para reproducibilidad.
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
    
    # Ordenar por key y tomar quota
    enriched.sort(key=lambda x: x["key"])
    selected = enriched[:quota]
    
    return [{"name": x["name"], "rank": x["rank"], "key": x["key"]} for x in selected]


# ============================================================
# Ingroup Sampling
# ============================================================

@dataclass
class IngroupResult:
    """Resultado del muestreo de ingroup."""
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
    Ejecuta el muestreo de ingroup.
    
    Args:
        config: {K, allocation_rank, target_rank, allocation, min_one_per_clade}
        scope_node: Nodo raíz del scope
        scope_root_key: Key del scope root
        target_keys: Lista de keys de clados objetivo (opcional)
        index: TreeIndex para búsquedas
    
    Returns:
        IngroupResult con los taxa seleccionados
    """
    alloc_rank = norm_rank(config.get("allocation_rank", "family"))
    target_rank = norm_rank(config.get("target_rank", "species"))
    K = max(2, int(config.get("K", 50)))
    allocation = config.get("allocation", "proportional")
    min_one_per_clade = bool(config.get("min_one_per_clade", True))
    
    targets = [k for k in (target_keys or []) if k]
    use_targets = len(targets) > 0
    
    # Resolver target scopes
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
    
    # Si no hay targets válidos, usar el scope completo
    if not target_scopes:
        target_scopes = [{
            "key": scope_root_key,
            "node": scope_node,
            "species": index.count_rank_under(scope_node, "species"),
            "name": scope_node.get("name", "") if scope_node else "",
            "rank": norm_rank(scope_node.get("rank", "")) if scope_node else ""
        }]
    
    # Distribuir K entre scopes
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
        # Proporcional
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
    
    # Muestrear cada scope
    picked_by_scopes = []
    for scope in scopes_with_k:
        scope_rank = norm_rank(scope["node"].get("rank", "") if scope["node"] else "")
        
        # Obtener nodos de allocation rank
        if scope["node"] and scope_rank == alloc_rank:
            alloc_nodes = [scope["node"]]
        else:
            alloc_nodes = list_nodes_at_rank_under(scope["node"], alloc_rank)
        
        # Construir lista de clados
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
        
        # Calcular quotas
        quota_result, note = compute_quotas(scope["K"], allocation, min_one_per_clade, clades)
        
        # Seleccionar tips por clado
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
    
    # Merge y deduplicar
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
    """Resultado del muestreo de outgroup."""
    picked: List[Dict[str, str]]
    meta: Dict[str, Any]


def run_outgroup_sampling(
    config: Dict[str, Any],
    scope_root_key: Optional[str],
    target_rank: str,
    index: TreeIndex
) -> OutgroupResult:
    """
    Ejecuta el muestreo de outgroup.
    
    Args:
        config: {outgroup_rank, outgroup_n}
        scope_root_key: Key del scope root
        target_rank: Rank de las especies a muestrear
        index: TreeIndex para búsquedas
    
    Returns:
        OutgroupResult con los taxa seleccionados
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
    
    # Obtener clados candidatos
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
    
    # Ordenar por riqueza descendente, luego por key
    candidates.sort(key=lambda c: (-c["species"], c["key"]))
    
    if not candidates:
        return OutgroupResult(
            picked=[],
            meta={"rank_distance": out_rank, "n": n, "note": "no candidates"}
        )
    
    # Seleccionar outgroup
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
# API Principal
# ============================================================

@dataclass
class SamplingResult:
    """Resultado completo del muestreo."""
    ingroup: IngroupResult
    outgroup: OutgroupResult


def run_sampling(
    tree_data: Dict[str, Any],
    config: Dict[str, Any]
) -> SamplingResult:
    """
    Ejecuta el muestreo completo (ingroup + outgroup).
    
    Args:
        tree_data: Árbol completo (dict con children)
        config: {
            scope_key: str (opcional),
            targets: List[str] (opcional),
            K: int,
            allocation_rank: str,
            target_rank: str,
            allocation: "balanced" | "proportional",
            min_one_per_clade: bool,
            outgroup_rank: str (opcional),
            outgroup_n: int
        }
    
    Returns:
        SamplingResult con ingroup y outgroup
    """
    # Construir índice
    index = TreeIndex()
    index.build(tree_data)
    
    # Resolver scope
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
        target_keys=config.get("targets", []),
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
