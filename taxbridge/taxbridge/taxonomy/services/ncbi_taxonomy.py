import time
import requests
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, Optional


EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


@dataclass
class NcbiTaxonRecord:
    taxid: int
    scientific_name: str
    rank: str
    parent_taxid: Optional[int]
    lineage: Dict[str, str]
    raw: Dict


def _text(node):
    return node.text.strip() if node is not None and node.text else ""


def resolve_name_to_taxon(name, api_key=None, sleep_s=0.12, timeout=30):
    params = {
        "db": "taxonomy",
        "term": f"\"{name}\"[Scientific Name]",
        "retmode": "xml",
        "retmax": 5,
    }
    if api_key:
        params["api_key"] = api_key

    r = requests.get(f"{EUTILS_BASE}/esearch.fcgi", params=params, timeout=timeout)
    r.raise_for_status()
    root = ET.fromstring(r.text)

    ids = [x.text for x in root.findall(".//Id") if x.text]
    if not ids:
        return None

    taxid = int(ids[0])
    time.sleep(sleep_s)

    r = requests.get(
        f"{EUTILS_BASE}/efetch.fcgi",
        params={"db": "taxonomy", "id": taxid, "retmode": "xml"},
        timeout=timeout,
    )
    r.raise_for_status()
    root = ET.fromstring(r.text)

    taxon = root.find(".//Taxon")
    sci = _text(taxon.find("ScientificName"))
    rank = _text(taxon.find("Rank"))
    parent = _text(taxon.find("ParentTaxId"))
    parent_taxid = int(parent) if parent.isdigit() else None

    lineage = {}
    for t in taxon.findall(".//LineageEx/Taxon"):
        rnk = _text(t.find("Rank")).lower()
        nm = _text(t.find("ScientificName"))
        if rnk and nm:
            lineage[rnk] = nm

    lineage[rank.lower()] = sci

    return NcbiTaxonRecord(
        taxid=taxid,
        scientific_name=sci,
        rank=rank,
        parent_taxid=parent_taxid,
        lineage=lineage,
        raw={"source": "ncbi_taxonomy"},
    )
