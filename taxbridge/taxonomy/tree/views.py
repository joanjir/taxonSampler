from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from taxonomy.models import ExternalTaxon
from .filters import cut_tree_by_rank  # <-- nuevo


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

    if _is_leaf_to_root(path):
        clean.reverse()

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
        kids = [c.to_d3() for c in sorted(self.children.values(), key=lambda n: (n.rank, n.name))]
        obj = {"name": self.name, "rank": self.rank}
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

    rank_cut = request.GET.get("rankCut", None)
    if rank_cut is None:
        rank_cut = request.GET.get("rank_cut", "")

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
