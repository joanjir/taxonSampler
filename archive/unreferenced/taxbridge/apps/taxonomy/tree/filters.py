# taxonomy/tree/filters.py
"""
Filters for taxonomic tree manipulation.

Re-exports functions from utils and managers for compatibility.
"""
from typing import Dict, Any, List, Optional

from apps.taxonomy.utils import (
    RANK_ORDER,
    LAST_RANK_INDEX,
    norm_rank,
    rank_index,
)

from apps.taxonomy.tree.managers import (
    shallow_clone,
    collapse_all,
    cut_by_rank as cut_tree_by_rank,
    is_leaf,
)

# Re-export for compatibility
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


