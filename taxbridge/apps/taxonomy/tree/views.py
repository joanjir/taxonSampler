from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict
from typing import Any, Dict, List, Tuple, Set

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt

from apps.taxonomy.models import ExternalTaxon
from apps.taxonomy.tree.managers import (
    cut_by_rank,
    expand_to_keys,
    find_node_by_key,
    count_species_under,
    list_clades_at_rank,
)
from apps.taxonomy.utils import (
    RANK_ORDER,
    ROOT_RANKS,
    norm_rank,
    path_key_from_parts,
    parse_key_parts,
    normalize_classification_path,
    parts_to_label,
)

logger = logging.getLogger(__name__)

# Tree cache configuration
TREE_CACHE_KEY = "taxonomy_tree_v1"
TREE_CACHE_TIMEOUT = 600  # 10 minutes
TREE_VERSION_KEY = "taxonomy_tree_version"


def _get_tree_version():
    """Compute a version string based on data state (count + max id of matched species + manual)."""
    from django.db.models import Max, Q
    # COL matched species
    qs_col = ExternalTaxon.objects.filter(
        system="col",
        rank__in=["species", "subspecies"],
        ncbi_genomes__col_match_status="matched",
    ).distinct()
    # Manual species (genus fallback, manual edits)
    qs_manual = ExternalTaxon.objects.filter(
        system="manual",
        rank="species",
    )
    count = qs_col.count() + qs_manual.count()
    max_id_col = qs_col.aggregate(m=Max("id"))["m"] or 0
    max_id_manual = qs_manual.aggregate(m=Max("id"))["m"] or 0
    max_id = max(max_id_col, max_id_manual)
    return f"{count}:{max_id}"


def _parse_include(v: str) -> Set[str]:
    """Parses the include=species,nodes parameter."""
    s = (v or "").strip().lower()
    if not s:
        return {"species", "nodes"}
    return {x.strip() for x in s.split(",") if x.strip()}


# ============================================================
# Tree endpoints
# ============================================================

def _get_tree_cache_key(limit, rank_cut):
    """Generate a cache key based on parameters."""
    key_parts = [TREE_CACHE_KEY, str(limit or "all"), str(rank_cut or "none")]
    return ":".join(key_parts)


@require_GET
def tree_data(request):
    """
    Main endpoint: returns the taxonomic tree.
    
    Params:
        - limit: maximum species count (default: all)
        - rankCut: rank to expand down to (default: None = fully expanded)
        - expand: keys to expand, comma-separated
        - nocache: if present, bypass cache
    """
    # If limit param is not provided, request entire DB (no slicing) up to safety max.
    raw_limit = request.GET.get("limit")
    if raw_limit is None:
        limit = None
    else:
        try:
            limit = int(raw_limit)
        except ValueError:
            limit = None

    if limit is not None:
        limit = max(1, min(limit, 200000))

    rank_cut = request.GET.get("rankCut") or request.GET.get("rank_cut")
    expand_keys = request.GET.get("expand", "")
    nocache = "nocache" in request.GET
    
    # Try to get from cache (only for requests without expand_keys)
    cache_key = _get_tree_cache_key(limit, rank_cut)
    tree = None
    
    if not nocache and not expand_keys:
        tree = cache.get(cache_key)
        if tree:
            logger.debug("[tree_data] Cache HIT for %s", cache_key)
    
    if tree is None:
        logger.debug("[tree_data] Cache MISS, building tree...")
        # Build tree using the manager
        tree = ExternalTaxon.objects.build_tree(
            limit=limit,
            system="col",
            rank_cut=rank_cut,
            with_keys=True,
        )
        
        # Stamp tree_version so frontend can detect changes
        tree["tree_version"] = _get_tree_version()
        
        # Cache the result (only if no expand_keys)
        if not expand_keys:
            cache.set(cache_key, tree, TREE_CACHE_TIMEOUT)
            logger.info("[tree_data] Cached tree (%s) for %d seconds", cache_key, TREE_CACHE_TIMEOUT)
    
    # Expand specific paths if requested (applied after cache lookup)
    if expand_keys:
        keys = [k.strip() for k in expand_keys.split(",") if k.strip()]
        if keys:
            tree = expand_to_keys(tree, keys)
    
    return JsonResponse(tree, safe=True)


@require_GET
def tree_version(request):
    """
    Lightweight endpoint returning only the current tree version.
    The frontend polls this to detect when species data has changed.
    """
    return JsonResponse({"tree_version": _get_tree_version()})


@require_GET
def invalidate_tree_cache(request):
    """
    Utility endpoint to invalidate the tree cache.
    Called after data imports or COL matching.
    """
    # Delete all tree cache keys
    for limit in [None, 1000, 5000, 10000, 15000]:
        for rank_cut in [None, "phylum", "class", "order", "family"]:
            key = _get_tree_cache_key(limit, rank_cut)
            cache.delete(key)
    
    logger.info("[tree_data] Tree cache invalidated")
    return JsonResponse({"success": True, "message": "Tree cache invalidated"})


@require_GET
def tree_search(request):
    """
    Backend-driven search.

    Params:
      - q: query string (min len 2)
      - include: "species,nodes" (default both)
      - limit: page size
      - offset: pagination offset
      - nodes_scan_limit: how many species are scanned to find matches in paths
    """
    q = (request.GET.get("q") or "").strip()
    q_lc = q.lower()

    try:
        limit = int(request.GET.get("limit", "50"))
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 200))

    try:
        offset = int(request.GET.get("offset", "0"))
    except ValueError:
        offset = 0
    offset = max(0, offset)

    include = _parse_include(request.GET.get("include", ""))  # species,nodes

    if len(q) < 2:
        return JsonResponse(
            {
                "query": q,
                "total": 0,
                "offset": offset,
                "limit": limit,
                "hits": [],
                "include": sorted(include),
                "scanned_paths": False,
            },
            safe=True,
        )

    hits_by_key: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    scanned = False

    # A) Species hits (fast)
    if "species" in include:
        # COL species & subspecies (accepted + synonyms)
        sp_qs = (
            ExternalTaxon.objects
            .filter(system="col", rank__in=["species", "subspecies"])
            .filter(name__icontains=q)
            .only("id", "external_id", "name", "status", "classification_path")
            .order_by("name")[:15000]
        )

        for rec in sp_qs:
            path = normalize_classification_path(rec.classification_path)
            leaf_rank = rec.rank if rec.rank in ("species", "subspecies") else "species"
            parts = [{"rank": "dataset", "name": "Root"}] + [{"rank": r, "name": n} for r, n in path] + [
                {"rank": leaf_rank, "name": rec.name}
            ]
            k = path_key_from_parts(parts)
            if k in hits_by_key:
                continue

            st = (rec.status or "").lower()
            source = "synonym" if "synonym" in st else "accepted"

            hits_by_key[k] = {
                "key": k,
                "name": rec.name,
                "rank": leaf_rank,
                "id": rec.id,
                "external_id": rec.external_id,
                "label": parts_to_label(parts),
                "kind": "species",
                "source": source,
            }

        # Manual species
        manual_qs = (
            ExternalTaxon.objects
            .filter(system="manual", rank="species")
            .filter(name__icontains=q)
            .only("id", "external_id", "name", "classification")
            .order_by("name")[:5000]
        )
        primary_ranks = ["kingdom", "phylum", "class", "order", "family", "genus"]
        for rec in manual_qs:
            cls = rec.classification or {}
            path = []
            domain_val = cls.get("domain") or cls.get("superkingdom")
            if domain_val:
                path.append(("domain", domain_val))
            for r in primary_ranks:
                val = cls.get(r)
                if val:
                    path.append((r, val))
            parts = [{"rank": "dataset", "name": "Root"}] + [{"rank": r, "name": n} for r, n in path] + [
                {"rank": "species", "name": rec.name}
            ]
            k = path_key_from_parts(parts)
            if k in hits_by_key:
                continue
            hits_by_key[k] = {
                "key": k,
                "name": rec.name,
                "rank": "species",
                "id": rec.id,
                "external_id": rec.external_id,
                "label": parts_to_label(parts),
                "kind": "species",
                "source": "manual",
            }

    # B) Node hits within classification_path
    #    (this is what was missing for "hom" to return Homo/Hominidae/etc)
    if "nodes" in include:
        scanned = True
        try:
            nodes_scan_limit = int(request.GET.get("nodes_scan_limit", "20000"))
        except ValueError:
            nodes_scan_limit = 20000
        nodes_scan_limit = max(1, min(nodes_scan_limit, 50000))

        scan_qs = (
            ExternalTaxon.objects
            .filter(system="col", rank__in=["species", "subspecies"])
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
                    k = path_key_from_parts(parts_prefix)
                    if k in hits_by_key:
                        continue
                    hits_by_key[k] = {
                        "key": k,
                        "name": n,
                        "rank": r,
                        "id": None,
                        "external_id": None,
                        "label": parts_to_label(parts_prefix),
                        "kind": "node",
                    }

    # Order: exact/prefix/contains + depth
    def _score(hit: Dict[str, Any]) -> Tuple[int, int, str]:
        name = (hit.get("name") or "").lower()
        if name == q_lc:
            s = 300
        elif name.startswith(q_lc):
            s = 200 + min(50, len(q_lc))
        elif q_lc in name:
            s = 100 + min(50, len(q_lc))
        else:
            s = 0

        depth = len((hit.get("key") or "").split("|"))
        return (s, depth, name)

    all_hits = list(hits_by_key.values())
    all_hits.sort(key=_score, reverse=True)

    total = len(all_hits)
    page = all_hits[offset : offset + limit]

    return JsonResponse(
        {
            "query": q,
            "total": total,
            "offset": offset,
            "limit": limit,
            "hits": page,
            "include": sorted(include),
            "scanned_paths": scanned,
        },
        safe=True,
    )


@ensure_csrf_cookie
def tree_page(request):
    return render(request, "taxonomy/pages/tree/index.html", {
        "show_tree_controls": True,
    })
