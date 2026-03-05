"""
API views for taxonomy module.

All JSON API endpoints are consolidated here following Django best practices.
Separated from UI views which render HTML templates.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


from django.db.models import Q
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.taxonomy.models import ExternalTaxon, Taxon
from apps.taxonomy.tree.managers import (
    expand_to_keys,
    count_species_under,
)
from apps.taxonomy.utils import (
    path_key_from_parts,
    norm_rank,
)
from apps.taxonomy.sampling.service import run_sampling, TreeIndex

import time as _time

# =============================================================================
# In-memory tree cache (avoids rebuilding on every scope-info request)
# =============================================================================

_tree_cache: Dict[str, Any] = {}
_tree_cache_ts: float = 0.0
_tree_index_cache: "TreeIndex | None" = None
_TREE_CACHE_TTL = 300  # 5 minutes


def _get_cached_tree_and_index() -> Tuple[Dict[str, Any], "TreeIndex"]:
    """
    Returns the cached (tree, TreeIndex) pair.
    Rebuilds only when the cache is stale (older than _TREE_CACHE_TTL seconds).
    """
    global _tree_cache, _tree_cache_ts, _tree_index_cache

    now = _time.monotonic()
    if _tree_cache and _tree_index_cache and (now - _tree_cache_ts) < _TREE_CACHE_TTL:
        return _tree_cache, _tree_index_cache

    tree = ExternalTaxon.objects.build_tree(
        limit=None, rank_cut="species", with_keys=True,
    )
    index = TreeIndex()
    index.build(tree)

    _tree_cache = tree
    _tree_index_cache = index
    _tree_cache_ts = now
    logger.info("[tree_cache] rebuilt in %.1f s", _time.monotonic() - now)
    return tree, index


def invalidate_tree_cache():
    """Call after DB mutations that affect the tree (sync, manual edits, etc.)."""
    global _tree_cache, _tree_cache_ts, _tree_index_cache
    _tree_cache = {}
    _tree_cache_ts = 0.0
    _tree_index_cache = None


# =============================================================================
# Helpers
# =============================================================================

_ROOT_RANKS_SET = {"domain", "superkingdom", "kingdom"}

def _normalize_path_for_key(path: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Normalize classification_path to build key.
    Detects and corrects leaf->root order if necessary.
    """
    if not path:
        return []
    
    # Check if path comes in leaf->root order (last element is root)
    last_rank = norm_rank(path[-1].get("rank", ""))
    if last_rank in _ROOT_RANKS_SET:
        path = list(reversed(path))
    
    return path


# =============================================================================
# Tree API Endpoints
# =============================================================================

@require_GET
def tree_data(request):
    """
    GET /api/v1/taxonomy/tree/data/
    
    Returns tree JSON for D3 visualization.
    
    Query params:
        - limit: Max species to include (default: 15000)
        - max_rank or rankCut: Maximum rank to show (default: species = no cut)
        - expand_keys: Comma-separated keys to expand
    """
    limit = request.GET.get("limit", "15000")
    # Accept both 'max_rank' (backend standard) and 'rankCut' (frontend legacy)
    # None = fully expanded tree; "" = collapsed root; "genus" = cut at genus
    raw_rank = request.GET.get("max_rank") or request.GET.get("rankCut")
    max_rank = raw_rank  # keep None when not provided
    expand_keys_str = request.GET.get("expand_keys", "")
    
    try:
        limit = int(limit)
    except ValueError:
        limit = 15000
    
    expand_keys = [k.strip() for k in expand_keys_str.split(",") if k.strip()]
    
    # Build tree from database
    # rank_cut=None → fully expanded; rank_cut="" → collapsed root only
    tree = ExternalTaxon.objects.build_tree(limit=limit, rank_cut=max_rank, with_keys=True)
    
    if not tree:
        return JsonResponse({"error": "Tree not found"}, status=404)
    
    # Expand specific keys if provided
    if expand_keys:
        tree = expand_to_keys(tree, expand_keys)
    
    # Count total species
    species_count = count_species_under(tree)
    
    return JsonResponse({
        "tree": tree,
        "limit": limit,
        "max_rank": max_rank,
        "expanded_keys": expand_keys,
        "species_count": species_count,
    })


@require_GET
def tree_search(request):
    """
    GET /api/v1/taxonomy/tree/search/?q=<query>
    
    Search taxa by name in the tree.
    Returns hits with key for tree navigation.
    
    Query params:
        - q: Search query (min 2 characters)
        - limit: Max results (default: 50, max: 200)
        - hide_existing: If true, hide species that already exist locally (default: false)
    """
    query = request.GET.get("q", "").strip()
    limit = min(int(request.GET.get("limit", 50)), 200)
    hide_existing = request.GET.get("hide_existing", "").lower() == "true"
    
    if len(query) < 2:
        return JsonResponse({"hits": [], "query": query, "total": 0})

    q_lower = query.lower()
    hits = []
    seen_keys: set = set()
    
    # Get all NCBI species names to check for existing local species
    existing_species = set(Taxon.objects.filter(rank="species").values_list("scientific_name", flat=True))

    # 1) Direct name match on ExternalTaxon records (species)
    species_qs = (
        ExternalTaxon.objects
        .filter(
            name__icontains=query,
            system="col",
            status="accepted",
        )
        .only("id", "external_id", "name", "rank", "classification_path")
        [:limit]
    )

    for ext in species_qs:
        # Check if this species already exists locally
        is_existing = ext.name in existing_species
        
        # Skip if user wants to hide existing species and this one exists
        if hide_existing and is_existing:
            continue
            
        path = _normalize_path_for_key(ext.classification_path or [])
        if ext.rank == "species":
            path = list(path) + [{"rank": "species", "name": ext.name}]
        
        key = "dataset:Root|" + path_key_from_parts(path) if path else ""
        if key and key not in seen_keys:
            seen_keys.add(key)
            hits.append({
                "id": ext.id,
                "external_id": ext.external_id,
                "name": ext.name,
                "rank": ext.rank,
                "key": key,
                "is_existing": is_existing,
            })

    # 2) Search higher-level clades inside classification_path
    #    (these taxa don't have their own ExternalTaxon record)
    if len(hits) < limit:
        clade_qs = (
            ExternalTaxon.objects
            .filter(
                classification_path__icontains=query,
                system="col",
                status="accepted",
            )
            .only("classification_path")
            [:500]  # scan more to find unique clades
        )
        
        for ext in clade_qs:
            path = _normalize_path_for_key(ext.classification_path or [])
            # Walk the path to find nodes whose name matches the query
            for i, node in enumerate(path):
                node_name = node.get("name", "")
                if q_lower in node_name.lower():
                    # Build key up to (and including) this node
                    clade_path = path[:i + 1]
                    key = "dataset:Root|" + path_key_from_parts(clade_path)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        hits.append({
                            "id": None,
                            "external_id": None,
                            "name": node_name,
                            "rank": norm_rank(node.get("rank", "")),
                            "key": key,
                            "is_existing": False,  # Higher-level clades are not considered "existing species"
                        })
                        if len(hits) >= limit:
                            break
            if len(hits) >= limit:
                break

    return JsonResponse({
        "hits": hits,
        "query": query,
        "total": len(hits),
        "hide_existing": hide_existing,
    })


# =============================================================================
# COL Navigation API Endpoints
# =============================================================================

# Base filter for COL species queries
_BASE_FILTER = Q(system="col") & Q(rank="species") & Q(status="accepted")
_ROOT_RANKS = {"domain", "superkingdom", "kingdom"}


def _parse_int(v: str | None, default: int, lo: int, hi: int) -> int:
    """Parse integer with bounds validation."""
    try:
        n = int(v) if v is not None else default
    except ValueError:
        n = default
    return max(lo, min(hi, n))


def _is_leaf_to_root(raw_path: List[Dict[str, Any]]) -> bool:
    """Check if path is ordered leaf->root."""
    if not raw_path:
        return False
    last_rank = (raw_path[-1].get("rank") or "").strip().lower()
    return last_rank in _ROOT_RANKS


def _normalize_path(raw_path: Any) -> List[Tuple[str, str]]:
    """
    Normalize classification_path to root->leaf list of (rank, name).
    Removes invalid entries and corrects order if leaf->root.
    """
    if not isinstance(raw_path, list):
        return []

    clean: List[Tuple[str, str]] = []
    for x in raw_path:
        if not isinstance(x, dict):
            continue
        rank = (x.get("rank") or "").strip()
        name = (x.get("name") or "").strip()
        if not rank or not name:
            continue
        clean.append((rank.lower(), name))

    if _is_leaf_to_root(raw_path):
        clean.reverse()

    # Deduplicate consecutive
    out: List[Tuple[str, str]] = []
    prev = None
    for item in clean:
        if item != prev:
            out.append(item)
        prev = item
    return out


def _parse_path_param(path_param: str | None) -> List[Tuple[str, str]]:
    """
    Parse path parameter from JSON string.
    Accepts [] or null as "root".
    """
    if not path_param:
        return []
    try:
        obj = json.loads(path_param)
    except json.JSONDecodeError:
        raise ValueError("path is not valid JSON")

    if obj is None:
        return []
    if not isinstance(obj, list):
        raise ValueError("path must be a JSON list")

    out: List[Tuple[str, str]] = []
    for x in obj:
        if not isinstance(x, dict):
            continue
        r = (x.get("rank") or "").strip().lower()
        n = (x.get("name") or "").strip()
        if r and n:
            out.append((r, n))
    return out


def _path_starts_with(full: List[Tuple[str, str]], prefix: List[Tuple[str, str]]) -> bool:
    """Check if full path starts with prefix."""
    if len(prefix) > len(full):
        return False
    return full[: len(prefix)] == prefix


def _get_next_after_prefix(full: List[Tuple[str, str]], prefix: List[Tuple[str, str]]) -> Tuple[str, str] | None:
    """Get the next element after prefix in full path."""
    if not _path_starts_with(full, prefix):
        return None
    if len(full) == len(prefix):
        return None
    return full[len(prefix)]


def _has_children_for_prefix(full: List[Tuple[str, str]], prefix: List[Tuple[str, str]]) -> bool:
    """Check if path has more elements after prefix."""
    return len(full) > len(prefix)


def _make_path_json(prefix: List[Tuple[str, str]]) -> List[Dict[str, str]]:
    """Convert path tuples to JSON-serializable format."""
    return [{"rank": r, "name": n} for r, n in prefix]


@require_GET
def col_next_ranks(request):
    """
    GET /api/v1/taxonomy/col/next-ranks/
    
    Returns ranks that appear immediately after the given path.
    
    Query params:
        - dataset_code: COL dataset code (required)
        - path: JSON array of {rank, name} (optional, defaults to root)
        - scan_limit: Max species to scan (default: 20000)
    """
    dataset_code = (request.GET.get("dataset_code") or "").strip()
    if not dataset_code:
        return HttpResponseBadRequest("dataset_code is required")

    try:
        prefix = _parse_path_param(request.GET.get("path"))
    except ValueError as e:
        return HttpResponseBadRequest(str(e))

    limit_scan = _parse_int(request.GET.get("scan_limit"), default=20000, lo=1000, hi=200000)

    qs = (
        ExternalTaxon.objects
        .filter(_BASE_FILTER, dataset_code=dataset_code)
        .only("classification_path")
        .iterator(chunk_size=2000)
    )

    counts: Dict[str, Dict[str, int]] = {}
    name_sets: Dict[str, set] = {}

    scanned = 0
    for sp in qs:
        scanned += 1
        if scanned > limit_scan:
            break

        full = _normalize_path(sp.classification_path)
        nxt = _get_next_after_prefix(full, prefix)
        if not nxt:
            continue
        r, n = nxt
        if r not in counts:
            counts[r] = {"count_species": 0}
            name_sets[r] = set()
        counts[r]["count_species"] += 1
        if len(name_sets[r]) < 50000:
            name_sets[r].add(n)

    out = []
    for r, d in counts.items():
        out.append({
            "rank": r,
            "count_species": d["count_species"],
            "count_distinct_names": len(name_sets.get(r, set())),
        })

    out.sort(key=lambda x: (-x["count_species"], x["rank"]))

    return JsonResponse({
        "dataset_code": dataset_code,
        "path": _make_path_json(prefix),
        "scanned_species": scanned if scanned <= limit_scan else limit_scan,
        "next_ranks": out,
    })


@require_GET
def col_nodes(request):
    """
    GET /api/v1/taxonomy/col/nodes/
    
    Returns nodes of a specific rank under the given path.
    
    Query params:
        - dataset_code: COL dataset code (required)
        - rank: Taxonomic rank to list (required)
        - path: JSON array of {rank, name} (optional)
        - offset: Pagination offset (default: 0)
        - limit: Page size (default: 200, max: 2000)
        - scan_limit: Max species to scan (default: 100000)
    """
    dataset_code = (request.GET.get("dataset_code") or "").strip()
    if not dataset_code:
        return HttpResponseBadRequest("dataset_code is required")

    rank = (request.GET.get("rank") or "").strip().lower()
    if not rank:
        return HttpResponseBadRequest("rank is required")

    try:
        prefix = _parse_path_param(request.GET.get("path"))
    except ValueError as e:
        return HttpResponseBadRequest(str(e))

    offset = _parse_int(request.GET.get("offset"), default=0, lo=0, hi=10_000_000)
    limit = _parse_int(request.GET.get("limit"), default=200, lo=1, hi=2000)
    limit_scan = _parse_int(request.GET.get("scan_limit"), default=100000, lo=5000, hi=500000)

    qs = (
        ExternalTaxon.objects
        .filter(_BASE_FILTER, dataset_code=dataset_code)
        .only("classification_path")
        .iterator(chunk_size=2000)
    )

    counts: Dict[str, int] = {}
    has_child_map: Dict[str, bool] = {}
    scanned = 0

    for sp in qs:
        scanned += 1
        if scanned > limit_scan:
            break

        full = _normalize_path(sp.classification_path)
        nxt = _get_next_after_prefix(full, prefix)
        if not nxt:
            continue
        nxt_rank, nxt_name = nxt
        if nxt_rank != rank:
            continue

        counts[nxt_name] = counts.get(nxt_name, 0) + 1

        node_prefix = prefix + [(nxt_rank, nxt_name)]
        has_children = _has_children_for_prefix(full, node_prefix)
        if nxt_name not in has_child_map:
            has_child_map[nxt_name] = has_children
        else:
            has_child_map[nxt_name] = has_child_map[nxt_name] or has_children

    items_all = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    total = len(items_all)
    page = items_all[offset: offset + limit]

    items = []
    for name, c in page:
        path_next = _make_path_json(prefix + [(rank, name)])
        items.append({
            "rank": rank,
            "name": name,
            "count_species": c,
            "has_children": bool(has_child_map.get(name, False)),
            "path_next": path_next,
        })

    next_offset = offset + limit if (offset + limit) < total else None

    return JsonResponse({
        "dataset_code": dataset_code,
        "path": _make_path_json(prefix),
        "rank": rank,
        "offset": offset,
        "limit": limit,
        "total": total,
        "next_offset": next_offset,
        "scanned_species": scanned if scanned <= limit_scan else limit_scan,
        "items": items,
    })


@require_GET
def col_species(request):
    """
    GET /api/v1/taxonomy/col/species/
    
    List accepted species under the given path.
    
    Query params:
        - dataset_code: COL dataset code (required)
        - path: JSON array of {rank, name} (optional)
        - offset: Pagination offset (default: 0)
        - limit: Page size (default: 200, max: 2000)
        - scan_limit: Max species to scan (default: 200000)
    """
    dataset_code = (request.GET.get("dataset_code") or "").strip()
    if not dataset_code:
        return HttpResponseBadRequest("dataset_code is required")

    try:
        prefix = _parse_path_param(request.GET.get("path"))
    except ValueError as e:
        return HttpResponseBadRequest(str(e))

    offset = _parse_int(request.GET.get("offset"), default=0, lo=0, hi=10_000_000)
    limit = _parse_int(request.GET.get("limit"), default=200, lo=1, hi=2000)
    limit_scan = _parse_int(request.GET.get("scan_limit"), default=200000, lo=5000, hi=1_000_000)

    qs = (
        ExternalTaxon.objects
        .filter(_BASE_FILTER, dataset_code=dataset_code)
        .only("id", "external_id", "name", "classification_path")
        .iterator(chunk_size=2000)
    )

    matches: List[Dict[str, Any]] = []
    scanned = 0

    for sp in qs:
        scanned += 1
        if scanned > limit_scan:
            break

        full = _normalize_path(sp.classification_path)
        if not _path_starts_with(full, prefix):
            continue

        matches.append({"id": sp.id, "external_id": sp.external_id, "name": sp.name})

    matches.sort(key=lambda x: x["name"])
    total = len(matches)
    page = matches[offset: offset + limit]
    next_offset = offset + limit if (offset + limit) < total else None

    return JsonResponse({
        "dataset_code": dataset_code,
        "path": _make_path_json(prefix),
        "offset": offset,
        "limit": limit,
        "total": total,
        "next_offset": next_offset,
        "scanned_species": scanned if scanned <= limit_scan else limit_scan,
        "species": page,
    })


@require_POST
def col_resolve_selection(request):
    """
    POST /api/v1/taxonomy/col/resolve/
    
    Resolve unique accepted species under union of selected paths.
    
    Request body:
        {
            "dataset_code": "COL25.12",
            "selected_paths": [[{rank, name}, ...], ...]
        }
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    dataset_code = (payload.get("dataset_code") or "").strip()
    if not dataset_code:
        return HttpResponseBadRequest("dataset_code is required")

    selected_paths = payload.get("selected_paths")
    if not isinstance(selected_paths, list):
        return HttpResponseBadRequest("selected_paths must be a list")

    prefixes: List[List[Tuple[str, str]]] = []
    for p in selected_paths:
        if p is None:
            prefixes.append([])
            continue
        if not isinstance(p, list):
            continue
        pr: List[Tuple[str, str]] = []
        for x in p:
            if not isinstance(x, dict):
                continue
            r = (x.get("rank") or "").strip().lower()
            n = (x.get("name") or "").strip()
            if r and n:
                pr.append((r, n))
        prefixes.append(pr)

    prefixes = [p for p in prefixes if p]
    if not prefixes:
        return JsonResponse({"dataset_code": dataset_code, "species": []})

    limit_scan = 500000

    qs = (
        ExternalTaxon.objects
        .filter(_BASE_FILTER, dataset_code=dataset_code)
        .only("id", "external_id", "name", "classification_path")
        .iterator(chunk_size=2000)
    )

    out_map: Dict[int, Dict[str, Any]] = {}
    scanned = 0
    for sp in qs:
        scanned += 1
        if scanned > limit_scan:
            break
        full = _normalize_path(sp.classification_path)
        for pref in prefixes:
            if _path_starts_with(full, pref):
                out_map[sp.id] = {"id": sp.id, "external_id": sp.external_id, "name": sp.name}
                break

    species_list = list(out_map.values())
    species_list.sort(key=lambda x: x["name"])

    return JsonResponse({
        "dataset_code": dataset_code,
        "scanned_species": scanned if scanned <= limit_scan else limit_scan,
        "species": species_list,
    })


# =============================================================================
# Sampling API Endpoints
# =============================================================================

@require_GET
def sampling_scope_info(request):
    """
    GET /api/v1/taxonomy/sampling/scope-info/
    
    Returns species counts for scope, targets, and active node.
    Used by the sampling wizard to show richness info.
    
    Query params:
        - scope_key: Key of scope node (optional)
        - target_keys: Comma-separated list of target keys (optional)
        - active_key: Key of currently active node (optional)
    
    Response:
        {
            "scope": {"key": "...", "name": "...", "rank": "...", "species_count": 123},
            "targets": [{"key": "...", "name": "...", "rank": "...", "species_count": 45}, ...],
            "active": {"key": "...", "name": "...", "rank": "...", "species_count": 10},
            "children": [{"key": "...", "name": "...", "rank": "...", "species_count": 5}, ...]
        }
    """
    scope_key = request.GET.get("scope_key", "").strip() or None
    target_keys_str = request.GET.get("target_keys", "").strip()
    active_key = request.GET.get("active_key", "").strip() or None
    
    target_keys = [k.strip() for k in target_keys_str.split(",") if k.strip()] if target_keys_str else []
    
    # Use cached tree + index (rebuilt at most every 5 min)
    tree, index = _get_cached_tree_and_index()
    if not tree:
        return JsonResponse({"error": "No tree data available"}, status=404)
    
    def node_info(key):
        """Get node info with species count."""
        if not key:
            return None
        node = index.get_node(key)
        if not node:
            return None
        species_count = index.count_rank_under(node, "species")
        return {
            "key": key,
            "name": node.get("name", ""),
            "rank": node.get("rank", ""),
            "species_count": species_count,
        }
    
    def get_children(key):
        """Get immediate children of a node with species counts."""
        if not key:
            # Return root's children
            root_children = tree.get("children") or []
            result = []
            for child in root_children:
                child_rank = norm_rank(child.get("rank", ""))
                child_name = child.get("name", "")
                child_key = path_key_from_parts([
                    {"rank": tree.get("rank", ""), "name": tree.get("name", "")},
                    {"rank": child_rank, "name": child_name}
                ])
                species_count = index.count_rank_under(child, "species")
                result.append({
                    "key": child_key,
                    "name": child_name,
                    "rank": child_rank,
                    "species_count": species_count,
                })
            return result
        
        node = index.get_node(key)
        if not node:
            return []
        
        node_children = node.get("children") or []
        result = []
        for child in node_children:
            child_rank = norm_rank(child.get("rank", ""))
            child_name = child.get("name", "")
            # Build child key by appending to parent key
            child_key = f"{key}|{child_rank}:{child_name}"
            species_count = index.count_rank_under(child, "species")
            result.append({
                "key": child_key,
                "name": child_name,
                "rank": child_rank,
                "species_count": species_count,
            })
        return result
    
    # Build response
    scope_info = node_info(scope_key) if scope_key else None
    if not scope_info and scope_key:
        # Scope key not found, use entire tree
        scope_info = {
            "key": None,
            "name": tree.get("name", "Root"),
            "rank": tree.get("rank", ""),
            "species_count": index.count_rank_under(tree, "species"),
        }
    
    targets_info = [node_info(k) for k in target_keys if k]
    targets_info = [t for t in targets_info if t]  # Filter None
    
    active_info = node_info(active_key) if active_key else None
    
    # Get children of scope (or root if no scope)
    children_info = get_children(scope_key)
    
    return JsonResponse({
        "scope": scope_info,
        "targets": targets_info,
        "active": active_info,
        "children": children_info,
    })


@require_POST
def sampling_run(request):
    """
    POST /api/v1/taxonomy/sampling/run/

    Executes the sampling algorithm on the server side.
    Receives sampling configuration, builds the tree, runs ingroup+outgroup
    sampling, and returns the result.

    Request body:
        {
            "scope_key": null | "rank:name|...",
            "targets": [],
            "K": 50,
            "allocation_rank": "class",
            "target_rank": "species",
            "allocation": "proportional",
            "min_one_per_clade": true,
            "outgroup_rank": "",
            "outgroup_n": 2,
            "limit": 15000,
            "max_rank": "class"
        }
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    # Build tree from DB (same as tree_data endpoint)
    limit = int(payload.get("limit", 5000))
    max_rank = payload.get("max_rank") or "class"

    tree = ExternalTaxon.objects.build_tree(limit=limit, rank_cut=max_rank, with_keys=True)
    if not tree:
        return JsonResponse({"error": "No tree data available"}, status=404)

    # Expand all nodes so sampling can traverse the full tree
    full_tree = ExternalTaxon.objects.build_tree(limit=limit, rank_cut="species", with_keys=True)
    if not full_tree:
        full_tree = tree

    # Prepare sampling config
    config = {
        "scope_key": payload.get("scope_key") or None,
        "targets": payload.get("targets") or [],
        "K": max(2, int(payload.get("K", 50))),
        "allocation_rank": (payload.get("allocation_rank") or "class").strip().lower(),
        "target_rank": (payload.get("target_rank") or "species").strip().lower(),
        "allocation": (payload.get("allocation") or "proportional").strip().lower(),
        "min_one_per_clade": bool(payload.get("min_one_per_clade", True)),
        "outgroup_rank": (payload.get("outgroup_rank") or "").strip().lower(),
        "outgroup_n": max(1, int(payload.get("outgroup_n", 2))),
    }

    # Run sampling
    result = run_sampling(full_tree, config)

    # Serialize response
    ingroup = result.ingroup
    outgroup = result.outgroup

    return JsonResponse({
        "scope_root_key": ingroup.scope_root_key,
        "mode": payload.get("sampling_root_mode", "tree"),
        "targets": config["targets"],
        "K": config["K"],
        "allocation": config["allocation"],
        "allocationRank": ingroup.allocation_rank,
        "targetRank": ingroup.target_rank,
        "minOnePerClade": config["min_one_per_clade"],

        "ingroup": {
            "note": ingroup.note,
            "quotas": [
                {
                    "key": q.get("key", ""),
                    "name": q.get("name", ""),
                    "rank": q.get("rank", ""),
                    "speciesAvail": q.get("species_avail", 0),
                    "quota": q.get("quota", 0),
                    "picked": q.get("picked", []),
                }
                for q in (ingroup.quotas or [])
            ],
            "picked": ingroup.picked,
        },

        "outgroupPicked": outgroup.picked,
        "outgroup": outgroup.meta,
    })


# =============================================================================
# Genomes API Endpoints
# =============================================================================

@require_GET
def genomes_list(request):
    """
    GET /api/v1/taxonomy/genomes/
    
    List of NCBI genomes with filtering and pagination.
    
    Query params:
        - page: Page number (default: 1)
        - page_size: Page size (default: 50, max: 200)
        - search: Search by organism name
        - phylum: Filter by phylum
        - class_name: Filter by class
        - genome_level: Filter by genome level
        - col_match_status: Filter by linkage status
        - ordering: Sort field (default: organism_name)
    """
    from apps.taxonomy.models import NCBIGenome
    
    # Pagination
    try:
        page = int(request.GET.get("page", 1))
        page_size = min(int(request.GET.get("page_size", 50)), 200)
    except ValueError:
        page, page_size = 1, 50
    
    # Filters
    qs = NCBIGenome.objects.all()
    
    search = request.GET.get("search", "").strip()
    if search:
        qs = qs.filter(
            Q(organism_name__icontains=search) |
            Q(accession__icontains=search) |
            Q(common_name__icontains=search)
        )
    
    phylum = request.GET.get("phylum", "").strip()
    if phylum:
        qs = qs.filter(phylum=phylum)
    
    class_name = request.GET.get("class_name", "").strip()
    if class_name:
        qs = qs.filter(class_name=class_name)
    
    genome_level = request.GET.get("genome_level", "").strip()
    if genome_level:
        qs = qs.filter(genome_level=genome_level)
    
    col_match_status = request.GET.get("col_match_status", "").strip()
    if col_match_status:
        if col_match_status == "unlinked":
            # Unlinked = unmatched (never searched) + not_in_col (searched, not found)
            qs = qs.filter(col_match_status__in=["unmatched", "not_in_col"])
        else:
            qs = qs.filter(col_match_status=col_match_status)
    
    # Filter by COL status (accepted, synonym, not_in_col)
    col_status = request.GET.get("col_status", "").strip()
    if col_status:
        if col_status == "not_in_col":
            # Searched in COL but not found
            qs = qs.filter(col_match_status="not_in_col")
        else:
            # Filter by external_taxon.status (accepted, synonym, etc.)
            qs = qs.filter(external_taxon__status=col_status)
    
    # Sorting
    ordering = request.GET.get("ordering", "organism_name")
    valid_orderings = ["organism_name", "-organism_name", "accession", "-accession", 
                       "phylum", "-phylum", "genome_level", "-genome_level",
                       "col_match_status", "-col_match_status"]
    if ordering in valid_orderings:
        qs = qs.order_by(ordering)
    else:
        qs = qs.order_by("organism_name")
    
    # Total count
    total_count = qs.count()
    
    # Pagination
    offset = (page - 1) * page_size
    genomes = qs.select_related('external_taxon')[offset:offset + page_size]
    
    # Serialize
    results = []
    for g in genomes:
        # Get COL status: external_taxon.status or 'not_in_col' if searched but not found
        col_status = None
        if g.external_taxon:
            col_status = g.external_taxon.status
        elif g.col_match_status == "not_in_col":
            col_status = "not_in_col"
        
        results.append({
            "id": g.id,
            "accession": g.accession,
            "organism_name": g.organism_name,
            "common_name": g.common_name,
            "genome_level": g.genome_level,
            "genome_coverage": g.genome_coverage,
            "genes": g.genes,
            "protein_coding": g.protein_coding,
            "has_proteome": g.has_proteome,
            "proteome_quality": g.proteome_quality,
            "col_match_status": g.col_match_status,
            "col_status": col_status,  # accepted, synonym, etc
            "taxon_id": g.taxon_id,
            "external_taxon_id": g.external_taxon_id,
        })
    
    return JsonResponse({
        "count": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size,
        "results": results,
    })


@require_GET
def genome_detail(request, accession: str):
    """
    GET /api/v1/taxonomy/genomes/<accession>/
    
    Genome detail by accession.
    """
    from apps.taxonomy.models import NCBIGenome
    
    try:
        genome = NCBIGenome.objects.select_related("taxon", "external_taxon").get(accession=accession)
    except NCBIGenome.DoesNotExist:
        return JsonResponse({"error": f"Genome {accession} not found"}, status=404)
    
    # External taxon classification if available
    external_taxon_data = None
    if genome.external_taxon:
        ext = genome.external_taxon
        external_taxon_data = {
            "id": ext.id,
            "external_id": ext.external_id,
            "name": ext.name,
            "rank": ext.rank,
            "status": ext.status,
            "classification": ext.classification or {},
            "classification_path": ext.classification_path or [],
        }
    
    data = {
        "id": genome.id,
        "accession": genome.accession,
        "organism_name": genome.organism_name,
        "common_name": genome.common_name,
        "strain": genome.strain,
        "phylum": genome.phylum,
        "class_name": genome.class_name,
        # Genome assembly info
        "genome_level": genome.genome_level,
        "refseq_category": genome.refseq_category,
        "source_database": genome.source_database,
        "release_date": genome.release_date,
        "sequencing_tech": genome.sequencing_tech,
        "assembly_method": genome.assembly_method,
        # Quality metrics
        "genome_coverage": genome.genome_coverage,
        "contig_n50_kb": genome.contig_n50_kb,
        "scaffold_n50_kb": genome.scaffold_n50_kb,
        "scaffold_count": genome.scaffold_count,
        "contig_count": genome.contig_count,
        "chromosome_count": genome.chromosome_count,
        "total_sequence_length": genome.total_sequence_length,
        "gc_percent": genome.gc_percent,
        "quality_score": genome.quality_score,
        # Genes
        "genes": genome.genes,
        "protein_coding": genome.protein_coding,
        "non_coding_genes": genome.non_coding_genes,
        "pseudogenes": genome.pseudogenes,
        # Annotation
        "annotation_provider": genome.annotation_provider,
        "annotation_status": genome.annotation_status,
        # BUSCO
        "busco_complete": genome.busco_complete,
        "busco_single_copy": genome.busco_single_copy,
        "busco_duplicated": genome.busco_duplicated,
        "busco_fragmented": genome.busco_fragmented,
        "busco_missing": genome.busco_missing,
        "busco_lineage": genome.busco_lineage,
        # Proteome
        "has_proteome": genome.has_proteome,
        "proteome_quality": genome.proteome_quality,
        # COL match
        "col_match_status": genome.col_match_status,
        "col_match_notes": genome.col_match_notes,
        # Related objects
        "taxon": {
            "taxid": genome.taxon.taxid,
            "scientific_name": genome.taxon.scientific_name,
            "rank": genome.taxon.rank,
        } if genome.taxon else None,
        "external_taxon": external_taxon_data,
        # Metadata
        "fetched_at": genome.fetched_at.isoformat() if genome.fetched_at else None,
        "updated_at": genome.updated_at.isoformat() if genome.updated_at else None,
    }
    
    return JsonResponse(data)


@require_POST
def genome_update(request, accession: str):
    """
    POST /api/v1/taxonomy/genomes/<accession>/update/
    Admin only - update a genome's COL match.
    """
    if not (request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)):
        return JsonResponse({"error": "Permission denied"}, status=403)
    from apps.taxonomy.models import NCBIGenome
    
    try:
        genome = NCBIGenome.objects.get(accession=accession)
    except NCBIGenome.DoesNotExist:
        return JsonResponse({"error": f"Genome {accession} not found"}, status=404)
    
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    
    # ── Update species name (Taxon.scientific_name + organism_name) ──
    new_species_name = data.get("species_name", "").strip()
    if new_species_name and genome.taxon:
        genome.taxon.scientific_name = new_species_name
        genome.taxon.save(update_fields=["scientific_name"])
        genome.organism_name = new_species_name
    
    # ── Update taxonomy fields on genome ──
    taxonomy = data.get("taxonomy", {})
    if taxonomy:
        if "phylum" in taxonomy:
            genome.phylum = taxonomy["phylum"]
        if "class" in taxonomy:
            genome.class_name = taxonomy["class"]
    
    # ── Update external_taxon (COL link) ──
    ext_id = data.get("external_taxon_id")
    if ext_id:
        # User selected a COL taxon — link it
        try:
            external_taxon = ExternalTaxon.objects.get(id=ext_id)
            genome.external_taxon = external_taxon
            # If user also supplied taxonomy, update the external_taxon classification
            if taxonomy:
                external_taxon.classification = taxonomy
                external_taxon.save(update_fields=["classification"])
        except ExternalTaxon.DoesNotExist:
            return JsonResponse({"error": "ExternalTaxon not found"}, status=404)
    elif taxonomy:
        # No COL taxon selected but taxonomy provided — create/update manual ExternalTaxon
        species_name = new_species_name or genome.organism_name or ""
        if species_name:
            manual_ext, _created = ExternalTaxon.objects.update_or_create(
                system="manual",
                name=species_name,
                rank="species",
                defaults={
                    "dataset_code": "manual",
                    "external_id": f"manual-{genome.accession}",
                    "status": "accepted",
                    "classification": taxonomy,
                },
            )
            genome.external_taxon = manual_ext
    
    # ── Update notes ──
    if "col_match_notes" in data:
        genome.col_match_notes = data["col_match_notes"]
    
    # ── Update status ──
    if ext_id:
        genome.col_match_status = "matched"
    else:
        genome.col_match_status = "manual"
    
    # ── Create / update TaxonCrosswalk record ──
    if genome.taxon and genome.external_taxon:
        from apps.taxonomy.models import TaxonCrosswalk
        TaxonCrosswalk.objects.update_or_create(
            ncbi_taxon=genome.taxon,
            external_taxon=genome.external_taxon,
            defaults={
                "score": 1.0,
                "decision": "manual",
                "method": "manual",
                "is_active": True,
            },
        )
    
    genome.save()
    
    return JsonResponse({
        "success": True,
        "accession": genome.accession,
        "col_match_status": genome.col_match_status,
        "external_taxon_id": genome.external_taxon_id,
        "col_match_notes": genome.col_match_notes,
        "organism_name": genome.organism_name,
    })


@require_GET
def col_search(request):
    """
    GET /api/v1/taxonomy/col/search/?q=query
    
    Search COL taxa by name. For use in the edit modal.
    
    Query params:
        - q: Search term (min 2 characters)
        - limit: Max results (default: 20)
        - hide_existing: If true, hide species that already exist locally (default: false)
    """
    query = request.GET.get("q", "").strip()
    limit = min(int(request.GET.get("limit", 20)), 100)
    hide_existing = request.GET.get("hide_existing", "").lower() == "true"
    
    if len(query) < 2:
        return JsonResponse({"results": []})
    
    # Get all NCBI species names to check for existing local species
    existing_species = set(Taxon.objects.filter(rank="species").values_list("scientific_name", flat=True))
    
    # Search in local ExternalTaxon database
    results = ExternalTaxon.objects.filter(
        Q(name__icontains=query) | Q(external_id__icontains=query),
        system="col",
        rank="species"
    ).select_related("accepted")[:limit * 2]  # Get more to filter existing ones
    
    data = []
    for ext in results:
        # Check if this species already exists locally
        is_existing = ext.name in existing_species
        
        # Skip if user wants to hide existing species and this one exists
        if hide_existing and is_existing:
            continue
        
        # Stop adding if we already have enough results
        if len(data) >= limit:
            break
            
        # Build classification string
        classification_str = ""
        if ext.classification:
            parts = []
            for rank in ["kingdom", "phylum", "class", "order", "family", "genus"]:
                if rank in ext.classification:
                    parts.append(ext.classification[rank])
            classification_str = " > ".join(parts)
        
        data.append({
            "id": ext.id,
            "external_id": ext.external_id,
            "name": ext.name,
            "rank": ext.rank,
            "status": ext.status,
            "classification": classification_str,
            "classification_raw": ext.classification or {},
            "accepted_name": ext.accepted.name if ext.accepted else None,
            "is_existing": is_existing,
        })
    
    return JsonResponse({
        "results": data,
        "hide_existing": hide_existing,
    })


@require_GET
def gbif_search(request):
    """
    GET /api/v1/taxonomy/gbif/search/?q=query

    Proxy search to GBIF Species API (suggest endpoint).
    Returns species-level matches with taxonomy for use in the edit modal.

    Query params:
        - q: Search term (min 2 characters)
        - limit: Max results (default: 10)
    """
    import urllib.request
    import urllib.parse

    query = request.GET.get("q", "").strip()
    limit = min(int(request.GET.get("limit", 10)), 50)

    if len(query) < 2:
        return JsonResponse({"results": []})

    try:
        params = urllib.parse.urlencode({
            "q": query,
            "rank": "SPECIES",
            "limit": limit,
        })
        url = f"https://api.gbif.org/v1/species/suggest?{params}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            gbif_data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return JsonResponse({"error": f"GBIF API error: {str(e)}"}, status=502)

    # Deduplicate by canonicalName
    seen = set()
    results = []
    for item in gbif_data:
        canon = item.get("canonicalName", "")
        if not canon or canon in seen:
            continue
        seen.add(canon)

        classification = {}
        for rank in ["kingdom", "phylum", "class", "order", "family", "genus", "species"]:
            val = item.get(rank)
            if val:
                classification[rank] = val

        # Build classification string
        cls_str = " > ".join(
            classification.get(r, "")
            for r in ["kingdom", "phylum", "class", "order", "family", "genus"]
            if classification.get(r)
        )

        results.append({
            "gbif_key": item.get("key"),
            "name": canon,
            "rank": (item.get("rank") or "").lower(),
            "status": (item.get("taxonomicStatus") or "accepted").lower(),
            "classification": cls_str,
            "classification_raw": classification,
            "source": "gbif",
        })

    return JsonResponse({"results": results})


# ============================================================
# DB Sampling API — Step 2
# ============================================================

@require_GET
def sampling_stats(request):
    """
    Returns statistics about available species for sampling config UI.
    Query params:
        - kingdom: Filter by kingdom (optional)
        - phylum: Filter by phylum (optional)
        - scope_filters: JSON-encoded dict of rank→taxon filters (optional)
        - species_names: JSON-encoded list of organism names (optional)
    """
    from apps.taxonomy.sampling.db_engine import get_sampling_stats

    kingdom = request.GET.get("kingdom", "")
    phylum = request.GET.get("phylum", "")

    # Parse scope_filters from query param (JSON string)
    scope_filters = None
    sf_raw = request.GET.get("scope_filters", "")
    if sf_raw:
        try:
            scope_filters = json.loads(sf_raw)
        except json.JSONDecodeError:
            pass

    # Parse target_keys from query param (JSON string)
    target_keys = None
    tk_raw = request.GET.get("target_keys", "")
    if tk_raw:
        try:
            target_keys = json.loads(tk_raw)
        except json.JSONDecodeError:
            pass

    # Parse species_names from query param (JSON string)
    species_names = None
    sn_raw = request.GET.get("species_names", "")
    if sn_raw:
        try:
            species_names = json.loads(sn_raw)
        except json.JSONDecodeError:
            pass

    stats = get_sampling_stats(
        scope_kingdom=kingdom,
        scope_phylum=phylum,
        scope_filters=scope_filters,
        target_keys=target_keys,
        species_names=species_names,
    )

    return JsonResponse(stats)


@require_GET
def organisms_search(request):
    """
    Search for organisms by name within the current sampling scope.
    Returns a list of organism names matching the query.
    
    Query params:
      q: search query (minimum 2 characters)
      kingdom: filter by kingdom (optional)
      phylum: filter by phylum (optional)
      class: filter by class (optional)
      order: filter by order (optional)
      family: filter by family (optional)
      full: if "1", return full organism data instead of just names
    """
    query = request.GET.get('q', '').strip().lower()
    
    if len(query) < 2:
        return JsonResponse({"organisms": []})
    
    from apps.taxonomy.models import NCBIGenome
    
    # Build queryset with scope filters
    qs = NCBIGenome.objects.filter(
        organism_name__icontains=query,
        col_match_status='matched',
        external_taxon__isnull=False,
    )
    
    # Apply scope filters if provided (using classification JSONField)
    kingdom = request.GET.get('kingdom', '').strip()
    phylum = request.GET.get('phylum', '').strip()
    class_name = request.GET.get('class', '').strip()
    order = request.GET.get('order', '').strip()
    family = request.GET.get('family', '').strip()
    
    if kingdom:
        qs = qs.filter(external_taxon__classification__kingdom=kingdom)
    if phylum:
        qs = qs.filter(external_taxon__classification__phylum=phylum)
    if class_name:
        qs = qs.filter(external_taxon__classification__class=class_name)
    if order:
        qs = qs.filter(external_taxon__classification__order=order)
    if family:
        qs = qs.filter(external_taxon__classification__family=family)
    
    # Return full data or just names
    full_data = request.GET.get('full', '') == '1'
    
    if full_data:
        organisms = list(
            qs.select_related('external_taxon')
            .order_by('organism_name')[:50]
        )
        organisms_full = []
        for g in organisms:
            ext = g.external_taxon
            cls = ext.classification if ext else {}
            organisms_full.append({
                "organism_name": g.organism_name,
                "accession": g.assembly_accession,
                "assembly_level": g.assembly_level,
                "phylum": cls.get("phylum"),
                "class_name": cls.get("class"),
                "order": cls.get("order"),
                "family": cls.get("family"),
                "genus": cls.get("genus"),
            })
        return JsonResponse({
            "organisms": [o["organism_name"] for o in organisms_full],
            "organisms_full": organisms_full,
        })
    else:
        organisms = (
            qs.values_list('organism_name', flat=True)
            .distinct()
            .order_by('organism_name')[:50]
        )
        return JsonResponse({"organisms": list(organisms)})


@csrf_exempt
@require_POST
def sampling_execute(request):
    """
    Execute a DB-based sampling with the given configuration.
    POST body (JSON):
        - max_sample_size: int (required)
        - start_rank: str (default: phylum)
        - end_rank: str (default: species)
        - strategy: natural | quality_random | stratified_proportional | balanced_hierarchical (default: stratified_proportional)
        - kingdom: str (optional scope filter)
        - phylum: str (optional scope filter)
        - target_keys: list of tree path keys for target clades (optional)
        - save: bool (if true, saves a SamplingConfiguration record)
        - name: str (optional name for saved config)
    """
    from apps.taxonomy.sampling.db_engine import run_db_sampling
    from apps.taxonomy.models import SamplingConfiguration

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Validate max_sample_size (0 = all available)
    max_sample_size = data.get("max_sample_size")
    if max_sample_size is None:
        max_sample_size = 0  # "All"
    if not isinstance(max_sample_size, int) or max_sample_size < 0:
        return JsonResponse({"error": "max_sample_size must be a non-negative integer (0 = all)"}, status=400)

    start_rank = data.get("start_rank", "phylum").lower()
    end_rank = data.get("end_rank", "species").lower()
    strategy = data.get("strategy", "stratified_proportional").lower()
    kingdom = data.get("scope_kingdom") or data.get("kingdom", "")
    phylum = data.get("scope_phylum") or data.get("phylum", "")
    scope_filters = data.get("scope_filters") or None
    target_keys = data.get("target_keys") or None
    species_names = data.get("species_names") or None
    save_config = data.get("save", False)
    config_name = data.get("name", "")

    valid_ranks = ["domain", "kingdom", "phylum", "class", "order", "family", "genus", "species"]
    valid_strategies = ["natural", "quality_random", "stratified_proportional", "balanced_hierarchical"]

    if start_rank not in valid_ranks:
        return JsonResponse({"error": f"Invalid start_rank: {start_rank}"}, status=400)
    if end_rank not in valid_ranks:
        return JsonResponse({"error": f"Invalid end_rank: {end_rank}"}, status=400)
    if strategy not in valid_strategies:
        return JsonResponse({"error": f"Invalid strategy: {strategy}"}, status=400)

    # Validate rank order: start_rank must be higher (smaller index) than end_rank
    if valid_ranks.index(start_rank) >= valid_ranks.index(end_rank):
        return JsonResponse(
            {"error": f"start_rank ({start_rank}) must be higher than end_rank ({end_rank})"},
            status=400,
        )

    # Save config if requested
    config_id = None
    if save_config:
        config_obj = SamplingConfiguration.objects.create(
            name=config_name,
            max_sample_size=max_sample_size,
            start_rank=start_rank,
            end_rank=end_rank,
            strategy=strategy,
            scope_kingdom=kingdom,
            scope_phylum=phylum,
        )
        config_id = config_obj.pk

    # Execute sampling
    logger.info(
        "[sampling_execute] params → max_sample_size=%s, start_rank=%s, "
        "end_rank=%s, strategy=%s, scope_filters=%s, target_keys=%s, "
        "species_names_count=%s",
        max_sample_size, start_rank, end_rank, strategy,
        scope_filters, target_keys,
        len(species_names) if species_names else 0,
    )
    try:
        result = run_db_sampling(
            max_sample_size=max_sample_size,
            start_rank=start_rank,
            end_rank=end_rank,
            strategy=strategy,
            scope_kingdom=kingdom,
            scope_phylum=phylum,
            scope_filters=scope_filters,
            target_keys=target_keys,
            species_names=species_names,
            config_id=config_id,
        )
    except Exception as e:
        if config_id:
            SamplingConfiguration.objects.filter(pk=config_id).update(
                status="failed", error=str(e)
            )
        return JsonResponse({"error": str(e)}, status=500)

    # Update config with results
    if config_id:
        SamplingConfiguration.objects.filter(pk=config_id).update(
            status="executed",
            executed_at=timezone.now(),
            result={
                "total_available": result.total_available,
                "total_selected": result.total_selected,
                "strategy": result.strategy,
                "clades_count": len(result.clades),
                "warnings": result.warnings,
            },
        )

    return JsonResponse({
        "success": True,
        "config_id": config_id,
        "strategy": result.strategy,
        "max_sample_size": result.max_sample_size,
        "start_rank": result.start_rank,
        "end_rank": result.end_rank,
        "total_available": result.total_available,
        "total_selected": result.total_selected,
        "warnings": result.warnings,
        "clades": result.clades,
        "species": result.species,
        "available_species": result.available_species,  # All species in scope
        # Scope info for export/import (restore original scope context)
        "scope_filters": scope_filters,  # Dict of rank→taxon from Step 1
        "target_keys": target_keys,      # List of tree path keys from Step 1
    })


@require_GET
def sampling_configs(request):
    """List saved sampling configurations."""
    from apps.taxonomy.models import SamplingConfiguration

    configs = SamplingConfiguration.objects.all()[:20]
    data = []
    for c in configs:
        data.append({
            "id": c.pk,
            "name": c.name,
            "max_sample_size": c.max_sample_size,
            "start_rank": c.start_rank,
            "end_rank": c.end_rank,
            "strategy": c.strategy,
            "scope_kingdom": c.scope_kingdom,
            "scope_phylum": c.scope_phylum,
            "status": c.status,
            "result": c.result,
            "created_at": c.created_at.isoformat(),
            "executed_at": c.executed_at.isoformat() if c.executed_at else None,
        })

    return JsonResponse({"configs": data})


# ═══════════════════════════════════════════════════════════════════════
# Newick / Phylo Tree generation from DB Sampling results
# ═══════════════════════════════════════════════════════════════════════

@csrf_exempt
@require_POST
def sampling_newick(request):
    """
    Generate a Newick string (and optionally an SVG tree) from
    a DB sampling result.

    POST body: DB sampling result JSON containing species[] with
    taxonomy fields (kingdom, phylum, class, order, family, genus,
    organism_name).

    Query params:
      - format: "newick" (default) | "svg"

    Returns:
      - newick: text/plain Newick file download
      - svg: JSON with {"svg": "<svg>...", "newick": "..."}
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    species = payload.get("species", [])
    if not species:
        return JsonResponse({"error": "No species in payload"}, status=400)

    fmt = request.GET.get("format", "newick")

    try:
        from ete3 import Tree
    except ImportError as ie:
        return JsonResponse({"error": f"ete3 import failed: {ie}"}, status=500)

    try:
        # Build ETE3 tree from taxonomy hierarchy
        root = Tree()
        root.name = "Root"
        root.dist = 0.0

        # Taxonomy levels to traverse
        tax_ranks = ["kingdom", "phylum", "class", "order", "family", "genus"]
        node_index = {"": root}
        used_leaves = {}

        for sp in species:
            parent = root
            acc_parts = []

            for rank in tax_ranks:
                taxon_name = (sp.get(rank) or "").strip()
                if not taxon_name:
                    continue

                acc_parts.append(f"{rank}:{taxon_name}")
                acc_key = "|".join(acc_parts)

                if acc_key in node_index:
                    parent = node_index[acc_key]
                    continue

                # Create internal node
                safe_name = taxon_name.replace(" ", "_").replace("(", "").replace(")", "").replace(",", "").replace(";", "").replace(":", "_")
                internal_name = safe_name
                n = parent.add_child(name=internal_name)
                n.add_feature("rank", rank)
                n.dist = 1.0
                node_index[acc_key] = n
                parent = n

            # Add species leaf (skip duplicates)
            org_name = sp.get("organism_name") or sp.get("scientific_name") or "Unknown"
            safe_leaf = org_name.replace(" ", "_").replace("(", "").replace(")", "").replace(",", "").replace(";", "").replace(":", "_")

            # Skip if this species already exists as a leaf
            if safe_leaf in used_leaves:
                continue
            used_leaves[safe_leaf] = True

            leaf = parent.add_child(name=safe_leaf)
            leaf.add_feature("rank", "species")
            leaf.dist = 1.0

        # ── Collapse single-child chain from root ──────────────────
        # If the root has only one child chain (e.g., Root→Animalia→…)
        # move root down to the first node with >1 child or a leaf.
        while len(root.children) == 1 and root.children[0].children:
            child = root.children[0]
            root = child
            root.up = None          # detach from phantom parent
            root.dist = 0.0         # root has no branch length

        newick_str = root.write(format=1)

        if fmt == "svg":
            # Try to render SVG using ETE3
            try:
                from ete3 import TreeStyle, TextFace, NodeStyle
                import tempfile
                import os

                ts = TreeStyle()
                ts.show_leaf_name = True
                ts.show_branch_length = False
                ts.show_branch_support = False
                ts.mode = "r"  # rectangular mode
                ts.branch_vertical_margin = 4
                ts.scale = 40
                ts.title.add_face(TextFace(f"Sampling result ({len(species)} species)", fsize=14), column=0)

                # Style internal nodes with rank labels
                for node in root.traverse():
                    ns = NodeStyle()
                    if node.is_leaf():
                        ns["fgcolor"] = "#2d8a4e"
                        ns["size"] = 4
                    else:
                        ns["fgcolor"] = "#555"
                        ns["size"] = 3
                    node.set_style(ns)

                # Render to SVG file
                with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, mode="w") as f:
                    tmp_path = f.name

                root.render(tmp_path, tree_style=ts, w=800, units="px")

                with open(tmp_path, "r", encoding="utf-8") as f:
                    svg_content = f.read()

                os.unlink(tmp_path)

                return JsonResponse({
                    "svg": svg_content,
                    "newick": newick_str,
                    "species_count": len(species),
                })

            except Exception as svg_err:
                # If SVG rendering fails (e.g., no display), return Newick only
                return JsonResponse({
                    "svg": None,
                    "newick": newick_str,
                    "species_count": len(species),
                    "svg_error": str(svg_err),
                })

        # Default: return Newick file download
        from django.http import HttpResponse
        resp = HttpResponse(newick_str, content_type="text/plain; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="sampling_taxonomic.newick"'
        return resp

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ═══════════════════════════════════════════════════════════════════════
# Assembly Filtering (Step 3)
# ═══════════════════════════════════════════════════════════════════════

@require_GET
def assembly_fields(request):
    """
    Return the field registry for assembly filtering UI.
    Includes field names, types, ranges, choices, and default weights.
    """
    from apps.taxonomy.sampling.assembly_engine import get_filter_fields
    return JsonResponse(get_filter_fields())


@csrf_exempt
@require_POST
def assembly_stats(request):
    """
    Get aggregate assembly statistics for a set of species accessions.

    POST body JSON:
      { "accessions": ["GCF_...", ...] }

    Returns min/max/avg for numeric fields and distributions for
    categorical fields.
    """
    from apps.taxonomy.sampling.assembly_engine import get_assembly_stats

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    accessions = data.get("accessions", [])
    if not accessions:
        return JsonResponse({"error": "No accessions provided"}, status=400)

    try:
        stats = get_assembly_stats(accessions)
        return JsonResponse(stats)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@require_POST
def assembly_filter(request):
    """
    Apply assembly filtering/scoring to the sampling result.

    POST body JSON:
      {
        "accessions": ["GCF_...", ...],
        "mode": "hard" | "scoring",
        "hard_filters": { "genome_coverage": {"min": 30}, ... },
        "categorical_filters": { "genome_level": ["Chromosome", "Complete Genome"], ... },
        "scoring_weights": { "genome_coverage": 0.3, "contig_n50_kb": 0.3, ... },
        "best_per_species": true
      }

    Returns filtered/scored species list with full assembly metadata.
    """
    from apps.taxonomy.sampling.assembly_engine import (
        run_assembly_filter,
        AssemblyFilterConfig,
    )

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    accessions = data.get("accessions", [])
    if not accessions:
        return JsonResponse({"error": "No accessions provided"}, status=400)

    mode = data.get("mode", "scoring")
    if mode not in ("hard", "scoring"):
        return JsonResponse({"error": f"Invalid mode: {mode}"}, status=400)

    config = AssemblyFilterConfig(
        mode=mode,
        hard_filters=data.get("hard_filters") or {},
        categorical_filters=data.get("categorical_filters") or {},
        scoring_weights=data.get("scoring_weights") or {},
        best_per_species=data.get("best_per_species", True),
    )

    try:
        result = run_assembly_filter(accessions, config)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({
        "success": True,
        "mode": result.mode,
        "input_species": result.input_species,
        "output_species": result.output_species,
        "filtered_out": result.filtered_out,
        "stats": result.stats,
        "warnings": result.warnings,
        "species": result.species,
    })


# =============================================================================
# Markdown rendering endpoint
# =============================================================================
@require_POST
def render_markdown(request):
    """
    Render Markdown text to HTML using Python's markdown library.
    Output is sanitized with bleach to prevent XSS attacks.
    
    POST body: { "text": "# Markdown content..." }
    Response: { "html": "<h1>Markdown content...</h1>" }
    """
    import markdown
    import bleach
    
    try:
        data = json.loads(request.body)
        text = data.get("text", "")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    
    # Render markdown with extensions
    raw_html = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "nl2br"]
    )
    
    # Sanitize HTML to prevent XSS - allow only safe tags and attributes
    allowed_tags = [
        "h1", "h2", "h3", "h4", "h5", "h6",
        "p", "br", "hr",
        "strong", "em", "b", "i", "u", "s", "code", "pre",
        "ul", "ol", "li",
        "table", "thead", "tbody", "tr", "th", "td",
        "blockquote", "a", "img",
    ]
    allowed_attrs = {
        "a": ["href", "title", "rel"],
        "img": ["src", "alt", "title"],
        "th": ["align"],
        "td": ["align"],
    }
    
    safe_html = bleach.clean(
        raw_html,
        tags=allowed_tags,
        attributes=allowed_attrs,
        strip=True
    )
    
    return JsonResponse({"html": safe_html})
