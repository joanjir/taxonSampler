from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple, Optional

from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_GET

from .models import ExternalTaxon


ROOT_RANKS = {"domain", "superkingdom", "kingdom"}


def _is_leaf_to_root(path: List[Dict[str, Any]]) -> bool:
    """
    Heurística: si el ÚLTIMO rank parece root (domain/kingdom), probablemente viene leaf->root.
    """
    if not path:
        return False
    last_rank = (path[-1].get("rank") or "").strip().lower()
    return last_rank in ROOT_RANKS


def _normalize_path(path: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """
    Retorna lista ordenada root->leaf de tuplas (rank, name), eliminando entradas inválidas.
    """
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

    if _is_leaf_to_root(path):
        clean.reverse()

    # dedup consecutivo (por si hay repeticiones)
    out: List[Tuple[str, str]] = []
    prev = None
    for item in clean:
        if item != prev:
            out.append(item)
        prev = item
    return out


@dataclass
class TrieNode:
    name: str
    rank: str
    meta: Dict[str, Any] = field(default_factory=dict)
    children: Dict[Tuple[str, str], "TrieNode"] = field(default_factory=dict)

    def to_d3(self) -> Dict[str, Any]:
        # children ordenados por rank, luego name (estable para UI)
        kids = [c.to_d3() for c in sorted(self.children.values(), key=lambda n: (n.rank, n.name))]
        obj = {"name": self.name, "rank": self.rank}
        if self.meta:
            obj.update(self.meta)
        if kids:
            obj["children"] = kids
        return obj


@require_GET
def tree_data(request):
    """
    Construye el árbol desde ExternalTaxon.classification_path + especies.
    """
    dataset_code = (request.GET.get("dataset_code") or "").strip()
    if not dataset_code:
        return HttpResponseBadRequest("dataset_code es requerido (ej. COL25.12)")

    try:
        limit = int(request.GET.get("limit", "5000"))
    except ValueError:
        limit = 5000
    limit = max(1, min(limit, 200000))

    qs = (
        ExternalTaxon.objects
        .filter(system="col", dataset_code=dataset_code, rank="species", status="accepted")
        .only("id", "external_id", "name", "rank", "classification_path")
        .order_by("id")[:limit]
    )

    root = TrieNode(name=f"Dataset {dataset_code}", rank="dataset")

    for sp in qs:
        path = _normalize_path(sp.classification_path)

        cur = root
        for rank, name in path:
            key = (rank, name)
            if key not in cur.children:
                cur.children[key] = TrieNode(name=name, rank=rank)
            cur = cur.children[key]

        # agrega especie como hoja
        sp_key = ("species", sp.name)
        if sp_key not in cur.children:
            cur.children[sp_key] = TrieNode(
                name=sp.name,
                rank="species",
                meta={"id": sp.id, "external_id": sp.external_id},
            )

    return JsonResponse(root.to_d3(), safe=True)
