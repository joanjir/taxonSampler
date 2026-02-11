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
    path_key_from_parts,
    norm_rank,
    count_species_under,
)
from apps.taxonomy.services.sampling import run_sampling


# =============================================================================
# Helpers
# =============================================================================

_ROOT_RANKS_SET = {"domain", "superkingdom", "kingdom"}

def _normalize_path_for_key(path: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Normaliza classification_path para construir key.
    Detecta y corrige orden leaf->root si es necesario.
    """
    if not path:
        return []
    
    # Verificar si el path viene en orden leaf->root (último elemento es root)
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
        - limit: Max species to include (default: 5000)
        - max_rank or rankCut: Maximum rank to show (default: species = no cut)
        - expand_keys: Comma-separated keys to expand
    """
    limit = request.GET.get("limit", "5000")
    # Accept both 'max_rank' (backend standard) and 'rankCut' (frontend legacy)
    # Default to "" (only root visible, all data in _children for expand on click)
    max_rank = request.GET.get("max_rank") or request.GET.get("rankCut") or ""
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
    
    # Contar especies totales
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
    """
    query = request.GET.get("q", "").strip()
    limit = min(int(request.GET.get("limit", 50)), 200)
    
    if len(query) < 2:
        return JsonResponse({"hits": [], "query": query, "total": 0})
    
    # Buscar en ExternalTaxon (tiene classification_path para construir key)
    qs = (
        ExternalTaxon.objects
        .filter(
            Q(name__icontains=query) | Q(classification_path__icontains=query),
            system="col",
            status="accepted"
        )
        .only("id", "external_id", "name", "rank", "classification_path")
        [:limit]
    )
    
    hits = []
    for ext in qs:
        # Construir el key del árbol desde classification_path
        path = _normalize_path_for_key(ext.classification_path or [])
        # Agregar la especie al path si no está
        if ext.rank == "species":
            path = list(path) + [{"rank": "species", "name": ext.name}]
        
        # Construir key con prefijo "dataset:Root|" para coincidir con el árbol
        key = "dataset:Root|" + path_key_from_parts(path) if path else ""
        
        hits.append({
            "id": ext.id,
            "external_id": ext.external_id,
            "name": ext.name,
            "rank": ext.rank,
            "key": key,
        })
    
    return JsonResponse({
        "hits": hits,
        "query": query,
        "total": len(hits),
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
    from apps.taxonomy.services.sampling import TreeIndex
    
    scope_key = request.GET.get("scope_key", "").strip() or None
    target_keys_str = request.GET.get("target_keys", "").strip()
    active_key = request.GET.get("active_key", "").strip() or None
    
    target_keys = [k.strip() for k in target_keys_str.split(",") if k.strip()] if target_keys_str else []
    
    # Build tree index
    tree = build_tree_from_db(limit=10000, rank_cut="species", with_keys=True)
    if not tree:
        return JsonResponse({"error": "No tree data available"}, status=404)
    
    index = TreeIndex()
    index.build(tree)
    
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
            "limit": 5000,
            "max_rank": "class"
        }
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return HttpResponseBadRequest("JSON inválido")

    # Build tree from DB (same as tree_data endpoint)
    limit = int(payload.get("limit", 5000))
    max_rank = payload.get("max_rank") or "class"

    tree = build_tree_from_db(limit=limit, rank_cut=max_rank, with_keys=True)
    if not tree:
        return JsonResponse({"error": "No tree data available"}, status=404)

    # Expand all nodes so sampling can traverse the full tree
    # (the tree from build_tree_from_db might be cut at max_rank)
    full_tree = build_tree_from_db(limit=limit, rank_cut="species", with_keys=True)
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
    
    Lista de genomas NCBI con filtrado y paginación.
    
    Query params:
        - page: Número de página (default: 1)
        - page_size: Tamaño de página (default: 50, max: 200)
        - search: Búsqueda por nombre de organismo
        - phylum: Filtrar por phylum
        - class_name: Filtrar por clase
        - genome_level: Filtrar por nivel de genoma
        - col_match_status: Filtrar por estado de vinculación
        - ordering: Campo de ordenación (default: organism_name)
    """
    from apps.taxonomy.models import NCBIGenome
    
    # Paginación
    try:
        page = int(request.GET.get("page", 1))
        page_size = min(int(request.GET.get("page_size", 50)), 200)
    except ValueError:
        page, page_size = 1, 50
    
    # Filtros
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
        # needs_review filter should include both needs_review AND no_match
        if col_match_status == "needs_review":
            qs = qs.filter(Q(col_match_status="needs_review") | Q(col_match_status="no_match"))
        else:
            qs = qs.filter(col_match_status=col_match_status)
    
    # Filter by COL status (accepted, synonym, no_match)
    col_status = request.GET.get("col_status", "").strip()
    if col_status:
        if col_status == "no_match":
            # No COL match - external_taxon is null and col_match_status is no_match
            qs = qs.filter(col_match_status="no_match")
        else:
            # Filter by external_taxon.status
            qs = qs.filter(external_taxon__status=col_status)
    
    # Ordenación
    ordering = request.GET.get("ordering", "organism_name")
    valid_orderings = ["organism_name", "-organism_name", "accession", "-accession", 
                       "phylum", "-phylum", "genome_level", "-genome_level",
                       "col_match_status", "-col_match_status"]
    if ordering in valid_orderings:
        qs = qs.order_by(ordering)
    else:
        qs = qs.order_by("organism_name")
    
    # Conteo total
    total_count = qs.count()
    
    # Paginación
    offset = (page - 1) * page_size
    genomes = qs.select_related('external_taxon')[offset:offset + page_size]
    
    # Serializar
    results = []
    for g in genomes:
        # Obtener status de COL si existe
        col_status = None
        if g.external_taxon:
            col_status = g.external_taxon.status
        
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
    
    Detalle de un genoma por accession.
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
    
    Actualiza un genoma, principalmente para vincular con COL.
    
    Body JSON:
        - col_match_status: "matched" | "unmatched" | "needs_review" | "no_match"
        - external_taxon_id: ID del ExternalTaxon a vincular (o null para desvincular)
        - col_match_notes: notas sobre el matching
    """
    from apps.taxonomy.models import NCBIGenome
    
    try:
        genome = NCBIGenome.objects.get(accession=accession)
    except NCBIGenome.DoesNotExist:
        return JsonResponse({"error": f"Genome {accession} not found"}, status=404)
    
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    
    # Update col_match_status
    if "col_match_status" in data:
        valid_statuses = ["matched", "unmatched", "needs_review", "no_match"]
        if data["col_match_status"] in valid_statuses:
            genome.col_match_status = data["col_match_status"]
    
    # Update external_taxon
    if "external_taxon_id" in data:
        if data["external_taxon_id"]:
            try:
                external_taxon = ExternalTaxon.objects.get(id=data["external_taxon_id"])
                genome.external_taxon = external_taxon
                genome.col_match_status = "matched"
            except ExternalTaxon.DoesNotExist:
                return JsonResponse({"error": "ExternalTaxon not found"}, status=404)
        else:
            genome.external_taxon = None
            if genome.col_match_status == "matched":
                genome.col_match_status = "unmatched"
    
    # Update notes
    if "col_match_notes" in data:
        genome.col_match_notes = data["col_match_notes"]
    
    genome.save()
    
    return JsonResponse({
        "success": True,
        "accession": genome.accession,
        "col_match_status": genome.col_match_status,
        "external_taxon_id": genome.external_taxon_id,
        "col_match_notes": genome.col_match_notes,
    })


@require_GET
def col_search(request):
    """
    GET /api/v1/taxonomy/col/search/?q=query
    
    Busca taxones en COL por nombre. Para usar en el modal de edición.
    
    Query params:
        - q: Término de búsqueda (min 2 caracteres)
        - limit: Máximo de resultados (default: 20)
    """
    query = request.GET.get("q", "").strip()
    limit = min(int(request.GET.get("limit", 20)), 100)
    
    if len(query) < 2:
        return JsonResponse({"results": []})
    
    # Search in local ExternalTaxon database
    results = ExternalTaxon.objects.filter(
        Q(name__icontains=query) | Q(external_id__icontains=query),
        system="col",
        rank="species"
    ).select_related("accepted")[:limit]
    
    data = []
    for ext in results:
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
            "accepted_name": ext.accepted.name if ext.accepted else None,
        })
    
    return JsonResponse({"results": data})
