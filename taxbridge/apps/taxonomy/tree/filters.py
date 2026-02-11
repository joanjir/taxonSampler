# taxonomy/tree/filters.py
"""
Filtros para manipulación de árboles taxonómicos.

NOTA: Este módulo re-exporta funciones de tree_builder.py para compatibilidad.
Se recomienda importar directamente desde los módulos centralizados.
"""
from typing import Dict, Any, List, Optional

from apps.taxonomy.services.taxonomy_core import (
    RANK_ORDER,
    LAST_RANK_INDEX,
    norm_rank,
    rank_index,
)

from apps.taxonomy.services.tree_builder import (
    shallow_clone,
    collapse_all,
    cut_by_rank as cut_tree_by_rank,
    is_leaf,
)

# Re-export para compatibilidad
__all__ = [
    "RANK_ORDER",
    "LAST_RANK_INDEX",
    "norm_rank",
    "rank_index",
    "is_leaf",
    "shallow_clone",
    "collapse_all",
    "cut_tree_by_rank",
]


