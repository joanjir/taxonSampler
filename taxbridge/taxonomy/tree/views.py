from __future__ import annotations

import json
from dataclasses import dataclass, field
from collections import OrderedDict
from typing import Any, Dict, List, Tuple, Set

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt

from taxonomy.models import ExternalTaxon
from taxonomy.services.sampling import run_sampling, RANK_ORDER as SAMPLING_RANK_ORDER
from taxonomy.services.tree_queries import (
    get_rank_config,
    search_taxa,
    find_node_by_key,
    count_species_under_node,
    list_children_clades,
    list_clades_at_rank,
    parse_key_parts,
    path_key_from_parts,
)
from .filters import cut_tree_by_rank

ROOT_RANKS = {"domain", "superkingdom", "kingdom"}


def _is_leaf_to_root(path: List[Dict[str, Any]]) -> bool:
    if not path:
        return False
    last_rank = (path[-1].get("rank") or "").strip().lower()
    return last_rank in ROOT_RANKS


def _normalize_path(path: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
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

    # si viene leaf->root, invertir
    if _is_leaf_to_root(path):
        clean.reverse()

    # quitar duplicados consecutivos
    out: List[Tuple[str, str]] = []
    prev = None
    for item in clean:
        if item != prev:
            out.append(item)
        prev = item
    return out


def _parts_to_key(parts: List[Dict[str, str]]) -> str:
    # debe matchear frontend: `${rank}:${name}` join("|")
    return "|".join([f"{(p.get('rank') or '?').lower()}:{p.get('name') or ''}" for p in parts])


def _parts_to_label(parts: List[Dict[str, str]]) -> str:
    return " / ".join([f"{p.get('rank') or '?'}:{p.get('name') or ''}" for p in parts])


def _parse_include(v: str) -> Set[str]:
    """
    include=species,nodes
    default: {"species","nodes"}
    """
    s = (v or "").strip().lower()
    if not s:
        return {"species", "nodes"}
    return {x.strip() for x in s.split(",") if x.strip()}


@dataclass
class TrieNode:
    name: str
    rank: str
    meta: Dict[str, Any] = field(default_factory=dict)
    children: Dict[Tuple[str, str], "TrieNode"] = field(default_factory=dict)

    def to_d3(self) -> Dict[str, Any]:
        kids = [c.to_d3() for c in sorted(self.children.values(), key=lambda n: (n.rank, n.name))]
        obj: Dict[str, Any] = {"name": self.name, "rank": self.rank}
        if self.meta:
            obj.update(self.meta)
        if kids:
            obj["children"] = kids
        return obj


@require_GET
def tree_data(request):
    try:
        limit = int(request.GET.get("limit", "5000"))
    except ValueError:
        limit = 5000
    limit = max(1, min(limit, 200000))

    # rank_cut solo se aplica si el parámetro vino en la request.
    # - Si NO viene => None => NO se corta.
    # - Si viene vacío (rankCut=) => "" => cut_tree_by_rank colapsa a ROOT.
    rank_cut = request.GET.get("rankCut", None)
    if rank_cut is None:
        rank_cut = request.GET.get("rank_cut", None)

    qs = (
        ExternalTaxon.objects
        .filter(system="col", rank="species", status="accepted")
        .only("id", "external_id", "name", "rank", "classification_path")
        .order_by("id")[:limit]
    )

    root = TrieNode(name="Root", rank="dataset")

    for sp in qs:
        path = _normalize_path(sp.classification_path)

        cur = root
        for rank, name in path:
            key = (rank, name)
            if key not in cur.children:
                cur.children[key] = TrieNode(name=name, rank=rank)
            cur = cur.children[key]

        sp_key = ("species", sp.name)
        if sp_key not in cur.children:
            cur.children[sp_key] = TrieNode(
                name=sp.name,
                rank="species",
                meta={"id": sp.id, "external_id": sp.external_id},
            )

    data = root.to_d3()

    if rank_cut is not None:
        data = cut_tree_by_rank(data, rank_cut) or data

    return JsonResponse(data, safe=True)


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
            path = _normalize_path(rec.classification_path)
            parts = [{"rank": "dataset", "name": "Root"}] + [{"rank": r, "name": n} for r, n in path] + [
                {"rank": "species", "name": rec.name}
            ]
            k = _parts_to_key(parts)
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
            path = _normalize_path(sp.classification_path)
            if not path:
                continue

            parts_prefix = [{"rank": "dataset", "name": "Root"}]
            for (r, n) in path:
                parts_prefix.append({"rank": r, "name": n})
                if q_lc in (n or "").lower():
                    k = _parts_to_key(parts_prefix)
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
