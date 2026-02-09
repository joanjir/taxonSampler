# apps/taxonomy/services/tree_builder.py
"""
Servicio unificado para construcción y transformación del árbol taxonómico.

Responsabilidades:
- Construir el árbol desde la BD (build_tree_from_db)
- Cortar/expandir el árbol por rank (cut_by_rank, expand_to_keys)
- Agregar keys a los nodos (add_keys_to_tree)

El frontend recibe el árbol ya procesado y solo hace rendering D3.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from apps.taxonomy.models import ExternalTaxon


# ============================================================
# Constantes
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
# Utilidades básicas
# ============================================================

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


def is_prefix_key(parent_key: str, child_key: str) -> bool:
    """Verifica si parent_key es prefijo de child_key."""
    if not parent_key or not child_key:
        return False
    if parent_key == child_key:
        return True
    return child_key.startswith(parent_key + "|")


# ============================================================
# Transformaciones del árbol
# ============================================================

def shallow_clone(node: Dict[str, Any]) -> Dict[str, Any]:
    """Clona el nodo sin children ni _children."""
    return {k: v for k, v in node.items() if k not in ("children", "_children")}


def is_leaf(node: Dict[str, Any]) -> bool:
    """Verifica si el nodo es hoja."""
    return not node or not node.get("children")


def collapse_all(node: Dict[str, Any]) -> Dict[str, Any]:
    """
    Colapsa todo el subárbol: children -> _children recursivamente.
    """
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
    Corta el árbol hasta un rank específico.
    
    - rank_cut = "" o None -> solo ROOT visible (todo en _children)
    - rank_cut = "class"   -> abierto hasta class, debajo colapsado
    - rank_cut = "species" -> todo abierto
    
    Args:
        tree: Árbol en formato D3 {name, rank, children: [...]}
        rank_cut: Rank hasta el cual expandir
        
    Returns:
        Árbol cortado con children/_children apropiados
    """
    if not tree:
        return tree
    
    cut = norm_rank(rank_cut)
    
    # Caso: "" o None -> solo root visible
    if not cut:
        root = shallow_clone(tree)
        children = tree.get("children") or []
        root["children"] = None
        root["_children"] = [collapse_all(c) for c in children] if children else None
        return root
    
    cut_idx = rank_index(cut)
    
    # Rank desconocido -> política conservadora
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
        
        # species -> abrir todo
        if cut_idx == LAST_RANK_INDEX:
            n["children"] = [build(c, cur_idx) for c in node.get("children", [])]
            n["_children"] = None
            return n
        
        # Por encima del corte -> abierto
        if cur_idx < cut_idx:
            n["children"] = [build(c, cur_idx) for c in node.get("children", [])]
            n["_children"] = None
            return n
        
        # En el corte o por debajo -> colapsar
        n["children"] = None
        n["_children"] = [collapse_all(c) for c in node.get("children", [])]
        return n
    
    root_idx = rank_index(tree.get("rank"))
    root_idx = root_idx if root_idx >= 0 else -999
    
    return build(tree, root_idx)


def add_keys_to_tree(tree: Dict[str, Any]) -> Dict[str, Any]:
    """
    Agrega 'key' a cada nodo del árbol (recursivo).
    """
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
    """
    Expande el árbol para que las rutas hasta las keys estén visibles.
    Mueve nodos de _children a children según sea necesario.
    """
    if not tree or not keys:
        return tree
    
    key_set = set(keys)
    
    # También incluimos todos los prefijos (ancestros)
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
        
        # Si este nodo o algún descendiente está en all_needed, expandir
        needs_expand = any(
            k == current_key or k.startswith(current_key + "|")
            for k in all_needed
        )
        
        if needs_expand:
            # Mover _children a children si es necesario
            children = node.get("children") or []
            _children = node.get("_children") or []
            
            if not children and _children:
                node["children"] = _children
                node["_children"] = None
            
            # Procesar hijos recursivamente
            if node.get("children"):
                node["children"] = [walk(c, next_parts) for c in node["children"]]
        
        return node
    
    return walk(tree, [])


# ============================================================
# Construcción del árbol desde BD
# ============================================================

@dataclass
class TrieNode:
    """Nodo interno para construir el árbol antes de serializar a D3."""
    name: str
    rank: str
    meta: Dict[str, Any] = field(default_factory=dict)
    children: Dict[Tuple[str, str], "TrieNode"] = field(default_factory=dict)
    
    def to_d3(self) -> Dict[str, Any]:
        """Convierte a formato D3 {name, rank, children: [...]}."""
        kids = [
            c.to_d3() 
            for c in sorted(self.children.values(), key=lambda n: (n.rank, n.name))
        ]
        obj: Dict[str, Any] = {"name": self.name, "rank": self.rank}
        if self.meta:
            obj.update(self.meta)
        if kids:
            obj["children"] = kids
        return obj


def _is_path_leaf_to_root(path: List[Dict[str, Any]]) -> bool:
    """Detecta si el path viene en orden leaf->root."""
    if not path:
        return False
    last_rank = norm_rank(path[-1].get("rank"))
    return last_rank in ROOT_RANKS


def _normalize_classification_path(path: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """
    Normaliza classification_path a lista de (rank, name).
    Detecta y corrige orden leaf->root si es necesario.
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
    
    # Corregir orden si viene leaf->root
    if _is_path_leaf_to_root(path):
        clean.reverse()
    
    # Quitar duplicados consecutivos
    out: List[Tuple[str, str]] = []
    prev = None
    for item in clean:
        if item != prev:
            out.append(item)
        prev = item
    
    return out


def build_tree_from_db(
    limit: int = 5000,
    system: str = "col",
    rank_cut: Optional[str] = None,
    with_keys: bool = True,
) -> Dict[str, Any]:
    """
    Construye el árbol taxonómico desde la BD.
    
    Args:
        limit: Máximo de especies a incluir
        system: Sistema de taxonomía (default: "col")
        rank_cut: Si se especifica, corta el árbol a este rank
        with_keys: Si True, agrega 'key' a cada nodo
        
    Returns:
        Árbol en formato D3 listo para el frontend
    """
    qs = (
        ExternalTaxon.objects
        .filter(system=system, rank="species", status="accepted")
        .only("id", "external_id", "name", "rank", "classification_path")
        .order_by("id")[:limit]
    )
    
    root = TrieNode(name="Root", rank="dataset")
    
    for sp in qs:
        path = _normalize_classification_path(sp.classification_path)
        
        cur = root
        for rank, name in path:
            key = (rank, name)
            if key not in cur.children:
                cur.children[key] = TrieNode(name=name, rank=rank)
            cur = cur.children[key]
        
        # Agregar la especie como hoja
        sp_key = ("species", sp.name)
        if sp_key not in cur.children:
            cur.children[sp_key] = TrieNode(
                name=sp.name,
                rank="species",
                meta={"id": sp.id, "external_id": sp.external_id},
            )
    
    tree = root.to_d3()
    
    # Aplicar corte si se especifica
    if rank_cut is not None:
        tree = cut_by_rank(tree, rank_cut)
    
    # Agregar keys a todos los nodos
    if with_keys:
        tree = add_keys_to_tree(tree)
    
    return tree


# ============================================================
# Utilidades de conteo
# ============================================================

def count_species_under(node: Dict[str, Any]) -> int:
    """Cuenta especies bajo un nodo (incluye children y _children)."""
    if not node:
        return 0
    
    if norm_rank(node.get("rank")) == "species":
        return 1
    
    count = 0
    for child in (node.get("children") or []) + (node.get("_children") or []):
        count += count_species_under(child)
    
    return count


def count_visible_nodes(tree: Dict[str, Any]) -> int:
    """Cuenta nodos visibles (con children, no _children)."""
    if not tree:
        return 0
    
    count = 1  # este nodo
    for child in (tree.get("children") or []):
        count += count_visible_nodes(child)
    
    return count


def find_node_by_key(tree: Dict[str, Any], target_key: str) -> Optional[Dict[str, Any]]:
    """Busca un nodo por su key en el árbol."""
    if not tree or not target_key:
        return None
    
    def walk(node: Dict[str, Any], parts: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        if not node:
            return None
        
        next_parts = parts + [{"rank": node.get("rank", "?"), "name": node.get("name", "")}]
        current_key = path_key_from_parts(next_parts)
        
        if current_key == target_key:
            return node
        
        # Si el target_key no empieza con current_key, no buscar más abajo
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
    """
    Lista todos los clados de un rank específico bajo un root.
    
    Returns:
        Lista de {key, name, rank, species_count}
    """
    target = norm_rank(target_rank)
    if not tree or not target:
        return []
    
    # Si hay root_key, buscar ese nodo primero
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
            return  # No descender más
        
        for child in (node.get("children") or []) + (node.get("_children") or []):
            walk(child, next_parts)
    
    walk(tree, [])
    return results
