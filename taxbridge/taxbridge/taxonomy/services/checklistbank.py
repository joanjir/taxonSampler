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
    """
    Canonicalización conservadora:
    - Quita subgénero "Mus (Mus) musculus" -> "Mus musculus"
    - Colapsa espacios
    """
    s = (name or "").strip()
    s = re.sub(r"\s+\([^)]*\)", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def classification_list_to_dict(classification: List[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for node in classification or []:
        r = (node.get("rank") or "").strip()
        n = (node.get("name") or "").strip()
        if r and n:
            # ChecklistBank suele entregar ranks en mayúsculas o TitleCase según endpoint
            out[r.lower()] = n
    return out


def _pick_usage(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    ChecklistBank match endpoint normalmente responde:
      { "usage": {...}, "match": true/false, "type": "...", ... }
    pero puede variar. Esto centraliza la extracción de usage.
    """
    if not isinstance(payload, dict):
        return {}

    usage = payload.get("usage")
    if isinstance(usage, dict) and usage:
        return usage

    # fallback: a veces devuelven el objeto directo (raro)
    if "id" in payload and ("name" in payload or "label" in payload):
        return payload

    return {}


def _extract_parent_external_id(usage: Dict[str, Any]) -> str:
    """
    En 'usage' a menudo hay:
      - parent: {"id": "..."} o parent: "..."
    """
    parent = usage.get("parent")
    if isinstance(parent, dict):
        pid = parent.get("id")
        return str(pid) if pid else ""
    if isinstance(parent, (str, int)):
        return str(parent)
    return ""


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    external_id: Optional[str]
    name: Optional[str]
    rank: Optional[str]
    status: Optional[str]
    authorship: Optional[str]
    classification: Dict[str, str]
    parent_external_id: str
    raw: Dict[str, Any]


class ChecklistBankClient:
    """
    Cliente HTTP con retries y timeouts razonables.
    """

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
        """
        Usa /dataset/{ds}/match/nameusage.
        Devuelve MatchResult normalizado.
        """
        url = f"{self.base_url}/dataset/{dataset}/match/nameusage"
        params: Dict[str, str] = {"scientificName": scientific_name}
        if rank:
            params["rank"] = rank
        if kingdom:
            params["kingdom"] = kingdom

        r = self.session.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()

        payload: Dict[str, Any] = r.json() or {}
        usage = _pick_usage(payload)

        # Señales típicas de "no match"
        match_flag = payload.get("match")
        type_flag = (payload.get("type") or "").lower()

        ext_id = usage.get("id")
        if ext_id is None or ext_id == "":
            return MatchResult(
                matched=False,
                external_id=None,
                name=None,
                rank=None,
                status=None,
                authorship=None,
                classification={},
                parent_external_id="",
                raw=payload,
            )

        # Si la API explícitamente dice match=false o type=none, igual lo tratamos como no match
        # aunque exista algo raro en usage. (Conservador).
        if match_flag is False or type_flag in {"none", "no_match"}:
            return MatchResult(
                matched=False,
                external_id=None,
                name=None,
                rank=None,
                status=None,
                authorship=None,
                classification={},
                parent_external_id="",
                raw=payload,
            )

        classification = classification_list_to_dict(usage.get("classification") or [])
        parent_external_id = _extract_parent_external_id(usage)

        return MatchResult(
            matched=True,
            external_id=str(ext_id),
            name=usage.get("name") or usage.get("label") or scientific_name,
            rank=usage.get("rank"),
            status=(usage.get("status") or "unknown"),
            authorship=usage.get("authorship"),
            classification=classification,
            parent_external_id=parent_external_id,
            raw=payload,
        )
