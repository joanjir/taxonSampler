from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from django.db.models import Q
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_GET, require_POST

from .models import ExternalTaxon


# -------------------------
# Config base (tu regla)
# -------------------------
BASE_FILTER = Q(system="col") & Q(rank="species") & Q(status="accepted")


ROOT_RANKS = {"domain", "superkingdom", "kingdom"}


def _parse_int(v: str | None, default: int, lo: int, hi: int) -> int:
    try:
        n = int(v) if v is not None else default
    except ValueError:
        n = default
    return max(lo, min(hi, n))


def _is_leaf_to_root(raw_path: List[Dict[str, Any]]) -> bool:
    if not raw_path:
        return False
    last_rank = (raw_path[-1].get("rank") or "").strip().lower()
    return last_rank in ROOT_RANKS


def _normalize_path(raw_path: Any) -> List[Tuple[str, str]]:
    """
    Normaliza classification_path a lista root->leaf de (rank,name).
    Elimina inválidos, y corrige el orden si viene leaf->root.
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

    # dedup consecutivo
    out: List[Tuple[str, str]] = []
    prev = None
    for item in clean:
        if item != prev:
            out.append(item)
        prev = item
    return out


def _parse_path_param(path_param: str | None) -> List[Tuple[str, str]]:
    """
    path llega como JSON serializado (urlencoded).
    Acepta [] o null como "raíz".
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
    if len(prefix) > len(full):
        return False
    return full[: len(prefix)] == prefix


def _get_next_after_prefix(full: List[Tuple[str, str]], prefix: List[Tuple[str, str]]) -> Tuple[str, str] | None:
    if not _path_starts_with(full, prefix):
        return None
    if len(full) == len(prefix):
        return None
    return full[len(prefix)]


def _has_children_for_prefix(full: List[Tuple[str, str]], prefix: List[Tuple[str, str]]) -> bool:
    return len(full) > len(prefix)


def _make_path_json(prefix: List[Tuple[str, str]]) -> List[Dict[str, str]]:
    return [{"rank": r, "name": n} for r, n in prefix]


# -------------------------
# Endpoints
# -------------------------
@require_GET
def next_ranks(request):
    """
    GET /api/col/next-ranks/?dataset_code=COL25.12&path=[...]
    Devuelve los ranks que aparecen inmediatamente después del path.
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
        .filter(BASE_FILTER, dataset_code=dataset_code)
        .only("classification_path")
        .iterator(chunk_size=2000)
    )

    counts: Dict[str, Dict[str, int]] = {}  # rank -> {"species": int, "names": set size tracked approximately}
    # Para no guardar sets gigantes por rank, contamos nombres con un set por rank pero acotado.
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

    # Orden: por count_species desc, luego rank asc (estable)
    out.sort(key=lambda x: (-x["count_species"], x["rank"]))

    return JsonResponse({
        "dataset_code": dataset_code,
        "path": _make_path_json(prefix),
        "scanned_species": scanned if scanned <= limit_scan else limit_scan,
        "next_ranks": out,
    })


@require_GET
def nodes(request):
    """
    GET /api/col/nodes/?dataset_code=...&path=[...]&rank=class&offset=0&limit=200
    Devuelve los nombres de 'rank' bajo 'path' con conteos.
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
        .filter(BASE_FILTER, dataset_code=dataset_code)
        .only("classification_path")
        .iterator(chunk_size=2000)
    )

    counts: Dict[str, int] = {}         # name -> count_species
    has_child_map: Dict[str, bool] = {} # name -> has_children (más niveles debajo del nodo rank)
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

        # has_children: si después de ese nodo hay más clasificación (o species)
        # full index del nodo = len(prefix)
        node_prefix = prefix + [(nxt_rank, nxt_name)]
        has_children = _has_children_for_prefix(full, node_prefix)
        if nxt_name not in has_child_map:
            has_child_map[nxt_name] = has_children
        else:
            has_child_map[nxt_name] = has_child_map[nxt_name] or has_children

    # Orden: por count desc, luego name asc
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
def species(request):
    """
    GET /api/col/species/?dataset_code=...&path=[...]&offset=0&limit=200
    Lista especies accepted bajo el path.
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
        .filter(BASE_FILTER, dataset_code=dataset_code)
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

    # orden alfabético para especies
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
def resolve_selection(request):
    """
    POST /api/col/resolve/
    Body:
      {"dataset_code":"COL25.12","selected_paths":[ [...], [...] ]}
    Devuelve especies accepted únicas bajo la unión de paths.
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

    # si no hay nada válido, retorna vacío
    prefixes = [p for p in prefixes if p]
    if not prefixes:
        return JsonResponse({"dataset_code": dataset_code, "species": []})

    limit_scan = 500000

    qs = (
        ExternalTaxon.objects
        .filter(BASE_FILTER, dataset_code=dataset_code)
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
