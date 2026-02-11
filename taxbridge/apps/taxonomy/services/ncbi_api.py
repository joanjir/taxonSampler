# apps/taxonomy/services/ncbi_api.py
"""
NCBI API client for Django TaxaBridge.
Adapted from traerNCBI/ for integration with COL matching system.
Fetches genome information, metrics and proteomes from NCBI Datasets API.
"""
from __future__ import annotations

import io
import logging
import os
import time
import zipfile
from dataclasses import dataclass
from threading import Semaphore
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# ===================== CONFIGURATION =====================

NCBI_BASE_URL = "https://api.ncbi.nlm.nih.gov/datasets/v2"
USER_AGENT = "TaxaBridge/1.0 (Django taxonomy matching)"
NET_TIMEOUT = 45
MAX_PARALLEL_CALLS = 8

def _get_api_key() -> str:
    """Get NCBI API key from Django settings or environment."""
    try:
        from django.conf import settings
        return getattr(settings, 'NCBI_API_KEY', '') or os.environ.get("NCBI_API_KEY", "")
    except Exception:
        return os.environ.get("NCBI_API_KEY", "")

# Semaphore to limit concurrency
_sema = Semaphore(MAX_PARALLEL_CALLS)
_last_request = [0.0]
_client_warned = [False]  # Track if we've already warned about missing API key


# ===================== DATACLASSES =====================

@dataclass
class GenomeMetrics:
    """Genome assembly metrics."""
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
    proteome_status: Dict[str, bool]  # accession -> has_valid_proteome


# ===================== HTTP CLIENT =====================

class NCBIClient:
    """Cliente HTTP para NCBI Datasets API."""

    def __init__(self, api_key: Optional[str] = None):
        self.base_url = NCBI_BASE_URL
        self.api_key = (api_key or _get_api_key()).strip()
        self.timeout = NET_TIMEOUT
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
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })

        if self.api_key:
            session.headers.update({"X-API-Key": self.api_key})
            if not _client_warned[0]:
                logger.info("NCBI API client initialized with API key")
                _client_warned[0] = True
        else:
            if not _client_warned[0]:
                logger.warning("NCBI API client without API key (limited mode: 3 req/s)")
                _client_warned[0] = True

        return session

    def _respect_rate_limit(self):
        """Pause to respect rate limit."""
        now = time.time()
        min_interval = 0.13 if self.api_key else 0.35
        delta = now - _last_request[0]
        if delta < min_interval:
            time.sleep(min_interval - delta)
        _last_request[0] = time.time()

    def _get(self, path: str, params: Optional[Dict] = None) -> Optional[requests.Response]:
        """GET con control de concurrencia."""
        url = f"{self.base_url}{path}"

        with _sema:
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

    def _get_binary(self, path: str, params: Optional[Dict] = None) -> bytes:
        """Download binary content (ZIPs)."""
        url = f"{self.base_url}{path}"

        with _sema:
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


# ===================== GENOMAS =====================

def _extract_metrics(report: Dict[str, Any]) -> GenomeMetrics:
    """Extract metrics from an assembly report."""
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

    score = _compute_quality_score(refseq_cat, genome_level, coverage, scaffold_n50, contig_n50, scaffold_count)

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


def _compute_quality_score(
    refseq_cat: str,
    genome_level: str,
    coverage: float,
    scaffold_n50_kb: Optional[float],
    contig_n50_kb: Optional[float],
    scaffold_count: int,
) -> float:
    """
    Calcula un score de calidad 0-1 basado en múltiples métricas.
    Ponderación:
    - RefSeq category: 25%
    - Genome level: 25%
    - Coverage: 20%
    - N50: 20%
    - Scaffold count: 10%
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

    # N50 (20%) - usa scaffold si disponible, sino contig
    n50 = scaffold_n50_kb or contig_n50_kb or 0
    if n50 >= 10000:  # 10 Mb
        score += 0.20
    elif n50 >= 1000:  # 1 Mb
        score += 0.15
    elif n50 >= 100:  # 100 kb
        score += 0.10
    elif n50 >= 10:  # 10 kb
        score += 0.05

    # Scaffold count (10%) - menos es mejor
    if scaffold_count <= 100:
        score += 0.10
    elif scaffold_count <= 1000:
        score += 0.07
    elif scaffold_count <= 5000:
        score += 0.03

    return round(score, 3)


# ===================== PROTEOMA =====================

def _check_proteome(client: NCBIClient, accession: str) -> Tuple[bool, str]:
    """
    Verifica si el accession tiene proteoma válido.
    Returns: (has_proteome, quality)
    """
    UNNAMED_KEYS = ("unnamed protein product", "hypothetical protein", "uncharacterized protein")

    path = f"/genome/accession/{accession}/download"
    params = {"include_annotation_type": "PROT_FASTA", "hydrated": "FULLY_HYDRATED"}

    try:
        blob = client._get_binary(path, params=params)
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
                logger.debug(f"Proteoma {accession} descartado: {ratio_unnamed:.0%} sin nombre")
                return False, "poor_annotation"

        return True, "good"

    except Exception as e:
        logger.warning(f"Error checking proteome {accession}: {e}")
        return False, "error"


# ===================== MAIN API =====================

def get_taxon_genomes(taxid: int, check_proteomes: bool = True) -> NCBITaxonInfo:
    """
    Get complete genome information for a taxid.
    
    Args:
        taxid: NCBI Taxonomy ID
        check_proteomes: Whether to check proteomes (slower but complete)
    
    Returns:
        NCBITaxonInfo with all taxon data
    """
    client = NCBIClient()
    taxid_str = str(taxid)
    
    # 1. Get basic taxon information
    scientific_name = ""
    try:
        r = client._get(f"/taxonomy/taxon/{taxid_str}/name_report")
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

    # 2. Get genome reports directly (the /summary endpoint doesn't exist in v2)
    genomes: List[GenomeMetrics] = []
    try:
        r = client._get(f"/genome/taxon/{taxid_str}/dataset_report")
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
            
            # If no reference/representative, use all
            if not filtered:
                filtered = reports[:10]  # Limit to 10

            for rep in filtered:
                metrics = _extract_metrics(rep)
                genomes.append(metrics)

    except Exception as e:
        logger.error(f"Error getting genomes for taxid {taxid}: {e}")
    
    # 3. If no genomes found, return early
    if not genomes:
        return NCBITaxonInfo(
            taxid=taxid,
            scientific_name=scientific_name,
            has_genome=False,
            genomes=[],
            best_genome=None,
            proteome_status={},
        )

    # 4. Sort by score and select the best
    genomes.sort(key=lambda g: g.quality_score, reverse=True)
    best_genome = genomes[0] if genomes else None

    # 5. Check proteomes if requested
    proteome_status: Dict[str, bool] = {}
    if check_proteomes and genomes:
        # Only check top 3 to avoid overloading
        for genome in genomes[:3]:
            has_prot, quality = _check_proteome(client, genome.accession)
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
    """
    Quick check if a taxid has genomes (without downloading details).
    Uses dataset_report with limit=1 for efficiency.
    """
    client = NCBIClient()
    try:
        r = client._get(f"/genome/taxon/{taxid}/dataset_report", params={"page_size": 1})
        if r and r.status_code == 200:
            reports = r.json().get("reports", [])
            return len(reports) > 0
    except Exception:
        pass
    return False


def fetch_and_save_genomes(taxon, check_proteomes: bool = True) -> int:
    """
    Fetch genomes from NCBI and save them to the database.
    
    Args:
        taxon: Taxon instance (NCBI)
        check_proteomes: Check proteomes
    
    Returns:
        Number of genomes saved
    """
    from apps.taxonomy.models import NCBIGenome
    
    info = get_taxon_genomes(taxon.taxid, check_proteomes=check_proteomes)
    
    if not info.has_genome or not info.genomes:
        logger.info(f"Taxid {taxon.taxid} has no available genomes")
        return 0

    saved = 0
    for i, genome in enumerate(info.genomes):
        is_best = (i == 0)  # El primero es el de mayor score
        has_prot = info.proteome_status.get(genome.accession, False)
        prot_quality = "good" if has_prot else "unknown"

        try:
            obj, created = NCBIGenome.objects.update_or_create(
                accession=genome.accession,
                defaults={
                    "taxon": taxon,
                    "organism_name": genome.organism_name,
                    "refseq_category": genome.refseq_category,
                    "genome_level": genome.genome_level,
                    "genome_coverage": genome.genome_coverage,
                    "contig_n50_kb": genome.contig_n50_kb,
                    "scaffold_n50_kb": genome.scaffold_n50_kb,
                    "scaffold_count": genome.scaffold_count,
                    "quality_score": genome.quality_score,
                    "has_proteome": has_prot,
                    "proteome_quality": prot_quality,
                    "is_best_for_taxon": is_best,
                    "raw": genome.raw,
                },
            )
            saved += 1
            action = "created" if created else "updated"
            logger.debug(f"NCBIGenome {genome.accession} {action}")
        except Exception as e:
            logger.error(f"Error saving genome {genome.accession}: {e}")

    # Unmark other genomes from the same taxon as "best"
    if saved > 0:
        best_acc = info.genomes[0].accession
        NCBIGenome.objects.filter(taxon=taxon).exclude(accession=best_acc).update(is_best_for_taxon=False)

    return saved
