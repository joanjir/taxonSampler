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
from django.db import connection


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


    # ------------------------------------------------------------
    # Lazy-loading helpers (scan-based fallbacks for large DBs)
    # ------------------------------------------------------------
    def children_for_key(
        self,
        key: Optional[str] = None,
        system: str = "col",
        dataset_code: Optional[str] = None,
        scan_limit: int = 100000,
    ) -> List[Dict[str, Any]]:
        """Return immediate children for the given key by scanning species.

        This is a scan-based fallback used by API endpoints when a CTE
        implementation is not yet available. It scans up to `scan_limit`
        species and aggregates child names, counts and whether they have
        further descendants.
        """
        from django.db.models import Q

        prefix = []
        if key:
            prefix = parse_key_parts(key)

        qs = self.filter(system=system, rank="species", status="accepted")
        if dataset_code:
            qs = qs.filter(dataset_code=dataset_code)

        qs = qs.only("classification_path").order_by("id").iterator(chunk_size=2000)

        counts: Dict[str, int] = {}
        has_children: Dict[str, bool] = {}
        scanned = 0

        for sp in qs:
            scanned += 1
            if scanned > scan_limit:
                break

            path = normalize_classification_path(sp.classification_path)
            # If key is provided, ensure path starts with prefix
            if prefix:
                # convert prefix parts to tuples
                pref_tuples = [(p.get("rank"), p.get("name")) for p in prefix]
                if len(path) < len(pref_tuples):
                    continue
                ok = True
                for i, (r, n) in enumerate(pref_tuples):
                    if path[i] != (r, n):
                        ok = False
                        break
                if not ok:
                    continue

                # child is next element after prefix
                if len(path) == len(pref_tuples):
                    # species sits exactly at prefix -> no child
                    continue
                child = path[len(pref_tuples)]
            else:
                # root: first element of path
                if not path:
                    continue
                child = path[0]

            r, n = child
            counts[n] = counts.get(n, 0) + 1

            # detect if this child has further descendants (by checking path length)
            child_prefix_len = (len(prefix) + 1) if prefix else 1
            has_children[n] = has_children.get(n, False) or (len(path) > child_prefix_len)

        items: List[Dict[str, Any]] = []
        for name, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            items.append({
                "name": name,
                "rank": None,
                "count_species": c,
                "has_children": bool(has_children.get(name, False)),
            })

        return items


    def aggregates_under(
        self,
        key: Optional[str] = None,
        target_rank: str = "class",
        system: str = "col",
        dataset_code: Optional[str] = None,
        scan_limit: int = 200000,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Aggregate nodes of `target_rank` under `key` by scanning species.

        Returns list of {name, species_count, has_children, key}
        """
        target = norm_rank(target_rank)
        if not target:
            return []

        prefix = []
        if key:
            prefix = parse_key_parts(key)

        qs = self.filter(system=system, rank="species", status="accepted")
        if dataset_code:
            qs = qs.filter(dataset_code=dataset_code)

        qs = qs.only("classification_path").order_by("id").iterator(chunk_size=2000)

        counts: Dict[str, int] = {}
        has_children: Dict[str, bool] = {}
        scanned = 0

        for sp in qs:
            scanned += 1
            if scanned > scan_limit:
                break

            path = normalize_classification_path(sp.classification_path)
            # check prefix
            if prefix:
                pref_tuples = [(p.get("rank"), p.get("name")) for p in prefix]
                if len(path) < len(pref_tuples):
                    continue
                ok = True
                for i, (r, n) in enumerate(pref_tuples):
                    if path[i] != (r, n):
                        ok = False
                        break
                if not ok:
                    continue

            # walk path to find nodes with matching target rank
            for i, (r, n) in enumerate(path):
                if norm_rank(r) != target:
                    continue
                # if prefix exists, ensure this node is under prefix
                if prefix and i < len(prefix):
                    continue

                counts[n] = counts.get(n, 0) + 1
                # has children if there are elements after this position
                has_children[n] = has_children.get(n, False) or (i < len(path) - 1)

        items = []
        for name, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]:
            items.append({
                "name": name,
                "rank": target,
                "species_count": c,
                "has_children": bool(has_children.get(name, False)),
            })

        return items

    def aggregates_under_cte(
        self,
        key: Optional[str] = None,
        target_rank: str = "class",
        system: str = "col",
        dataset_code: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Fast DB-backed aggregation for nodes of `target_rank` under root.

        NOTE: This optimized path currently only supports aggregation for the
        entire tree (key is None). If `key` is provided, falls back to the
        scan-based `aggregates_under` implementation.
        """
        target = norm_rank(target_rank)
        if not target:
            return []

        if key:
            # Prefix-limited aggregation is complex with jsonb; fallback to scan
            return self.aggregates_under(key=key, target_rank=target, system=system, dataset_code=dataset_code, limit=limit)

        table = self.model._meta.db_table

        sql = f"""
        SELECT elem->> 'name' AS name,
               elem->> 'rank' AS rank,
               COUNT(*)::int AS species_count,
               BOOL_OR((jsonb_array_length(classification_path) - idx) > 0) AS has_children
        FROM {table}, LATERAL (
            SELECT elem, row_number() OVER () AS idx
            FROM jsonb_array_elements(classification_path) WITH ORDINALITY arr(elem, ord)
        ) AS j(elem, idx)
        WHERE system = %s
            AND (elem->> 'rank') = %s
        GROUP BY name, rank
        ORDER BY species_count DESC, name ASC
        LIMIT %s
        """

        params = [system, target, limit]
        if dataset_code:
            # simple dataset_code filter appended
            sql = sql.replace("WHERE system = %s", "WHERE system = %s AND dataset_code = %s")
            params = [system, dataset_code, target, limit]

        with connection.cursor() as cur:
            try:
                cur.execute(sql, params)
                rows = cur.fetchall()
            except Exception:
                # On any SQL error, fallback to scan-based implementation
                return self.aggregates_under(key=key, target_rank=target, system=system, dataset_code=dataset_code, limit=limit)

        items: List[Dict[str, Any]] = []
        for name, rank, species_count, has_children in rows:
            items.append({
                "name": name,
                "rank": rank,
                "species_count": int(species_count),
                "has_children": bool(has_children),
            })
        return items

    def children_for_key_cte(
        self,
        key: Optional[str] = None,
        system: str = "col",
        dataset_code: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Optimized DB-backed retrieval of immediate children for the root only.

        If `key` is provided, falls back to `children_for_key` scan method.
        """
        if key:
            return self.children_for_key(key=key, system=system, dataset_code=dataset_code, scan_limit=200000)

        table = self.model._meta.db_table

        # We consider the immediate child under root as the first element of classification_path
        sql = f"""
        SELECT elem->> 'name' AS name, elem->> 'rank' AS rank, COUNT(*)::int AS count_species,
            BOOL_OR((jsonb_array_length(classification_path) - arr.ordinality) > 0) AS has_children
        FROM {table}, jsonb_array_elements(classification_path) WITH ORDINALITY arr(elem, ord)
        WHERE system = %s AND arr.ordinality = 1
        GROUP BY name, rank
        ORDER BY count_species DESC, name ASC
        LIMIT %s
        """

        params = [system, limit]
        if dataset_code:
            sql = sql.replace("WHERE system = %s", "WHERE system = %s AND dataset_code = %s")
            params = [system, dataset_code, limit]

        with connection.cursor() as cur:
            try:
                cur.execute(sql, params)
                rows = cur.fetchall()
            except Exception:
                return self.children_for_key(key=key, system=system, dataset_code=dataset_code, scan_limit=200000)

        items: List[Dict[str, Any]] = []
        for name, rank, count_species, has_children in rows:
            items.append({
                "name": name,
                "rank": rank,
                "count_species": int(count_species),
                "has_children": bool(has_children),
            })
        return items
