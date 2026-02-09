"""
API views for taxonomy module.

All JSON API endpoints are consolidated here following Django best practices.
Separated from UI views which render HTML templates.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from django.db.models import Q
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_GET, require_POST

from apps.taxonomy.models import ExternalTaxon, Taxon
from apps.taxonomy.services.tree_builder import (
    build_tree_from_db,
    expand_to_keys,
)


# =============================================================================
# Tree API Endpoints
# =============================================================================

@require_GET
def tree_data(request):
    """
    GET /api/v1/taxonomy/tree/data/
    
    Returns tree JSON for D3 visualization.
    
    Query params:
        - limit: Max species to include (default: 5000)
        - max_rank: Maximum rank to show (default: class)
        - expand_keys: Comma-separated keys to expand
    """
    limit = request.GET.get("limit", "5000")
    max_rank = request.GET.get("max_rank", "class")
    expand_keys_str = request.GET.get("expand_keys", "")
    
    try:
        limit = int(limit)
    except ValueError:
        limit = 5000
    
    expand_keys = [k.strip() for k in expand_keys_str.split(",") if k.strip()]
    
    # Build tree from database
    tree = build_tree_from_db(limit=limit, rank_cut=max_rank, with_keys=True)
    
    if not tree:
        return JsonResponse({"error": "No se encontró el árbol"}, status=404)
    
    # Expand specific keys if provided
    if expand_keys:
        tree = expand_to_keys(tree, expand_keys)
    
    return JsonResponse({
        "tree": tree,
        "limit": limit,
        "max_rank": max_rank,
        "expanded_keys": expand_keys,
    })


@require_GET
def tree_search(request):
    """
    GET /api/v1/taxonomy/tree/search/?q=<query>
    
    Search taxa by name.
    
    Query params:
        - q: Search query (min 2 characters)
        - limit: Max results (default: 50, max: 200)
    """
    query = request.GET.get("q", "").strip()
    limit = min(int(request.GET.get("limit", 50)), 200)
    
    if len(query) < 2:
        return JsonResponse({"results": [], "query": query})
    
    results = Taxon.objects.filter(
        scientific_name__icontains=query
    ).values(
        "tax_id", "scientific_name", "rank", "parent_tax_id"
    )[:limit]
    
    return JsonResponse({
        "results": list(results),
        "query": query,
        "count": len(results),
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
        raise ValueError("path no es JSON válido")

    if obj is None:
        return []
    if not isinstance(obj, list):
        raise ValueError("path debe ser una lista JSON")

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
        return HttpResponseBadRequest("dataset_code es requerido")

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
        return HttpResponseBadRequest("dataset_code es requerido")

    rank = (request.GET.get("rank") or "").strip().lower()
    if not rank:
        return HttpResponseBadRequest("rank es requerido")

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
        return HttpResponseBadRequest("dataset_code es requerido")

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
        return HttpResponseBadRequest("JSON inválido")

    dataset_code = (payload.get("dataset_code") or "").strip()
    if not dataset_code:
        return HttpResponseBadRequest("dataset_code es requerido")

    selected_paths = payload.get("selected_paths")
    if not isinstance(selected_paths, list):
        return HttpResponseBadRequest("selected_paths debe ser una lista")

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
