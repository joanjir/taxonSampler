# taxonomy/services/checklistbank.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://api.checklistbank.org"


def canonicalize_scientific_name(name: str) -> str:
    s = (name or "").strip()
    s = re.sub(r"\s+\([^)]*\)", "", s)  # Mus (Mus) musculus -> Mus musculus
    s = re.sub(r"\s+", " ", s)
    return s


def classification_list_normalized(classification: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Devuelve la clasificación como LISTA ORDENADA (root->leaf) tal como viene de CoL,
    normalizando claves a {rank, name}.
    """
    out: List[Dict[str, str]] = []
    for node in classification or []:
        r = (node.get("rank") or "").strip()
        n = (node.get("name") or "").strip()
        if r and n:
            out.append({"rank": r, "name": n})
    return out


def classification_list_to_dict(classification: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Derivado: dict rank -> name (pierde el orden). Útil para filtros, NO para el árbol.
    """
    out: Dict[str, str] = {}
    for node in classification_list_normalized(classification):
        out[node["rank"]] = node["name"]
    return out


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    external_id: Optional[str]
    name: Optional[str]
    rank: Optional[str]
    status: Optional[str]
    authorship: Optional[str]

    # LO IMPORTANTE:
    classification_path: List[Dict[str, str]]  # lista ordenada
    classification: Dict[str, str]             # dict derivado (opcional)

    raw: Dict[str, Any]


class ChecklistBankClient:
    def __init__(self, base_url: str = BASE_URL, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

        retry = Retry(
            total=6,
            connect=3,
            read=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def match_nameusage(
        self,
        dataset: str,
        scientific_name: str,
        rank: Optional[str] = None,
        kingdom: Optional[str] = None,
    ) -> MatchResult:
        url = f"{self.base_url}/dataset/{dataset}/match/nameusage"
        params: Dict[str, str] = {"scientificName": scientific_name}
        if rank:
            params["rank"] = rank
        if kingdom:
            params["kingdom"] = kingdom

        r = self.session.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        payload: Dict[str, Any] = r.json() or {}

        usage = payload.get("usage") if isinstance(payload, dict) else None
        if not usage:
            usage = payload if isinstance(payload, dict) else {}

        ext_id = usage.get("id")
        if not ext_id:
            return MatchResult(
                matched=False,
                external_id=None,
                name=None,
                rank=None,
                status=None,
                authorship=None,
                classification_path=[],
                classification={},
                raw=payload,
            )

        cls_raw = usage.get("classification") or []
        cls_path = classification_list_normalized(cls_raw)
        cls_dict = classification_list_to_dict(cls_raw)

        return MatchResult(
            matched=True,
            external_id=str(ext_id),
            name=usage.get("name") or usage.get("label") or scientific_name,
            rank=usage.get("rank"),
            status=(usage.get("status") or "unknown"),
            authorship=usage.get("authorship"),
            classification_path=cls_path,
            classification=cls_dict,
            raw=payload,
        )
