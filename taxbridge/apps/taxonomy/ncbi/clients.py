# apps/taxonomy/clients.py
"""
HTTP clients for external APIs.

This module contains reusable HTTP clients for:
- ChecklistBank (Catalogue of Life)
- NCBI Datasets API

These are infrastructure classes, not business logic.
Business logic should be in model methods/managers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# Helpers
# ============================================================

def canonicalize_scientific_name(name: str) -> str:
    """Normalize scientific name:
    - Mus (Mus) musculus -> Mus musculus
    - Candida dubliniensis CD36 -> Candida dubliniensis
    - Trichomonas vaginalis G3 -> Trichomonas vaginalis
    - Aegilops tauschii subsp. strangulata -> Aegilops tauschii subsp. strangulata  (kept)
    - Brassica oleracea var. oleracea -> Brassica oleracea var. oleracea  (kept)
    Keeps genus + species for binomial names, but preserves infraspecific markers
    (subsp., var., f., f. sp.).
    """
    s = (name or "").strip()
    # Remove subgenus in parentheses: Mus (Mus) musculus -> Mus musculus
    s = re.sub(r"\s+\([^)]*\)", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    # For binomial+ names, decide what to keep
    parts = s.split()
    if len(parts) > 2:
        third = parts[2]
        # Infraspecific markers: keep genus + species + marker + epithet
        if third.lower().rstrip(".") in ("subsp", "var", "f"):
            # "f. sp." is a special case (forma specialis): keep 4 words after genus+species
            if third.lower() == "f." and len(parts) > 3 and parts[3].lower() == "sp.":
                s = " ".join(parts[:5]) if len(parts) >= 5 else " ".join(parts[:4])
            else:
                s = " ".join(parts[:4]) if len(parts) >= 4 else s
        elif third[0].isupper() or third[0].isdigit():
            # Likely a strain suffix (G3, CD36, CBS 6074) - remove it
            s = " ".join(parts[:2])
    return s


# Infraspecific rank markers -> COL API rank value
_INFRASPECIFIC_MARKERS = {
    "subsp.": "subspecies",
    "var.": "variety",
    "f.": "form",
    "f. sp.": "form",  # forma specialis
}


def detect_infraspecific_rank(name: str) -> Optional[str]:
    """If the scientific name contains an infraspecific marker (subsp., var., f.),
    return the corresponding COL rank (subspecies, variety, form).
    Returns None for plain binomial names."""
    lower = (name or "").lower()
    # Check "f. sp." first (more specific)
    if " f. sp. " in lower:
        return "form"
    for marker, rank in _INFRASPECIFIC_MARKERS.items():
        if f" {marker} " in lower or lower.endswith(f" {marker}"):
            return rank
    return None


def classification_list_normalized(classification: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Normalize classification to an ordered list of {rank, name}."""
    out: List[Dict[str, str]] = []
    for node in classification or []:
        r = (node.get("rank") or "").strip()
        n = (node.get("name") or "").strip()
        if r and n:
            out.append({"rank": r, "name": n})
    return out


def classification_list_to_dict(classification: List[Dict[str, Any]]) -> Dict[str, str]:
    """Convert classification to dict rank -> name."""
    out: Dict[str, str] = {}
    for node in classification_list_normalized(classification):
        out[node["rank"]] = node["name"]
    return out


# ============================================================
# ChecklistBank (Catalogue of Life)
# ============================================================

COL_BASE_URL = "https://api.checklistbank.org"


@dataclass(frozen=True)
class COLMatchResult:
    """Result from COL name matching."""
    matched: bool
    external_id: Optional[str]
    name: Optional[str]
    rank: Optional[str]
    status: Optional[str]
    authorship: Optional[str]
    classification_path: List[Dict[str, str]]
    classification: Dict[str, str]
    raw: Dict[str, Any]


class ChecklistBankClient:
    """HTTP client for ChecklistBank API (Catalogue of Life)."""
    
    def __init__(self, base_url: str = COL_BASE_URL, timeout: int = 30):
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
    ) -> COLMatchResult:
        """Match a scientific name against COL.
        
        First tries the match endpoint. If no match found, falls back to search.
        Automatically detects infraspecific markers (subsp., var., f.) in the name
        and overrides the rank parameter accordingly.
        """
        # Detect infraspecific rank from the name itself (overrides NCBI rank)
        infraspecific_rank = detect_infraspecific_rank(scientific_name)
        effective_rank = infraspecific_rank or rank

        # Try match endpoint first
        url = f"{self.base_url}/dataset/{dataset}/match/nameusage"
        params: Dict[str, str] = {"scientificName": scientific_name}
        if effective_rank:
            params["rank"] = effective_rank
        if kingdom:
            params["kingdom"] = kingdom

        r = self.session.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        payload: Dict[str, Any] = r.json() or {}

        usage = payload.get("usage") if isinstance(payload, dict) else None
        if not usage:
            usage = payload if isinstance(payload, dict) else {}

        ext_id = usage.get("id")
        
        # If match endpoint didn't find anything, try search as fallback
        if not ext_id:
            search_result = self._search_nameusage(dataset, scientific_name, effective_rank)
            if search_result:
                return search_result
            # No match from either endpoint
            return COLMatchResult(
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

        return COLMatchResult(
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

    def _search_nameusage(
        self,
        dataset: str,
        scientific_name: str,
        rank: Optional[str] = None,
    ) -> Optional[COLMatchResult]:
        """Search for a species in COL using the search endpoint (fallback)."""
        url = f"{self.base_url}/dataset/{dataset}/nameusage/search"
        params: Dict[str, str] = {"q": scientific_name, "limit": "1"}
        if rank:
            params["rank"] = rank

        try:
            r = self.session.get(url, params=params, timeout=self.timeout)
            r.raise_for_status()
            data: Dict[str, Any] = r.json() or {}
            
            results = data.get("result", [])
            if not results:
                return None
            
            hit = results[0]
            # The search endpoint wraps data under "usage"
            usage = hit.get("usage") or hit
            ext_id = usage.get("id") or hit.get("id")
            if not ext_id:
                return None
            
            cls_raw = hit.get("classification") or usage.get("classification") or []
            cls_path = classification_list_normalized(cls_raw)
            cls_dict = classification_list_to_dict(cls_raw)
            
            # Get name/rank/status from nested usage.name or direct fields
            name_obj = usage.get("name", {})
            name = name_obj.get("scientificName") if isinstance(name_obj, dict) else None
            if not name:
                name = usage.get("label") or hit.get("label") or scientific_name
            
            result_rank = (name_obj.get("rank") if isinstance(name_obj, dict) else None) or usage.get("rank")
            result_status = usage.get("status") or hit.get("status") or "unknown"
            result_authorship = (name_obj.get("authorship") if isinstance(name_obj, dict) else None) or usage.get("authorship")
            
            return COLMatchResult(
                matched=True,
                external_id=str(ext_id),
                name=name,
                rank=result_rank,
                status=result_status,
                authorship=result_authorship,
                classification_path=cls_path,
                classification=cls_dict,
                raw={"search_result": hit},
            )
        except Exception:
            return None


# Alias for backwards compatibility
MatchResult = COLMatchResult


# ============================================================
# NCBI Datasets API
# ============================================================

import io
import logging
import os
import time
import zipfile
from threading import Semaphore

logger = logging.getLogger(__name__)

NCBI_BASE_URL = "https://api.ncbi.nlm.nih.gov/datasets/v2"
NCBI_USER_AGENT = "TaxaBridge/1.0 (Django taxonomy matching)"
NCBI_TIMEOUT = 45
NCBI_MAX_PARALLEL = 8

_ncbi_sema = Semaphore(NCBI_MAX_PARALLEL)
_ncbi_last_request = [0.0]
_ncbi_warned = [False]


def _get_ncbi_api_key() -> str:
    """Get NCBI API key from Django settings or environment."""
    try:
        from django.conf import settings
        return getattr(settings, 'NCBI_API_KEY', '') or os.environ.get("NCBI_API_KEY", "")
    except Exception:
        return os.environ.get("NCBI_API_KEY", "")


@dataclass
class GenomeMetrics:
    """Genome assembly metrics from NCBI."""
    accession: str
    organism_name: str
    taxid: int
    refseq_category: str
    genome_level: str
    genome_coverage: float
    contig_n50_kb: Optional[float]
    scaffold_n50_kb: Optional[float]
    scaffold_count: int
    quality_score: float
    raw: Dict[str, Any]


@dataclass
class NCBITaxonInfo:
    """Complete taxon information from NCBI."""
    taxid: int
    scientific_name: str
    has_genome: bool
    genomes: List[GenomeMetrics]
    best_genome: Optional[GenomeMetrics]
    proteome_status: Dict[str, bool]


class NCBIClient:
    """HTTP client for NCBI Datasets API."""

    def __init__(self, api_key: Optional[str] = None):
        self.base_url = NCBI_BASE_URL
        self.api_key = (api_key or _get_ncbi_api_key()).strip()
        self.timeout = NCBI_TIMEOUT
        self.session = self._make_session()

    def _make_session(self) -> requests.Session:
        """Create HTTP session with automatic retries."""
        session = requests.Session()

        retries = Retry(
            total=4,
            connect=3,
            read=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )

        adapter = HTTPAdapter(max_retries=retries, pool_connections=100, pool_maxsize=100)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        session.headers.update({
            "User-Agent": NCBI_USER_AGENT,
            "Accept": "application/json",
        })

        if self.api_key:
            session.headers.update({"X-API-Key": self.api_key})
            if not _ncbi_warned[0]:
                logger.info("NCBI API client initialized with API key")
                _ncbi_warned[0] = True
        else:
            if not _ncbi_warned[0]:
                logger.warning("NCBI API client without API key (limited: 3 req/s)")
                _ncbi_warned[0] = True

        return session

    def _respect_rate_limit(self):
        """Pause to respect rate limit."""
        now = time.time()
        min_interval = 0.13 if self.api_key else 0.35
        delta = now - _ncbi_last_request[0]
        if delta < min_interval:
            time.sleep(min_interval - delta)
        _ncbi_last_request[0] = time.time()

    def get(self, path: str, params: Optional[Dict] = None) -> Optional[requests.Response]:
        """GET with concurrency control."""
        url = f"{self.base_url}{path}"

        with _ncbi_sema:
            self._respect_rate_limit()
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                logger.debug(f"NCBI GET {path} -> {response.status_code}")
                return response
            except requests.exceptions.HTTPError as e:
                status = getattr(e.response, "status_code", None)
                if status == 404:
                    logger.debug(f"NCBI {path} -> 404 (not found)")
                    return None
                logger.error(f"NCBI HTTP error: {path} status={status}")
                raise
            except requests.exceptions.RequestException as e:
                logger.error(f"NCBI request error: {path} error={e}")
                raise

    def get_binary(self, path: str, params: Optional[Dict] = None) -> bytes:
        """Download binary content (ZIPs)."""
        url = f"{self.base_url}{path}"

        with _ncbi_sema:
            self._respect_rate_limit()
            try:
                headers = dict(self.session.headers)
                headers["Accept"] = "application/zip"
                resp = self.session.get(url, params=params, timeout=self.timeout, headers=headers, stream=True)
                resp.raise_for_status()

                chunks = []
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        chunks.append(chunk)
                return b"".join(chunks)
            except requests.exceptions.RequestException as e:
                logger.error(f"NCBI binary download failed: {path} error={e}")
                raise


def compute_genome_quality_score(
    refseq_cat: str,
    genome_level: str,
    coverage: float,
    scaffold_n50_kb: Optional[float],
    contig_n50_kb: Optional[float],
    scaffold_count: int,
) -> float:
    """
    Compute quality score 0-1 based on metrics.
    Weighting: RefSeq 25%, Level 25%, Coverage 20%, N50 20%, Scaffolds 10%
    """
    score = 0.0

    # RefSeq category (25%)
    refseq_upper = (refseq_cat or "").upper()
    if "REFERENCE" in refseq_upper:
        score += 0.25
    elif "REPRESENTATIVE" in refseq_upper:
        score += 0.20

    # Genome level (25%)
    level_upper = (genome_level or "").upper()
    if "COMPLETE" in level_upper:
        score += 0.25
    elif "CHROMOSOME" in level_upper:
        score += 0.20
    elif "SCAFFOLD" in level_upper:
        score += 0.10
    elif "CONTIG" in level_upper:
        score += 0.05

    # Coverage (20%)
    if coverage >= 100:
        score += 0.20
    elif coverage >= 50:
        score += 0.15
    elif coverage >= 20:
        score += 0.10
    elif coverage >= 10:
        score += 0.05

    # N50 (20%)
    n50 = scaffold_n50_kb or contig_n50_kb or 0
    if n50 >= 10000:
        score += 0.20
    elif n50 >= 1000:
        score += 0.15
    elif n50 >= 100:
        score += 0.10
    elif n50 >= 10:
        score += 0.05

    # Scaffold count (10%) - less is better
    if scaffold_count <= 100:
        score += 0.10
    elif scaffold_count <= 1000:
        score += 0.07
    elif scaffold_count <= 5000:
        score += 0.03

    return round(score, 3)


def extract_genome_metrics(report: Dict[str, Any]) -> GenomeMetrics:
    """Extract metrics from an NCBI assembly report."""
    info = report.get("assembly_info", {}) or {}
    stats = report.get("assembly_stats", {}) or {}
    org = report.get("organism", {}) or {}

    def to_kb(val):
        if val is None:
            return None
        try:
            return float(val) / 1000.0
        except (TypeError, ValueError):
            return None

    accession = report.get("current_accession") or report.get("accession") or ""
    refseq_cat = info.get("refseq_category") or ""
    genome_level = info.get("assembly_level") or ""
    coverage = float(stats.get("genome_coverage") or 0.0)
    contig_n50 = to_kb(stats.get("contig_n50"))
    scaffold_n50 = to_kb(stats.get("scaffold_n50"))
    scaffold_count = int(stats.get("number_of_scaffolds") or 0)

    score = compute_genome_quality_score(
        refseq_cat, genome_level, coverage, scaffold_n50, contig_n50, scaffold_count
    )

    return GenomeMetrics(
        accession=accession,
        organism_name=org.get("organism_name") or "",
        taxid=org.get("tax_id") or 0,
        refseq_category=refseq_cat,
        genome_level=genome_level,
        genome_coverage=coverage,
        contig_n50_kb=contig_n50,
        scaffold_n50_kb=scaffold_n50,
        scaffold_count=scaffold_count,
        quality_score=score,
        raw=report,
    )


def check_proteome(client: NCBIClient, accession: str) -> tuple[bool, str]:
    """Check if accession has valid proteome."""
    UNNAMED_KEYS = ("unnamed protein product", "hypothetical protein", "uncharacterized protein")

    path = f"/genome/accession/{accession}/download"
    params = {"include_annotation_type": "PROT_FASTA", "hydrated": "FULLY_HYDRATED"}

    try:
        blob = client.get_binary(path, params=params)
        with zipfile.ZipFile(io.BytesIO(blob), "r") as z:
            faa_files = [n for n in z.namelist() if n.endswith(".faa")]
            if not faa_files:
                return False, "no_faa"

            unnamed_count = 0
            total = 0
            for faa_name in faa_files:
                with z.open(faa_name, "r") as fh:
                    for line in io.TextIOWrapper(fh, encoding="utf-8"):
                        if line.startswith(">"):
                            total += 1
                            if any(k in line.lower() for k in UNNAMED_KEYS):
                                unnamed_count += 1
                        if total >= 1000:
                            break
                if total >= 1000:
                    break

            if total == 0:
                return False, "empty"

            ratio_unnamed = unnamed_count / total
            if ratio_unnamed > 0.5:
                logger.debug(f"Proteome {accession} discarded: {ratio_unnamed:.0%} unnamed")
                return False, "poor_annotation"

        return True, "good"

    except Exception as e:
        logger.warning(f"Error checking proteome {accession}: {e}")
        return False, "error"


def get_taxon_genomes(taxid: int, check_proteomes: bool = True) -> NCBITaxonInfo:
    """Get complete genome information for a taxid."""
    client = NCBIClient()
    taxid_str = str(taxid)
    
    # 1. Get basic taxon information
    scientific_name = ""
    try:
        r = client.get(f"/taxonomy/taxon/{taxid_str}/name_report")
        if r:
            data = r.json()
            reports = data.get("reports", [])
            if reports:
                names = reports[0].get("taxonomy", {}).get("names", [])
                for n in names:
                    if n.get("type") == "scientific name":
                        scientific_name = n.get("name", "")
                        break
    except Exception as e:
        logger.warning(f"Error getting name for taxid {taxid}: {e}")

    # 2. Get genome reports
    genomes: List[GenomeMetrics] = []
    try:
        r = client.get(f"/genome/taxon/{taxid_str}/dataset_report")
        if r:
            reports = r.json().get("reports", []) or []
            logger.debug(f"Taxid {taxid}: found {len(reports)} genome reports")
            
            # Filter only reference/representative
            filtered = []
            for rep in reports:
                info = rep.get("assembly_info", {}) or {}
                refcat = str(info.get("refseq_category", "")).upper()
                if "REFERENCE" in refcat or "REPRESENTATIVE" in refcat:
                    filtered.append(rep)
            
            if not filtered:
                filtered = reports[:10]

            for rep in filtered:
                metrics = extract_genome_metrics(rep)
                genomes.append(metrics)

    except Exception as e:
        logger.error(f"Error getting genomes for taxid {taxid}: {e}")
    
    if not genomes:
        return NCBITaxonInfo(
            taxid=taxid,
            scientific_name=scientific_name,
            has_genome=False,
            genomes=[],
            best_genome=None,
            proteome_status={},
        )

    # Sort by score
    genomes.sort(key=lambda g: g.quality_score, reverse=True)
    best_genome = genomes[0] if genomes else None

    # Check proteomes if requested
    proteome_status: Dict[str, bool] = {}
    if check_proteomes and genomes:
        for genome in genomes[:3]:
            has_prot, quality = check_proteome(client, genome.accession)
            proteome_status[genome.accession] = has_prot

    return NCBITaxonInfo(
        taxid=taxid,
        scientific_name=scientific_name,
        has_genome=True,
        genomes=genomes,
        best_genome=best_genome,
        proteome_status=proteome_status,
    )


def has_any_genome(taxid: int) -> bool:
    """Quick check if taxid has genomes."""
    client = NCBIClient()
    try:
        r = client.get(f"/genome/taxon/{taxid}/dataset_report", params={"page_size": 1})
        if r and r.status_code == 200:
            reports = r.json().get("reports", [])
            return len(reports) > 0
    except Exception:
        pass
    return False


# ============================================================
# NCBI Taxonomy EUtils API (name resolution)
# ============================================================
import xml.etree.ElementTree as ET

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


@dataclass(frozen=True)
class NcbiTaxonRecord:
    """Record from NCBI Taxonomy database."""
    taxid: int
    scientific_name: str
    rank: str
    parent_taxid: Optional[int]
    lineage: Dict[str, str]
    raw: Dict


def _eutils_text(node) -> str:
    """Extract text from XML node."""
    if node is None or node.text is None:
        return ""
    return node.text.strip()


class NcbiTaxonomyClient:
    """
    Minimal client to resolve scientific names to taxid (NCBI Taxonomy EUtils).
    Conservative: 1) esearch by Scientific Name 2) efetch of the first taxid.
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
        """Search for taxid by scientific name."""
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
        """Fetch complete taxon record by taxid."""
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

        sci = _eutils_text(taxon.find("ScientificName"))
        rank = _eutils_text(taxon.find("Rank"))
        parent = _eutils_text(taxon.find("ParentTaxId"))
        parent_taxid = int(parent) if parent.isdigit() else None

        lineage: Dict[str, str] = {}
        for t in taxon.findall(".//LineageEx/Taxon"):
            rnk = _eutils_text(t.find("Rank")).lower()
            nm = _eutils_text(t.find("ScientificName"))
            if rnk and nm:
                lineage[rnk] = nm

        # Include the taxon itself as the last entry
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
    Resolve scientific name to NCBI taxon record.
    Helper function compatible with management commands.
    """
    client = NcbiTaxonomyClient(api_key=api_key, sleep_s=sleep_s, timeout=timeout)
    taxid = client.esearch_taxid(name)
    if taxid is None:
        return None
    return client.efetch_taxon(taxid)
