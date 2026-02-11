# apps/taxonomy/services/ncbi_sync.py
"""
Unified NCBI Genome Synchronization Service.

This module centralizes ALL NCBI sync logic:
- Constants (KINGDOMS, QUALITY_CRITERIA)
- Genome fetching from NCBI Datasets API
- Quality filtering
- Database operations (Taxon, NCBIGenome)
- COL matching integration

Usage:
    from apps.taxonomy.services.ncbi_sync import NCBISyncService
    
    service = NCBISyncService(kingdom="metazoa")
    for result in service.sync_genomes(limit=100):
        print(result)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Callable

import requests
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


# ============================================================
# Constants - Single Source of Truth
# ============================================================

NCBI_API_BASE = "https://api.ncbi.nlm.nih.gov/datasets/v2"
COL_DATASET = "3LR"

# Kingdom taxids
KINGDOMS: Dict[str, int] = {
    "metazoa": 33208,
    "animalia": 33208,  # Alias
    "fungi": 4751,
    "viridiplantae": 33090,
    "plantae": 33090,  # Alias
    "bacteria": 2,
    "archaea": 2157,
    "protista": 2759,
}

# Quality criteria per kingdom
QUALITY_CRITERIA: Dict[str, Dict[str, float]] = {
    "metazoa": {"min_coverage": 30, "min_scaffold_n50_kb": 1000, "min_protein_coding": 1000},
    "fungi": {"min_coverage": 30, "min_scaffold_n50_kb": 500, "min_protein_coding": 500},
    "viridiplantae": {"min_coverage": 20, "min_scaffold_n50_kb": 500, "min_protein_coding": 1000},
    "bacteria": {"min_coverage": 20, "min_scaffold_n50_kb": 50, "min_protein_coding": 100},
    "archaea": {"min_coverage": 20, "min_scaffold_n50_kb": 50, "min_protein_coding": 100},
    "default": {"min_coverage": 10, "min_scaffold_n50_kb": 100, "min_protein_coding": 100},
}


# ============================================================
# Data Classes
# ============================================================

@dataclass
class SyncProgress:
    """Progress tracking for sync operations."""
    total_scanned: int = 0
    total_filtered: int = 0
    total_skipped: int = 0  # Already in database
    total_fetched: int = 0
    taxa_created: int = 0
    taxa_updated: int = 0
    genomes_created: int = 0
    genomes_updated: int = 0
    col_matched: int = 0
    col_unmatched: int = 0
    errors: List[str] = field(default_factory=list)
    
    @property
    def summary(self) -> Dict[str, Any]:
        return {
            "scanned": self.total_scanned,
            "filtered": self.total_filtered,
            "skipped": self.total_skipped,
            "fetched": self.total_fetched,
            "taxa_created": self.taxa_created,
            "taxa_updated": self.taxa_updated,
            "genomes_created": self.genomes_created,
            "genomes_updated": self.genomes_updated,
            "col_matched": self.col_matched,
            "col_unmatched": self.col_unmatched,
            "errors": len(self.errors),
        }


@dataclass
class GenomeData:
    """Parsed genome data from NCBI API."""
    accession: str
    taxid: int
    scientific_name: str
    organism_name: str
    common_name: str
    rank: str
    refseq_category: str
    genome_level: str
    genome_coverage: Optional[float]
    contig_n50_kb: Optional[float]
    scaffold_n50_kb: Optional[float]
    scaffold_count: Optional[int]
    genes: Optional[int]
    protein_coding: Optional[int]
    phylum: str
    class_name: str
    directory_name: str
    quality_score: float
    raw: Dict[str, Any]
    
    # Extended genome data
    total_sequence_length: Optional[int] = None
    gc_percent: Optional[float] = None
    chromosome_count: Optional[int] = None
    contig_count: Optional[int] = None
    sequencing_tech: str = ""
    assembly_method: str = ""
    release_date: str = ""
    source_database: str = ""  # refseq or genbank
    
    # Extended annotation data
    annotation_provider: str = ""
    annotation_status: str = ""
    non_coding_genes: Optional[int] = None
    pseudogenes: Optional[int] = None
    
    # BUSCO completeness
    busco_complete: Optional[float] = None
    busco_single_copy: Optional[float] = None
    busco_duplicated: Optional[float] = None
    busco_fragmented: Optional[float] = None
    busco_missing: Optional[float] = None
    busco_lineage: str = ""
    
    # Strain/isolate info
    strain: str = ""
    ecotype: str = ""
    
    @classmethod
    def from_ncbi_report(cls, report: Dict[str, Any], taxonomy: Dict[str, str] = None) -> "GenomeData":
        """Parse NCBI API genome report into GenomeData."""
        taxonomy = taxonomy or {}
        
        org = report.get("organism", {}) or {}
        info = report.get("assembly_info", {}) or {}
        stats = report.get("assembly_stats", {}) or {}
        ann = report.get("annotation_info", {}) or {}
        gene_counts = (ann.get("stats", {}) or {}).get("gene_counts", {}) or {}
        busco = ann.get("busco", {}) or {}
        infraspecific = org.get("infraspecific_names", {}) or {}
        
        # Extract metrics
        coverage = _safe_float(stats.get("genome_coverage"))
        contig_n50 = _safe_float(stats.get("contig_n50"))
        scaffold_n50 = _safe_float(stats.get("scaffold_n50"))
        scaffold_count = _safe_int(stats.get("number_of_scaffolds"))
        
        # Convert to kb
        contig_n50_kb = contig_n50 / 1000 if contig_n50 else None
        scaffold_n50_kb = scaffold_n50 / 1000 if scaffold_n50 else None
        
        # Calculate quality score
        refseq_cat = info.get("refseq_category", "")
        genome_level = info.get("assembly_level", "")
        quality_score = compute_quality_score(
            refseq_cat, genome_level, coverage or 0,
            scaffold_n50_kb, contig_n50_kb, scaffold_count or 0
        )
        
        # Source database
        source_db = report.get("source_database", "")
        if "REFSEQ" in source_db.upper():
            source_database = "refseq"
        elif "GENBANK" in source_db.upper():
            source_database = "genbank"
        else:
            source_database = source_db.lower() if source_db else ""
        
        return cls(
            accession=report.get("accession", ""),
            taxid=org.get("tax_id", 0),
            scientific_name=org.get("organism_name", ""),  # NCBI uses organism_name, not sci_name
            organism_name=org.get("organism_name", ""),
            common_name=org.get("common_name", ""),
            rank=org.get("rank", "species"),
            refseq_category=refseq_cat,
            genome_level=genome_level,
            genome_coverage=coverage,
            contig_n50_kb=contig_n50_kb,
            scaffold_n50_kb=scaffold_n50_kb,
            scaffold_count=scaffold_count,
            genes=_safe_int(gene_counts.get("total")),
            protein_coding=_safe_int(gene_counts.get("protein_coding")),
            phylum=taxonomy.get("phylum", ""),
            class_name=taxonomy.get("class", ""),
            directory_name=info.get("assembly_name", ""),
            quality_score=quality_score,
            raw=report,
            # Extended genome data
            total_sequence_length=_safe_int(stats.get("total_sequence_length")),
            gc_percent=_safe_float(stats.get("gc_percent")),
            chromosome_count=_safe_int(stats.get("total_number_of_chromosomes")),
            contig_count=_safe_int(stats.get("number_of_contigs")),
            sequencing_tech=info.get("sequencing_tech", ""),
            assembly_method=info.get("assembly_method", ""),
            release_date=info.get("release_date", ""),
            source_database=source_database,
            # Extended annotation data
            annotation_provider=ann.get("provider", ""),
            annotation_status=ann.get("status", ""),
            non_coding_genes=_safe_int(gene_counts.get("non_coding")),
            pseudogenes=_safe_int(gene_counts.get("pseudogene")),
            # BUSCO
            busco_complete=_safe_float(busco.get("complete")),
            busco_single_copy=_safe_float(busco.get("single_copy")),
            busco_duplicated=_safe_float(busco.get("duplicated")),
            busco_fragmented=_safe_float(busco.get("fragmented")),
            busco_missing=_safe_float(busco.get("missing")),
            busco_lineage=busco.get("busco_lineage", ""),
            # Strain info
            strain=infraspecific.get("strain", ""),
            ecotype=infraspecific.get("ecotype", ""),
        )


# ============================================================
# Helper Functions
# ============================================================

def _safe_float(val, default: float = None) -> Optional[float]:
    """Safely convert to float."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val, default: int = None) -> Optional[int]:
    """Safely convert to int."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def compute_quality_score(
    refseq_cat: str,
    genome_level: str,
    coverage: float,
    scaffold_n50_kb: Optional[float],
    contig_n50_kb: Optional[float],
    scaffold_count: int,
) -> float:
    """
    Compute quality score 0-1 based on multiple metrics.
    
    Weights:
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

    # N50 (20%) - prefer scaffold, fallback to contig
    n50 = scaffold_n50_kb or contig_n50_kb or 0
    if n50 >= 10000:  # 10 Mb
        score += 0.20
    elif n50 >= 1000:  # 1 Mb
        score += 0.15
    elif n50 >= 100:  # 100 kb
        score += 0.10
    elif n50 >= 10:  # 10 kb
        score += 0.05

    # Scaffold count (10%) - fewer is better
    if scaffold_count <= 100:
        score += 0.10
    elif scaffold_count <= 1000:
        score += 0.07
    elif scaffold_count <= 5000:
        score += 0.03

    return round(score, 3)


def get_kingdom_taxid(kingdom: str) -> int:
    """Get taxid for a kingdom name."""
    kingdom_lower = kingdom.lower()
    if kingdom_lower in KINGDOMS:
        return KINGDOMS[kingdom_lower]
    # Try as direct taxid
    try:
        return int(kingdom)
    except (ValueError, TypeError):
        raise ValueError(f"Unknown kingdom: {kingdom}. Available: {list(KINGDOMS.keys())}")


def get_quality_criteria(kingdom: str) -> Dict[str, float]:
    """Get quality criteria for a kingdom."""
    kingdom_lower = kingdom.lower()
    # Normalize aliases
    if kingdom_lower in ("animalia",):
        kingdom_lower = "metazoa"
    elif kingdom_lower in ("plantae",):
        kingdom_lower = "viridiplantae"
    return QUALITY_CRITERIA.get(kingdom_lower, QUALITY_CRITERIA["default"])


# ============================================================
# Filters
# ============================================================

class GenomeFilters:
    """Collection of filter functions for genome data."""
    
    @staticmethod
    def passes_refseq(data: Dict[str, Any]) -> bool:
        """Check if genome is RefSeq reference or representative."""
        info = data.get("assembly_info", {}) or {}
        refcat = (info.get("refseq_category") or "").upper()
        return "REFERENCE" in refcat or "REPRESENTATIVE" in refcat
    
    @staticmethod
    def passes_level(data: Dict[str, Any], allowed: List[str] = None) -> bool:
        """Check if genome level is acceptable."""
        if allowed is None:
            allowed = ["complete", "chromosome", "scaffold"]
        info = data.get("assembly_info", {}) or {}
        level = (info.get("assembly_level") or "").lower()
        return any(k in level for k in allowed)
    
    @staticmethod
    def passes_quality(data: Dict[str, Any], criteria: Dict[str, float]) -> bool:
        """Check if genome meets quality criteria."""
        stats = data.get("assembly_stats", {}) or {}
        info = data.get("assembly_info", {}) or {}
        level = (info.get("assembly_level") or "").lower()
        
        coverage = _safe_float(stats.get("genome_coverage"), 0.0)
        scaffold_n50 = _safe_float(stats.get("scaffold_n50"), 0.0)
        scaffold_n50_kb = scaffold_n50 / 1000.0 if scaffold_n50 else 0.0
        
        # Complete genomes get automatic pass for coverage
        if coverage == 0 and "complete" in level:
            coverage = 100.0
        
        min_coverage = criteria.get("min_coverage", 10)
        min_n50 = criteria.get("min_scaffold_n50_kb", 100)
        
        return coverage >= min_coverage or scaffold_n50_kb >= min_n50
    
    @staticmethod
    def passes_annotation(data: Dict[str, Any], min_proteins: int = 1000) -> bool:
        """Check if genome has sufficient annotation."""
        ann = data.get("annotation_info", {}) or {}
        gene_counts = (ann.get("stats", {}) or {}).get("gene_counts", {}) or {}
        protein_coding = _safe_int(gene_counts.get("protein_coding"), 0)
        return protein_coding >= min_proteins


# ============================================================
# NCBI API Functions
# ============================================================

@dataclass
class NCBIApiFilters:
    """Filters for NCBI Datasets API."""
    reference_only: bool = True  # Reference + Representative genomes
    refseq_only: bool = True     # Only RefSeq (GCF_), not GenBank (GCA_)
    annotated_only: bool = True  # Only with annotation
    exclude_contigs: bool = True # Exclude contig-level assemblies


def fetch_ncbi_genomes(
    taxid: int,
    page_size: int = 100,
    max_pages: int = 0,
    filters: NCBIApiFilters = None,
) -> Iterator[Dict[str, Any]]:
    """
    Fetch genomes from NCBI Datasets API.
    
    Args:
        taxid: NCBI taxonomy ID
        page_size: Results per page (max 1000)
        max_pages: Maximum pages to fetch (0 = unlimited)
        filters: API filters (reference_only, refseq_only, annotated_only, exclude_contigs)
    
    Yields:
        Raw genome report dicts from NCBI API
    """
    if filters is None:
        filters = NCBIApiFilters()
    
    url = f"{NCBI_API_BASE}/genome/taxon/{taxid}/dataset_report"
    page_token = None
    page_count = 0
    
    session = requests.Session()
    session.headers.update({
        "User-Agent": "TaxaBridge/2.0 (Django taxonomy sync)",
        "Accept": "application/json",
    })
    
    while True:
        params = {"page_size": min(page_size, 1000)}
        if page_token:
            params["page_token"] = page_token
        
        # Apply API-level filters
        if filters.reference_only:
            params["filters.reference_only"] = "true"
        if filters.refseq_only:
            params["filters.assembly_source"] = "refseq"
        if filters.annotated_only:
            params["filters.has_annotation"] = "true"
        
        try:
            time.sleep(0.35)  # Rate limit
            resp = session.get(url, params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error(f"NCBI API error: {e}")
            break
        
        reports = data.get("reports", [])
        if not reports:
            break
        
        for report in reports:
            # Post-filter: exclude contigs (API doesn't support this filter directly)
            if filters.exclude_contigs:
                level = (report.get("assembly_info", {}).get("assembly_level") or "").lower()
                if level == "contig":
                    continue
            yield report
        
        page_count += 1
        if max_pages and page_count >= max_pages:
            break
        
        page_token = data.get("next_page_token")
        if not page_token:
            break


def fetch_taxonomy(taxid: int, cache: Dict[int, Dict] = None) -> Dict[str, str]:
    """
    Fetch taxonomy hierarchy from NCBI.
    
    Args:
        taxid: NCBI taxonomy ID
        cache: Optional cache dict to avoid repeated calls
    
    Returns:
        Dict with rank->name mappings (phylum, class, order, family, genus)
    """
    if cache is not None and taxid in cache:
        return cache[taxid]
    
    url = f"{NCBI_API_BASE}/taxonomy/taxon/{taxid}"
    result: Dict[str, str] = {}
    
    try:
        time.sleep(0.35)
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            return result
        
        data = resp.json()
        
        rank_map = {
            "PHYLUM": "phylum",
            "CLASS": "class",
            "ORDER": "order",
            "FAMILY": "family",
            "GENUS": "genus",
        }
        
        for node in data.get("taxonomy_nodes", []):
            tax = node.get("taxonomy", {})
            rank = tax.get("rank", "")
            name = tax.get("organism_name", "")
            if rank in rank_map:
                result[rank_map[rank]] = name
        
        if cache is not None:
            cache[taxid] = result
            
    except Exception as e:
        logger.warning(f"Taxonomy fetch error for {taxid}: {e}")
    
    return result


# ============================================================
# Database Operations
# ============================================================

def save_genome_to_db(genome: GenomeData, sync_run=None) -> tuple:
    """
    Save genome data to database.
    
    Args:
        genome: GenomeData instance
        sync_run: Optional TaxonSyncRun for tracking
    
    Returns:
        Tuple of (taxon_created, genome_created)
    """
    from apps.taxonomy.models import NCBIGenome, Taxon
    
    if not genome.taxid or not genome.accession:
        return False, False
    
    taxon_created = False
    genome_created = False
    
    with transaction.atomic():
        # Create/update Taxon
        taxon, taxon_created = Taxon.objects.update_or_create(
            taxid=genome.taxid,
            defaults={
                "scientific_name": genome.scientific_name or genome.organism_name,
                "rank": genome.rank or "species",
            },
        )
        
        # Prepare genome defaults with only valid fields
        genome_defaults = {
            "taxon": taxon,
            "organism_name": genome.organism_name,
            "common_name": genome.common_name,
            "refseq_category": genome.refseq_category,
            "genome_level": genome.genome_level,
            "genome_coverage": genome.genome_coverage,
            "contig_n50_kb": genome.contig_n50_kb,
            "scaffold_n50_kb": genome.scaffold_n50_kb,
            "scaffold_count": genome.scaffold_count,
            "genes": genome.genes,
            "protein_coding": genome.protein_coding,
            "phylum": genome.phylum,
            "class_name": genome.class_name,
            "directory_name": genome.directory_name,
            "quality_score": genome.quality_score,
            "raw": genome.raw,
            # Extended genome data
            "total_sequence_length": genome.total_sequence_length,
            "gc_percent": genome.gc_percent,
            "chromosome_count": genome.chromosome_count,
            "contig_count": genome.contig_count,
            "sequencing_tech": genome.sequencing_tech,
            "assembly_method": genome.assembly_method,
            "release_date": genome.release_date,
            "source_database": genome.source_database,
            # Extended annotation data
            "annotation_provider": genome.annotation_provider,
            "annotation_status": genome.annotation_status,
            "non_coding_genes": genome.non_coding_genes,
            "pseudogenes": genome.pseudogenes,
            # BUSCO
            "busco_complete": genome.busco_complete,
            "busco_single_copy": genome.busco_single_copy,
            "busco_duplicated": genome.busco_duplicated,
            "busco_fragmented": genome.busco_fragmented,
            "busco_missing": genome.busco_missing,
            "busco_lineage": genome.busco_lineage,
            # Strain info
            "strain": genome.strain,
            "ecotype": genome.ecotype,
        }
        
        # Filter to valid fields only
        valid_fields = {f.name for f in NCBIGenome._meta.get_fields()}
        genome_defaults = {k: v for k, v in genome_defaults.items() if k in valid_fields and v is not None}
        
        # Create/update NCBIGenome
        _, genome_created = NCBIGenome.objects.update_or_create(
            accession=genome.accession,
            defaults=genome_defaults,
        )
    
    return taxon_created, genome_created


# ============================================================
# Main Sync Service
# ============================================================

class NCBISyncService:
    """
    Unified service for NCBI genome synchronization.
    
    Handles:
    - Fetching genomes from NCBI API
    - Filtering by quality criteria
    - Saving to database
    - Progress tracking
    
    Usage:
        service = NCBISyncService(kingdom="metazoa")
        progress = service.sync_genomes(limit=100)
        print(progress.summary)
    """
    
    def __init__(
        self,
        kingdom: str = "metazoa",
        taxid: int = None,
        skip_quality: bool = False,
        skip_refseq: bool = False,
        skip_annotation: bool = False,  # Changed default - now uses API filter
        custom_criteria: Dict[str, float] = None,
        api_filters: NCBIApiFilters = None,
    ):
        """
        Initialize sync service.
        
        Args:
            kingdom: Kingdom name (metazoa, fungi, etc.) or alias
            taxid: Override taxid (use instead of kingdom lookup)
            skip_quality: Skip quality filtering
            skip_refseq: Skip RefSeq filtering (deprecated, use api_filters)
            skip_annotation: Skip annotation filtering (deprecated, use api_filters)
            custom_criteria: Override quality criteria
            api_filters: API-level filters (NCBIApiFilters)
        """
        self.kingdom = kingdom.lower()
        self.taxid = taxid or get_kingdom_taxid(self.kingdom)
        self.skip_quality = skip_quality
        self.skip_refseq = skip_refseq
        self.skip_annotation = skip_annotation
        self.criteria = custom_criteria or get_quality_criteria(self.kingdom)
        self.taxonomy_cache: Dict[int, Dict] = {}
        self.progress = SyncProgress()
        self._cancelled = False
        
        # API-level filters (more efficient - filters at source)
        if api_filters is None:
            # Default: Reference genomes + RefSeq + Annotated + no contigs
            self.api_filters = NCBIApiFilters(
                reference_only=not skip_refseq,
                refseq_only=not skip_refseq,
                annotated_only=not skip_annotation,
                exclude_contigs=True,
            )
        else:
            self.api_filters = api_filters
    
    def cancel(self):
        """Request cancellation of running sync."""
        self._cancelled = True
    
    def sync_genomes(
        self,
        limit: int = 0,
        page_size: int = 100,
        on_progress: Callable[[SyncProgress], None] = None,
        sync_run = None,
        skip_existing: bool = True,
    ) -> SyncProgress:
        """
        Synchronize genomes from NCBI to database.
        
        Args:
            limit: Maximum genomes to process (0 = unlimited)
            page_size: NCBI API page size
            on_progress: Callback for progress updates
            sync_run: Optional TaxonSyncRun model for tracking
            skip_existing: Skip genomes already in database (default True)
        
        Returns:
            SyncProgress with final statistics
        """
        from apps.taxonomy.models import NCBIGenome
        
        logger.info(f"Starting NCBI sync for {self.kingdom} (taxid={self.taxid})")
        logger.info(f"API filters: reference_only={self.api_filters.reference_only}, "
                    f"refseq_only={self.api_filters.refseq_only}, "
                    f"annotated_only={self.api_filters.annotated_only}")
        
        # Load existing accessions to skip
        existing_accessions: set = set()
        if skip_existing:
            existing_accessions = set(
                NCBIGenome.objects.values_list("accession", flat=True)
            )
            logger.info(f"Found {len(existing_accessions)} existing genomes in database")
        
        fetched = 0
        for report in fetch_ncbi_genomes(self.taxid, page_size=page_size, filters=self.api_filters):
            if self._cancelled:
                logger.info("Sync cancelled")
                break
            
            self.progress.total_scanned += 1
            
            # Skip if already in database
            accession = report.get("accession", "")
            if skip_existing and accession in existing_accessions:
                self.progress.total_skipped += 1
                continue
            
            # Apply post-API filters (quality criteria)
            # Note: Most filtering is now done at API level for efficiency
            if not self.skip_quality and not GenomeFilters.passes_quality(report, self.criteria):
                self.progress.total_filtered += 1
                continue
            
            # Parse and enrich with taxonomy
            org = report.get("organism", {}) or {}
            org_taxid = org.get("tax_id")
            taxonomy = fetch_taxonomy(org_taxid, self.taxonomy_cache) if org_taxid else {}
            
            genome = GenomeData.from_ncbi_report(report, taxonomy)
            
            # Save to database
            try:
                tax_created, gen_created = save_genome_to_db(genome, sync_run)
                
                if tax_created:
                    self.progress.taxa_created += 1
                else:
                    self.progress.taxa_updated += 1
                
                if gen_created:
                    self.progress.genomes_created += 1
                else:
                    self.progress.genomes_updated += 1
                
                self.progress.total_fetched += 1
                fetched += 1
                
                # Add to existing set so we don't re-process in same run
                existing_accessions.add(accession)
                
            except Exception as e:
                self.progress.errors.append(f"{genome.accession}: {str(e)}")
                logger.error(f"Error saving genome {genome.accession}: {e}")
            
            # Progress callback
            if on_progress and fetched % 50 == 0:
                on_progress(self.progress)
            
            # Check limit
            if limit and fetched >= limit:
                break
        
        logger.info(f"Sync complete: {self.progress.summary}")
        return self.progress
    
    def sync_genomes_iter(
        self,
        limit: int = 0,
        page_size: int = 100,
    ) -> Iterator[GenomeData]:
        """
        Iterate over genomes without saving to database.
        
        Useful for dry-run or custom processing.
        
        Args:
            limit: Maximum genomes to yield (0 = unlimited)
            page_size: NCBI API page size
        
        Yields:
            GenomeData instances
        """
        count = 0
        for report in fetch_ncbi_genomes(self.taxid, page_size=page_size, filters=self.api_filters):
            if self._cancelled:
                break
            
            self.progress.total_scanned += 1
            
            # Apply post-API filters (quality criteria)
            if not self.skip_quality and not GenomeFilters.passes_quality(report, self.criteria):
                self.progress.total_filtered += 1
                continue
            
            # Parse
            org = report.get("organism", {}) or {}
            org_taxid = org.get("tax_id")
            taxonomy = fetch_taxonomy(org_taxid, self.taxonomy_cache) if org_taxid else {}
            
            genome = GenomeData.from_ncbi_report(report, taxonomy)
            yield genome
            
            count += 1
            if limit and count >= limit:
                break
