# apps/taxonomy/managers.py
"""
Django model managers for taxonomy.

ExternalTaxonManager: builds the taxonomic tree from the DB.
TrieNode: internal node for efficient tree construction.

Pure tree manipulation functions are in tree/managers.py.
Re-exported here for backward compatibility with existing code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from django.db import models

from .utils import (
    RANK_ORDER,
    ROOT_RANKS,
    LAST_RANK_INDEX,
    norm_rank,
    rank_index,
    path_key_from_parts,
    parse_key_parts,
    is_prefix_key,
    normalize_classification_path,
)

# Re-export tree functions for backward compatibility
from .tree.managers import (
    shallow_clone,
    is_leaf,
    collapse_all,
    cut_by_rank,
    add_keys_to_tree,
    expand_to_keys,
    count_species_under,
    count_visible_nodes,
    find_node_by_key,
    list_clades_at_rank,
)


# ============================================================
# Internal node for tree construction
# ============================================================

@dataclass
class TrieNode:
    """Internal node for building the tree before serializing to D3."""
    name: str
    rank: str
    meta: Dict[str, Any] = field(default_factory=dict)
    children: Dict[Tuple[str, str], "TrieNode"] = field(default_factory=dict)
    
    def to_d3(self) -> Dict[str, Any]:
        """Converts to D3 format {name, rank, children: [...]}."""
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


# ============================================================
# Manager for ExternalTaxon
# ============================================================

class ExternalTaxonManager(models.Manager):
    """
    Manager with methods for building and querying the taxonomic tree.
    """
    
    def active_species(self, system: str = "col"):
        """Returns QuerySet of active species."""
        return self.filter(
            system=system,
            rank="species",
            status="accepted",
        )
    
    def build_tree(
        self,
        limit: Optional[int] = None,
        system: str = "col",
        rank_cut: Optional[str] = None,
        with_keys: bool = True,
    ) -> Dict[str, Any]:
        """
        Builds the taxonomic tree from the DB.
        
        Args:
            limit: Maximum number of species to include
            system: Taxonomy system (default: "col")
            rank_cut: If specified, cuts the tree at this rank
            with_keys: If True, adds 'key' to each node
            
        Returns:
            Tree in D3 format ready for the frontend
        """
        qs = (
            self.filter(system=system, rank="species", status="accepted")
            .only("id", "external_id", "name", "rank", "classification_path")
            .order_by("id")
        )
        if limit is not None:
            qs = qs[:limit]
        
        root = TrieNode(name="Root", rank="dataset")
        
        for sp in qs:
            path = normalize_classification_path(sp.classification_path)
            # find superkingdom/domain name if present in the path
            sk_name = None
            for r, n in path:
                if (r or "").lower() in ("superkingdom", "domain"):
                    sk_name = n
                    break

            # increment root species count
            root.meta["species_count"] = root.meta.get("species_count", 0) + 1
            if sk_name:
                root.meta.setdefault("superkingdom", sk_name)

            cur = root
            for rank, name in path:
                key = (rank, name)
                if key not in cur.children:
                    cur.children[key] = TrieNode(name=name, rank=rank, meta={})
                    if sk_name:
                        cur.children[key].meta.setdefault("superkingdom", sk_name)
                cur = cur.children[key]
                # increment species count for this node (this species passes through)
                cur.meta["species_count"] = cur.meta.get("species_count", 0) + 1
                if sk_name:
                    cur.meta.setdefault("superkingdom", sk_name)
            
            sp_key = ("species", sp.name)
            if sp_key not in cur.children:
                meta = {"id": sp.id, "external_id": sp.external_id, "species_count": 1}
                if sk_name:
                    meta["superkingdom"] = sk_name
                cur.children[sp_key] = TrieNode(
                    name=sp.name,
                    rank="species",
                    meta=meta,
                )
        
        tree = root.to_d3()
        
        if rank_cut is not None:
            tree = cut_by_rank(tree, rank_cut)
        
        if with_keys:
            tree = add_keys_to_tree(tree)
        
        return tree
