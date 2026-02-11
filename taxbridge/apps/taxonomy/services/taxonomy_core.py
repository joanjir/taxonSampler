# apps/taxonomy/services/taxonomy_core.py
"""
Módulo central con constantes y utilidades básicas de taxonomía.

Este módulo define:
- RANK_ORDER: Lista canónica de rangos taxonómicos
- Funciones de normalización y manejo de ranks
- Funciones de manejo de keys (path-based keys)

Todos los otros módulos de taxonomía deben importar de aquí para evitar duplicación.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple


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
# Funciones de normalización de ranks
# ============================================================

def norm_rank(rank: Optional[str]) -> str:
    """
    Normaliza un rank a lowercase.
    
    Args:
        rank: Rank a normalizar (puede ser None)
        
    Returns:
        Rank normalizado en minúsculas, o string vacío si es None
    """
    return (rank or "").strip().lower()


def rank_index(rank: Optional[str]) -> int:
    """
    Devuelve el índice del rank en RANK_ORDER.
    
    Args:
        rank: Rank a buscar
        
    Returns:
        Índice (0-based) del rank, o -1 si no existe
    """
    r = norm_rank(rank)
    try:
        return RANK_ORDER.index(r)
    except ValueError:
        return -1


def is_valid_rank(rank: Optional[str]) -> bool:
    """Verifica si un rank es válido."""
    return rank_index(rank) >= 0


def rank_depth(rank: Optional[str]) -> int:
    """
    Devuelve la profundidad del rank (sinónimo de rank_index para claridad).
    """
    return rank_index(rank)


# ============================================================
# Funciones de manejo de Keys (path-based keys)
# ============================================================

def path_key_from_parts(parts: List[Dict[str, str]]) -> str:
    """
    Construye un key path desde partes [{rank, name}, ...].
    
    Args:
        parts: Lista de diccionarios con 'rank' y 'name'
        
    Returns:
        Key string en formato "rank:name|rank:name|..."
        
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
    Parsea un key path a lista de {rank, name}.
    
    Args:
        key: Key string en formato "rank:name|rank:name|..."
        
    Returns:
        Lista de diccionarios con 'rank' y 'name'
        
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
    """
    Verifica si parent_key es prefijo de child_key.
    
    Args:
        parent_key: Key del posible ancestro
        child_key: Key del posible descendiente
        
    Returns:
        True si parent_key es prefijo de child_key
        
    Example:
        >>> is_prefix_key("dataset:Root|kingdom:Animalia", "dataset:Root|kingdom:Animalia|phylum:Chordata")
        True
    """
    if not parent_key or not child_key:
        return False
    if parent_key == child_key:
        return True
    return child_key.startswith(parent_key + "|")


def key_depth(key: str) -> int:
    """
    Devuelve la profundidad del key (número de segmentos).
    
    Args:
        key: Key string
        
    Returns:
        Número de segmentos en el key
    """
    if not key:
        return 0
    return len(key.split("|"))


def get_parent_key(key: str) -> Optional[str]:
    """
    Obtiene el key del padre.
    
    Args:
        key: Key del nodo
        
    Returns:
        Key del padre, o None si es root
    """
    parts = key.rsplit("|", 1)
    return parts[0] if len(parts) > 1 else None


def ancestor_key_at_rank(key: str, rank: str) -> Optional[str]:
    """
    Obtiene el ancestro de un key al rank especificado.
    
    Args:
        key: Key completo
        rank: Rank del ancestro deseado
        
    Returns:
        Key del ancestro al rank especificado, o None si no existe
    """
    target = norm_rank(rank)
    parts = parse_key_parts(key)
    
    for i, p in enumerate(parts):
        if p["rank"] == target:
            return path_key_from_parts(parts[:i + 1])
    return None


# ============================================================
# Funciones de normalización de classification_path
# ============================================================

def _is_path_leaf_to_root(path: List[Dict[str, Any]]) -> bool:
    """
    Detecta si el path viene en orden leaf->root.
    
    Los paths de COL pueden venir en ambas direcciones.
    """
    if not path:
        return False
    last_rank = (path[-1].get("rank") or "").strip().lower()
    return last_rank in ROOT_RANKS


def normalize_classification_path(path: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """
    Normaliza un classification_path a lista de (rank, name).
    
    Maneja paths en ambas direcciones y elimina duplicados.
    
    Args:
        path: Lista de dicts con 'rank' y 'name' (puede venir en cualquier orden)
        
    Returns:
        Lista de tuplas (rank, name) en orden root->leaf
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


def parts_to_label(parts: List[Dict[str, str]]) -> str:
    """
    Genera label legible desde partes.
    
    Args:
        parts: Lista de diccionarios con 'rank' y 'name'
        
    Returns:
        Label string como "rank:name / rank:name / ..."
    """
    return " / ".join([f"{p.get('rank') or '?'}:{p.get('name') or ''}" for p in parts])
