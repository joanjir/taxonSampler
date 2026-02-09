# apps/taxonomy/services/tree_queries.py
"""
Servicio de consultas sobre el árbol taxonómico.
Proporciona funciones para buscar nodos, contar especies, listar clados, etc.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass

from apps.taxonomy.models import ExternalTaxon

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


def norm_rank(rank: Optional[str]) -> str:
    """Normaliza un rank a lowercase."""
    return (rank or "").strip().lower()


def rank_index(rank: Optional[str]) -> int:
    """Devuelve el índice del rank en RANK_ORDER, o -1 si no existe."""
    r = norm_rank(rank)
    try:
        return RANK_ORDER.index(r)
    except ValueError:
        return -1


# ============================================================
# Utilidades de Keys
# ============================================================

def path_key_from_parts(parts: List[Dict[str, str]]) -> str:
    """Construye un key path desde partes [{rank, name}, ...]."""
    return "|".join(
        f"{norm_rank(p.get('rank', '?'))}:{p.get('name', '')}"
        for p in parts
    )


def parse_key_parts(key: str) -> List[Dict[str, str]]:
    """Parsea un key path a lista de {rank, name}."""
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


def key_depth(key: str) -> int:
    """Devuelve la profundidad del key (número de segmentos)."""
    if not key:
        return 0
    return len(key.split("|"))


def is_prefix_key(parent_key: str, child_key: str) -> bool:
    """Verifica si parent_key es prefijo de child_key."""
    if not parent_key or not child_key:
        return False
    if parent_key == child_key:
        return True
    return child_key.startswith(parent_key + "|")


def get_parent_key(key: str) -> Optional[str]:
    """Obtiene el key del padre."""
    parts = key.rsplit("|", 1)
    return parts[0] if len(parts) > 1 else None


# ============================================================
# Path Normalization (desde classification_path)
# ============================================================

def _is_leaf_to_root(path: List[Dict[str, Any]]) -> bool:
    """Detecta si el path viene en orden leaf->root."""
    if not path:
        return False
    last_rank = (path[-1].get("rank") or "").strip().lower()
    return last_rank in ROOT_RANKS


def normalize_classification_path(path: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """
    Normaliza un classification_path a lista de (rank, name).
    Maneja paths en ambas direcciones y elimina duplicados.
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
    
    # Invertir si viene leaf->root
    if _is_leaf_to_root(path):
        clean.reverse()
    
    # Quitar duplicados consecutivos
    out: List[Tuple[str, str]] = []
    prev = None
    for item in clean:
        if item != prev:
            out.append(item)
        prev = item
    
    return out


# ============================================================
# Dataclasses para resultados
# ============================================================

@dataclass
class NodeInfo:
    """Información de un nodo."""
    key: str
    name: str
    rank: str
    species_count: int
    has_children: bool
    id: Optional[int] = None
    external_id: Optional[str] = None
    label: Optional[str] = None


@dataclass
class CladeInfo:
    """Información de un clado."""
    key: str
    name: str
    rank: str
    species_count: int
    has_children: bool


@dataclass
class SearchHit:
    """Resultado de búsqueda."""
    key: str
    name: str
    rank: str
    id: Optional[int]
    external_id: Optional[str]
    label: str
    kind: str  # "species" | "node"


# ============================================================
# Funciones sobre árboles en memoria (dict)
# ============================================================

def find_node_by_key(tree: Dict[str, Any], target_key: str) -> Optional[Dict[str, Any]]:
    """
    Busca un nodo por su key en un árbol en memoria.
    
    Args:
        tree: Árbol como dict con "children"
        target_key: Key a buscar (formato "rank:name|rank:name|...")
    
    Returns:
        El nodo si se encuentra, None si no
    """
    if not tree or not target_key:
        return None
    
    def walk(node: Dict[str, Any], parts: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        next_parts = parts + [{"rank": node.get("rank", "?"), "name": node.get("name", "")}]
        key = path_key_from_parts(next_parts)
        
        if key == target_key:
            return node
        
        children = node.get("children") or []
        for child in children:
            result = walk(child, next_parts)
            if result:
                return result
        
        return None
    
    return walk(tree, [])


def count_species_under_node(node: Dict[str, Any]) -> int:
    """Cuenta especies bajo un nodo."""
    if not node:
        return 0
    
    count = 0
    stack = [node]
    
    while stack:
        n = stack.pop()
        if not n:
            continue
        
        rank = norm_rank(n.get("rank", ""))
        if rank == "species":
            count += 1
        
        children = n.get("children") or []
        stack.extend(children)
    
    return count


def list_children_clades(
    tree: Dict[str, Any],
    parent_key: Optional[str] = None
) -> List[CladeInfo]:
    """
    Lista los hijos inmediatos de un nodo.
    
    Args:
        tree: Árbol completo
        parent_key: Key del padre (None para root)
    
    Returns:
        Lista de CladeInfo de los hijos
    """
    if parent_key:
        parent = find_node_by_key(tree, parent_key)
        if not parent:
            return []
    else:
        parent = tree
    
    children = parent.get("children") or []
    if not children:
        return []
    
    # Calcular key del padre
    if parent_key:
        base_parts = parse_key_parts(parent_key)
    else:
        base_parts = [{"rank": parent.get("rank", "?"), "name": parent.get("name", "")}]
    
    result = []
    for child in children:
        child_parts = base_parts + [{"rank": child.get("rank", "?"), "name": child.get("name", "")}]
        child_key = path_key_from_parts(child_parts)
        
        result.append(CladeInfo(
            key=child_key,
            name=child.get("name", ""),
            rank=norm_rank(child.get("rank", "")),
            species_count=count_species_under_node(child),
            has_children=bool(child.get("children"))
        ))
    
    return sorted(result, key=lambda c: (c.rank, c.name))


def list_clades_at_rank(
    tree: Dict[str, Any],
    target_rank: str,
    under_key: Optional[str] = None
) -> List[CladeInfo]:
    """
    Lista todos los clados de un rank específico.
    
    Args:
        tree: Árbol completo
        target_rank: Rank a buscar
        under_key: Buscar solo bajo este nodo (opcional)
    
    Returns:
        Lista de CladeInfo
    """
    target = norm_rank(target_rank)
    
    if under_key:
        root = find_node_by_key(tree, under_key)
        if not root:
            return []
        base_parts = parse_key_parts(under_key)
    else:
        root = tree
        base_parts = []
    
    result = []
    
    def walk(node: Dict[str, Any], parts: List[Dict[str, str]]):
        next_parts = parts + [{"rank": node.get("rank", "?"), "name": node.get("name", "")}]
        rank = norm_rank(node.get("rank", ""))
        
        if rank == target:
            key = path_key_from_parts(next_parts)
            result.append(CladeInfo(
                key=key,
                name=node.get("name", ""),
                rank=rank,
                species_count=count_species_under_node(node),
                has_children=bool(node.get("children"))
            ))
            return  # No descender más
        
        children = node.get("children") or []
        for child in children:
            walk(child, next_parts)
    
    walk(root, base_parts[:-1] if base_parts else [])
    return sorted(result, key=lambda c: c.name)


# ============================================================
# Funciones sobre base de datos
# ============================================================

def search_taxa(
    query: str,
    include: Set[str] = None,
    limit: int = 50,
    offset: int = 0,
    nodes_scan_limit: int = 20000
) -> Tuple[List[SearchHit], int, bool]:
    """
    Busca taxa por nombre.
    
    Args:
        query: Texto a buscar (min 2 caracteres)
        include: {"species", "nodes"} - qué incluir
        limit: Máximo resultados a devolver
        offset: Offset para paginación
        nodes_scan_limit: Límite de paths a escanear para nodos
    
    Returns:
        Tuple de (hits, total, scanned_paths)
    """
    if include is None:
        include = {"species", "nodes"}
    
    q = (query or "").strip()
    q_lc = q.lower()
    
    if len(q) < 2:
        return [], 0, False
    
    hits_by_key: Dict[str, SearchHit] = {}
    scanned = False
    
    # A) Búsqueda de especies (rápido)
    if "species" in include:
        sp_qs = (
            ExternalTaxon.objects
            .filter(system="col", rank="species", status="accepted")
            .filter(name__icontains=q)
            .only("id", "external_id", "name", "classification_path")
            .order_by("name")[:5000]
        )
        
        for rec in sp_qs:
            path = normalize_classification_path(rec.classification_path)
            parts = [{"rank": "dataset", "name": "Root"}]
            parts += [{"rank": r, "name": n} for r, n in path]
            parts += [{"rank": "species", "name": rec.name}]
            
            key = path_key_from_parts(parts)
            if key in hits_by_key:
                continue
            
            hits_by_key[key] = SearchHit(
                key=key,
                name=rec.name,
                rank="species",
                id=rec.id,
                external_id=rec.external_id,
                label=_parts_to_label(parts),
                kind="species"
            )
    
    # B) Búsqueda en nodos (clasificación)
    if "nodes" in include:
        scanned = True
        
        scan_qs = (
            ExternalTaxon.objects
            .filter(system="col", rank="species", status="accepted")
            .only("classification_path")
            .order_by("id")[:nodes_scan_limit]
        )
        
        for sp in scan_qs:
            path = normalize_classification_path(sp.classification_path)
            if not path:
                continue
            
            parts_prefix = [{"rank": "dataset", "name": "Root"}]
            for (r, n) in path:
                parts_prefix.append({"rank": r, "name": n})
                if q_lc in (n or "").lower():
                    key = path_key_from_parts(parts_prefix)
                    if key in hits_by_key:
                        continue
                    hits_by_key[key] = SearchHit(
                        key=key,
                        name=n,
                        rank=r,
                        id=None,
                        external_id=None,
                        label=_parts_to_label(parts_prefix),
                        kind="node"
                    )
    
    # Ordenar por relevancia
    def _score(hit: SearchHit) -> Tuple[int, int, str]:
        name = (hit.name or "").lower()
        if name == q_lc:
            s = 300
        elif name.startswith(q_lc):
            s = 200 + min(50, len(q_lc))
        elif q_lc in name:
            s = 100 + min(50, len(q_lc))
        else:
            s = 0
        
        depth = key_depth(hit.key)
        return (s, depth, name)
    
    all_hits = list(hits_by_key.values())
    all_hits.sort(key=_score, reverse=True)
    
    total = len(all_hits)
    page = all_hits[offset:offset + limit]
    
    return page, total, scanned


def _parts_to_label(parts: List[Dict[str, str]]) -> str:
    """Genera un label legible desde partes."""
    return " / ".join([f"{p.get('rank', '?')}:{p.get('name', '')}" for p in parts])


# ============================================================
# Obtener configuración de ranks
# ============================================================

def get_rank_config() -> Dict[str, Any]:
    """Devuelve la configuración de ranks."""
    return {
        "ranks": RANK_ORDER,
        "root_ranks": list(ROOT_RANKS),
        "last_rank_index": len(RANK_ORDER) - 1
    }
