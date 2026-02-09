from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any, Dict, List, Tuple, Set

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt

from apps.taxonomy.models import ExternalTaxon
from apps.taxonomy.services.tree_builder import (
    build_tree_from_db,
    cut_by_rank,
    expand_to_keys,
    find_node_by_key,
    count_species_under,
    list_clades_at_rank,
    path_key_from_parts,
    parse_key_parts,
    norm_rank,
    RANK_ORDER,
)

ROOT_RANKS = {"domain", "superkingdom", "kingdom"}


def _parts_to_label(parts: List[Dict[str, str]]) -> str:
    """Genera label legible desde partes."""
    return " / ".join([f"{p.get('rank') or '?'}:{p.get('name') or ''}" for p in parts])


def _parse_include(v: str) -> Set[str]:
    """Parsea parámetro include=species,nodes."""
    s = (v or "").strip().lower()
    if not s:
        return {"species", "nodes"}
    return {x.strip() for x in s.split(",") if x.strip()}


def _normalize_classification_path(path: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """Normaliza classification_path de la BD a lista de (rank, name)."""
    if not isinstance(path, list):
        return []
    
    clean: List[Tuple[str, str]] = []
    for x in path:
        if not isinstance(x, dict):
            continue
        rank = (x.get("rank") or "").strip()
        name = (x.get("name") or "").strip()
        if not rank or not name:
            continue
        clean.append((rank.lower(), name))
    
    # Detectar y corregir orden leaf->root
    if clean and clean[-1][0] in ROOT_RANKS:
        clean.reverse()
    
    # Quitar duplicados consecutivos
    out: List[Tuple[str, str]] = []
    prev = None
    for item in clean:
        if item != prev:
            out.append(item)
        prev = item
    
    return out


# ============================================================
# Endpoints del árbol
# ============================================================

@require_GET
def tree_data(request):
    """
    Endpoint principal: devuelve el árbol taxonómico.
    
    Params:
        - limit: máximo de especies (default: 5000)
        - rankCut: rank hasta el cual expandir (default: None = todo expandido)
        - expand: keys a expandir separados por coma
    """
    try:
        limit = int(request.GET.get("limit", "5000"))
    except ValueError:
        limit = 5000
    limit = max(1, min(limit, 200000))

    rank_cut = request.GET.get("rankCut") or request.GET.get("rank_cut")
    expand_keys = request.GET.get("expand", "")
    
    # Construir árbol usando el servicio unificado
    tree = build_tree_from_db(
        limit=limit,
        system="col",
        rank_cut=rank_cut,
        with_keys=True,
    )
    
    # Expandir rutas específicas si se solicita
    if expand_keys:
        keys = [k.strip() for k in expand_keys.split(",") if k.strip()]
        if keys:
            tree = expand_to_keys(tree, keys)
    
    return JsonResponse(tree, safe=True)


@require_GET
def tree_search(request):
    """
    Backend-driven search.

    Params:
      - q: query string (min len 2)
      - include: "species,nodes" (default ambos)
      - limit: page size
      - offset: pagination offset
      - nodes_scan_limit: cuántos species se escanean para encontrar matches en paths
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

    # A) Species hits (rápido)
    if "species" in include:
        sp_qs = (
            ExternalTaxon.objects
            .filter(system="col", rank="species", status="accepted")
            .filter(name__icontains=q)
            .only("id", "external_id", "name", "classification_path")
            .order_by("name")[:5000]
        )

        for rec in sp_qs:
            path = _normalize_classification_path(rec.classification_path)
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
                "label": _parts_to_label(parts),
                "kind": "species",
            }

    # B) Node hits dentro de classification_path
    #    (esto es lo que te faltaba para que "hom" devuelva Homo/Hominidae/etc)
    if "nodes" in include:
        scanned = True
        try:
            nodes_scan_limit = int(request.GET.get("nodes_scan_limit", "20000"))
        except ValueError:
            nodes_scan_limit = 20000
        nodes_scan_limit = max(1, min(nodes_scan_limit, 50000))

        scan_qs = (
            ExternalTaxon.objects
            .filter(system="col", rank="species", status="accepted")
            .only("classification_path")
            .order_by("id")[:nodes_scan_limit]
        )

        for sp in scan_qs:
            path = _normalize_classification_path(sp.classification_path)
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
                        "label": _parts_to_label(parts_prefix),
                        "kind": "node",
                    }

    # Orden: exact/prefix/contains + profundidad
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


def tree_page(request):
    return render(request, "taxonomy/pages/tree/index.html", {})
