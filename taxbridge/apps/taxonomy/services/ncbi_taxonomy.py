# taxbridge/taxonomy/services/ncbi_taxonomy.py
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, Optional

import requests

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


@dataclass(frozen=True)
class NcbiTaxonRecord:
    taxid: int
    scientific_name: str
    rank: str
    parent_taxid: Optional[int]
    lineage: Dict[str, str]
    raw: Dict


def _text(node) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.strip()


class NcbiTaxonomyClient:
    """
    Cliente mínimo para resolver nombres científicos a taxid (NCBI Taxonomy).
    Conservador: 1) esearch por Scientific Name 2) efetch del primer taxid.
    """

    def __init__(
        self,
        api_key: str | None = None,
        sleep_s: float = 0.12,
        timeout: int = 30,
        user_agent: str = "TaxBridge/0.1",
    ):
        self.api_key = api_key
        self.sleep_s = sleep_s
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def esearch_taxid(self, scientific_name: str) -> Optional[int]:
        params = {
            "db": "taxonomy",
            "term": f"\"{scientific_name}\"[Scientific Name]",
            "retmode": "xml",
            "retmax": 5,
        }
        if self.api_key:
            params["api_key"] = self.api_key

        r = self.session.get(f"{EUTILS_BASE}/esearch.fcgi", params=params, timeout=self.timeout)
        r.raise_for_status()

        root = ET.fromstring(r.text)
        ids = [x.text for x in root.findall(".//Id") if x is not None and x.text]
        if not ids:
            return None
        try:
            return int(ids[0])
        except ValueError:
            return None

    def efetch_taxon(self, taxid: int) -> Optional[NcbiTaxonRecord]:
        time.sleep(self.sleep_s)

        params = {"db": "taxonomy", "id": str(taxid), "retmode": "xml"}
        if self.api_key:
            params["api_key"] = self.api_key

        r = self.session.get(f"{EUTILS_BASE}/efetch.fcgi", params=params, timeout=self.timeout)
        r.raise_for_status()

        root = ET.fromstring(r.text)
        taxon = root.find(".//Taxon")
        if taxon is None:
            return None

        sci = _text(taxon.find("ScientificName"))
        rank = _text(taxon.find("Rank"))
        parent = _text(taxon.find("ParentTaxId"))
        parent_taxid = int(parent) if parent.isdigit() else None

        lineage: Dict[str, str] = {}
        for t in taxon.findall(".//LineageEx/Taxon"):
            rnk = _text(t.find("Rank")).lower()
            nm = _text(t.find("ScientificName"))
            if rnk and nm:
                lineage[rnk] = nm

        # Incluye el propio taxón como última entrada
        if rank:
            lineage[rank.lower()] = sci

        return NcbiTaxonRecord(
            taxid=taxid,
            scientific_name=sci,
            rank=rank,
            parent_taxid=parent_taxid,
            lineage=lineage,
            raw={
                "source": "ncbi_taxonomy",
                "query": sci,
                "taxid": taxid,
            },
        )


def resolve_name_to_taxon(
    name: str,
    api_key: str | None = None,
    sleep_s: float = 0.12,
    timeout: int = 30,
) -> Optional[NcbiTaxonRecord]:
    """
    Helper compatible con tu comando.
    """
    client = NcbiTaxonomyClient(api_key=api_key, sleep_s=sleep_s, timeout=timeout)
    taxid = client.esearch_taxid(name)
    if taxid is None:
        return None
    return client.efetch_taxon(taxid)
