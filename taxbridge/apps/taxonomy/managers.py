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
        # Only include species that have at least one matched NCBIGenome.
        # This keeps the tree consistent with sampling (avoids showing
        # species that cannot be sampled).
        qs = (
            self.filter(
                system=system,
                rank__in=["species", "subspecies", "variety", "form"],
                ncbi_genomes__col_match_status="matched",
            )
            .only("id", "external_id", "name", "rank", "status", "classification_path")
            .distinct()
            .order_by("id")
        )
        if limit is not None:
            qs = qs[:limit]
        
        root = TrieNode(name="Root", rank="dataset")
        
        def _source_label(system, status):
            """Return source label: accepted / synonym / manual."""
            if system == "manual":
                return "manual"
            st = (status or "").lower()
            if "synonym" in st:
                return "synonym"
            return "accepted"

        def _insert_species(sp, path, source="accepted"):
            """Insert a single species into the trie."""
            sk_name = None
            for r, n in path:
                if (r or "").lower() in ("superkingdom", "domain"):
                    sk_name = n
                    break

            if sk_name:
                root.meta.setdefault("superkingdom", sk_name)

            # Walk the trie to the parent of the leaf, creating nodes as needed.
            # Collect the chain so we can increment counts only if the leaf is new.
            chain = []
            cur = root
            for rank, name in path:
                if rank in ("species", "subspecies"):
                    continue
                key = (rank, name)
                if key not in cur.children:
                    cur.children[key] = TrieNode(name=name, rank=rank, meta={})
                    if sk_name:
                        cur.children[key].meta.setdefault("superkingdom", sk_name)
                chain.append(cur)
                cur = cur.children[key]
                if sk_name:
                    cur.meta.setdefault("superkingdom", sk_name)
            
            leaf_rank = sp.rank if sp.rank in ("species", "subspecies", "variety", "form") else "species"
            sp_key = (leaf_rank, sp.name)
            if sp_key not in cur.children:
                meta = {
                    "id": sp.id,
                    "external_id": sp.external_id,
                    "species_count": 1,
                    "source": source,
                }
                if sk_name:
                    meta["superkingdom"] = sk_name
                cur.children[sp_key] = TrieNode(
                    name=sp.name,
                    rank=leaf_rank,
                    meta=meta,
                )
                # Increment species_count on root, all intermediate nodes, and cur
                for node in chain:
                    node.meta["species_count"] = node.meta.get("species_count", 0) + 1
                cur.meta["species_count"] = cur.meta.get("species_count", 0) + 1

        # ── Insert COL species (accepted + synonyms) ──
        for sp in qs:
            path = normalize_classification_path(sp.classification_path)
            _insert_species(sp, path, source=_source_label(sp.system, sp.status))

        # ── Helpers for merging manual species into the existing COL trie ──

        def _find_chain_to(node, target_rank, target_name):
            """
            DFS search in node's subtree for (target_rank, target_name).
            Returns list of intermediate (rank, name) keys to traverse
            (NOT including the target itself), or None if not found.
            """
            key = (target_rank, target_name)
            if key in node.children:
                return []                       # direct child
            for child_key, child_node in node.children.items():
                result = _find_chain_to(child_node, target_rank, target_name)
                if result is not None:
                    return [child_key] + result
            return None

        def _expand_manual_path(trie_root, path):
            """
            Fill in intermediate trie nodes that already exist in the COL
            trie between consecutive ranks of a manual species' path.

            Example: manual path [subphylum:Vertebrata, class:Reptilia]
            and the COL trie has Vertebrata → Gnathostomata → Osteichthyes →
            Tetrapoda → Reptilia.  Result:
              [Vertebrata, Gnathostomata, Osteichthyes, Tetrapoda, Reptilia]
            """
            if not path:
                return path
            expanded: list[tuple[str, str]] = []
            cur = trie_root
            for i, (rank, name) in enumerate(path):
                key = (rank, name)
                if key in cur.children:
                    # Direct child — no expansion needed
                    expanded.append((rank, name))
                    cur = cur.children[key]
                else:
                    chain = _find_chain_to(cur, rank, name)
                    if chain is not None:
                        # Insert the intermediate COL nodes, then the target
                        expanded.extend(chain)
                        expanded.append((rank, name))
                        for ck in chain:
                            cur = cur.children[ck]
                        cur = cur.children[key]
                    else:
                        # Not found in the trie — keep this and all
                        # remaining ranks as-is; _insert_species will
                        # create them.
                        expanded.extend(path[i:])
                        break
            return expanded

        # ── Insert manual species (from manual edits) ──
        manual_qs = (
            self.filter(
                system="manual",
                rank__in=["species", "subspecies", "variety", "form"],
                ncbi_genomes__col_match_status="manual",
            )
            .only("id", "external_id", "name", "rank", "classification")
            .distinct()
            .order_by("id")
        )
        # Comprehensive root→leaf rank ordering to match COL trie nodes
        _ALL_RANKS_ORDERED = [
            "domain", "superkingdom",
            "kingdom",
            "phylum",
            "subphylum",
            "infraphylum",
            "parvphylum",
            "gigaclass",
            "megaclass",
            "superclass",
            "class",
            "subclass",
            "subterclass",
            "infraclass",
            "superorder",
            "order",
            "suborder",
            "infraorder",
            "superfamily",
            "family",
            "subfamily",
            "tribe",
            "subtribe",
            "genus",
            "subgenus",
        ]
        _rank_sort = {r: i for i, r in enumerate(_ALL_RANKS_ORDERED)}

        for sp in manual_qs:
            cls = sp.classification or {}
            # Convert classification dict → sorted path of (rank, name)
            path = []
            for rank_key, name_val in cls.items():
                r = rank_key.strip().lower()
                if r in ("species",):
                    continue  # species is added separately
                if not name_val or not name_val.strip():
                    continue
                # Normalize domain/superkingdom to "domain"
                if r == "superkingdom":
                    r = "domain"
                if r in _rank_sort:
                    path.append((r, name_val.strip()))
            # Sort by the canonical rank ordering (root → leaf)
            path.sort(key=lambda x: _rank_sort.get(x[0], 999))
            # Expand path with intermediate COL nodes to avoid duplicate branches
            path = _expand_manual_path(root, path)
            _insert_species(sp, path, source="manual")

        tree = root.to_d3()

        if rank_cut is not None:
            tree = cut_by_rank(tree, rank_cut)
        
        if with_keys:
            tree = add_keys_to_tree(tree)
        
        return tree
