# apps/taxonomy/sampling/assembly_engine.py
"""
Assembly Filtering Engine (Step 3).

Post-sampling filter that refines species selection based on
genome assembly quality metrics. Two modes:

  1. Hard Filtering: strict thresholds (coverage ≥ X, N50 ≥ Y, etc.)
  2. Scoring System: weighted composite score → pick best assembly per species.

Input:  list of species dicts from Step 2 (with accession, organism_name, etc.)
Output: filtered/scored list with assembly metadata attached.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Filterable genome fields and their DB columns ─────────────────

# Assembly Info (categorical/date)
ASSEMBLY_INFO_FIELDS = {
    "genome_level":     {"label": "Assembly Level",     "type": "choice",
                         "choices": ["Complete Genome", "Chromosome", "Scaffold", "Contig"]},
    "refseq_category":  {"label": "RefSeq Category",    "type": "choice",
                         "choices": ["reference genome", "representative genome", "na"]},
    "source_database":  {"label": "Source",              "type": "choice",
                         "choices": ["refseq", "genbank"]},
    "release_date":     {"label": "Release Date",        "type": "date"},
}

# Quality Metrics (numeric)
QUALITY_METRIC_FIELDS = {
    "quality_score":    {"label": "Quality Score",    "type": "numeric", "unit": "",     "range": [0, 1]},
    "genome_coverage":  {"label": "Coverage",         "type": "numeric", "unit": "×",    "range": [0, 500]},
    "contig_n50_kb":    {"label": "Contig N50",       "type": "numeric", "unit": "kb",   "range": [0, 500_000]},
    "scaffold_n50_kb":  {"label": "Scaffold N50",     "type": "numeric", "unit": "kb",   "range": [0, 500_000]},
}

# Genome Statistics (numeric)
GENOME_STAT_FIELDS = {
    "total_sequence_length": {"label": "Genome Size",    "type": "numeric", "unit": "bp",  "range": [0, 40_000_000_000]},
    "gc_percent":            {"label": "GC Content",     "type": "numeric", "unit": "%",   "range": [0, 100]},
    "chromosome_count":      {"label": "Chromosomes",    "type": "numeric", "unit": "",    "range": [0, 200]},
    "scaffold_count":        {"label": "Scaffolds",      "type": "numeric", "unit": "",    "range": [0, 1_000_000]},
    "contig_count":          {"label": "Contigs",        "type": "numeric", "unit": "",    "range": [0, 5_000_000]},
}

# Gene Annotation (numeric)
GENE_ANNOTATION_FIELDS = {
    "genes":            {"label": "Total Genes",        "type": "numeric", "unit": "",  "range": [0, 200_000]},
    "protein_coding":   {"label": "Protein Coding",     "type": "numeric", "unit": "",  "range": [0, 100_000]},
    "non_coding_genes": {"label": "Non-coding",         "type": "numeric", "unit": "",  "range": [0, 100_000]},
    "pseudogenes":      {"label": "Pseudogenes",        "type": "numeric", "unit": "",  "range": [0, 50_000]},
}

# BUSCO (numeric, optional)
BUSCO_FIELDS = {
    "busco_complete":   {"label": "BUSCO Complete",     "type": "numeric", "unit": "%",  "range": [0, 100]},
    "busco_single_copy": {"label": "BUSCO Single Copy",  "type": "numeric", "unit": "%",  "range": [0, 100]},
    "busco_duplicated": {"label": "BUSCO Duplicated",   "type": "numeric", "unit": "%",  "range": [0, 100]},
    "busco_fragmented": {"label": "BUSCO Fragmented",   "type": "numeric", "unit": "%",  "range": [0, 100]},
    "busco_missing":    {"label": "BUSCO Missing",      "type": "numeric", "unit": "%",  "range": [0, 100]},
}

# Combined registry
ALL_FILTER_FIELDS = {
    **ASSEMBLY_INFO_FIELDS,
    **QUALITY_METRIC_FIELDS,
    **GENOME_STAT_FIELDS,
    **GENE_ANNOTATION_FIELDS,
    **BUSCO_FIELDS,
}

# Default scoring weights
DEFAULT_SCORING_WEIGHTS = {
    "genome_coverage":  0.35,
    "scaffold_n50_kb":  0.30,
    "quality_score":    0.35,
}


# ── Data classes ──────────────────────────────────────────────────

@dataclass
class AssemblyFilterConfig:
    """Configuration for assembly filtering."""
    mode: str = "scoring"  # "hard" | "scoring"

    # Hard filter thresholds: field → {"min": X, "max": Y}
    hard_filters: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Categorical filters: field → [allowed_values]
    categorical_filters: Dict[str, List[str]] = field(default_factory=dict)

    # Scoring weights: field → weight (0..1, should sum to 1)
    scoring_weights: Dict[str, float] = field(default_factory=dict)

    # Whether to pick only the best assembly per species
    best_per_species: bool = True


@dataclass
class AssemblyFilterResult:
    """Result of assembly filtering."""
    mode: str
    input_species: int
    output_species: int
    filtered_out: int
    species: List[Dict[str, Any]]
    stats: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


# ── Scoring helpers ───────────────────────────────────────────────

def _normalize_value(value: Optional[float], field_meta: dict) -> float:
    """
    Normalize a numeric value to [0, 1] using the field's expected range.
    """
    if value is None:
        return 0.0
    lo, hi = field_meta.get("range", [0, 1])
    if hi == lo:
        return 1.0 if value >= hi else 0.0
    clamped = max(lo, min(hi, value))
    return (clamped - lo) / (hi - lo)


def _compute_assembly_score(
    genome,
    weights: Dict[str, float],
) -> float:
    """
    Compute a weighted composite score for a genome assembly.

    FinalScore = Σ (w_i * normalized(field_i))
    """
    total_weight = sum(weights.values()) or 1.0
    score = 0.0

    for field_name, weight in weights.items():
        meta = ALL_FILTER_FIELDS.get(field_name)
        if not meta or meta["type"] != "numeric":
            continue

        raw = getattr(genome, field_name, None)
        norm = _normalize_value(raw, meta)

        # For fields where lower is better (fragmented, missing), invert
        if field_name in ("busco_fragmented", "busco_missing", "scaffold_count", "contig_count"):
            norm = 1.0 - norm

        score += (weight / total_weight) * norm

    return round(score, 6)


# ── Core functions ────────────────────────────────────────────────

def get_assembly_stats(species_accessions: List[str]) -> Dict[str, Any]:
    """
    Get aggregate assembly statistics for the given species accessions.
    Returns min/max/avg/median for key numeric fields, and
    value distributions for categorical fields.
    """
    from apps.taxonomy.models import NCBIGenome

    qs = NCBIGenome.objects.filter(accession__in=species_accessions)

    if not qs.exists():
        return {"total": 0, "numeric_stats": {}, "categorical_stats": {}}

    genomes = list(qs)
    total = len(genomes)

    # Numeric stats
    numeric_stats = {}
    numeric_fields = {
        **QUALITY_METRIC_FIELDS,
        **GENOME_STAT_FIELDS,
        **GENE_ANNOTATION_FIELDS,
        **BUSCO_FIELDS,
    }

    for fname, meta in numeric_fields.items():
        values = [
            getattr(g, fname) for g in genomes
            if getattr(g, fname, None) is not None
        ]
        if values:
            values.sort()
            n = len(values)
            numeric_stats[fname] = {
                "label": meta["label"],
                "unit": meta.get("unit", ""),
                "count": n,
                "min": values[0],
                "max": values[-1],
                "avg": round(sum(values) / n, 2),
                "median": values[n // 2],
            }

    # Categorical stats
    categorical_stats = {}
    for fname, meta in ASSEMBLY_INFO_FIELDS.items():
        if meta["type"] != "choice":
            continue
        dist = {}
        for g in genomes:
            val = getattr(g, fname, "") or "(empty)"
            dist[val] = dist.get(val, 0) + 1
        categorical_stats[fname] = {
            "label": meta["label"],
            "distribution": dist,
            "choices": meta.get("choices", []),
        }

    return {
        "total": total,
        "numeric_stats": numeric_stats,
        "categorical_stats": categorical_stats,
    }


def run_assembly_filter(
    species_accessions: List[str],
    config: AssemblyFilterConfig,
) -> AssemblyFilterResult:
    """
    Apply assembly filtering to a list of species (identified by accession).

    Steps:
      1. Fetch full genome records from DB
      2. Apply hard filters (if mode == "hard" or both)
      3. Apply scoring (if mode == "scoring")
      4. Optionally pick best assembly per species
      5. Return filtered list with assembly metadata attached.
    """
    from apps.taxonomy.models import NCBIGenome

    warnings: List[str] = []

    # Fetch genomes
    qs = NCBIGenome.objects.filter(
        accession__in=species_accessions,
    ).select_related("taxon", "external_taxon")

    genomes = list(qs)
    input_count = len(genomes)

    if not genomes:
        return AssemblyFilterResult(
            mode=config.mode,
            input_species=0,
            output_species=0,
            filtered_out=0,
            species=[],
            warnings=["No genomes found for the given accessions."],
        )

    # ── 1. Apply categorical filters ────────────────────────
    if config.categorical_filters:
        filtered = []
        for g in genomes:
            keep = True
            for fname, allowed in config.categorical_filters.items():
                if not allowed:
                    continue
                val = getattr(g, fname, "") or ""
                if val not in allowed:
                    keep = False
                    break
            if keep:
                filtered.append(g)

        cat_removed = len(genomes) - len(filtered)
        if cat_removed:
            warnings.append(f"Categorical filters removed {cat_removed} assemblies.")
        genomes = filtered

    # ── 2. Apply hard numeric filters ───────────────────────
    if config.mode in ("hard", "scoring") and config.hard_filters:
        filtered = []
        for g in genomes:
            keep = True
            for fname, thresholds in config.hard_filters.items():
                val = getattr(g, fname, None)
                if val is None:
                    # Skip species with missing data (don't filter out)
                    continue
                if "min" in thresholds and val < thresholds["min"]:
                    keep = False
                    break
                if "max" in thresholds and val > thresholds["max"]:
                    keep = False
                    break
            if keep:
                filtered.append(g)

        hard_removed = len(genomes) - len(filtered)
        if hard_removed:
            warnings.append(f"Hard filters removed {hard_removed} assemblies.")
        genomes = filtered

    # ── 3. Compute scores ───────────────────────────────────
    weights = config.scoring_weights or DEFAULT_SCORING_WEIGHTS

    scored_genomes = []
    for g in genomes:
        score = _compute_assembly_score(g, weights)
        scored_genomes.append((g, score))

    # Sort by score descending
    scored_genomes.sort(key=lambda x: x[1], reverse=True)

    # ── 4. Best per species (deduplicate by organism_name) ──
    if config.best_per_species:
        seen = {}
        unique = []
        for g, score in scored_genomes:
            key = g.organism_name.strip().lower()
            if key not in seen:
                seen[key] = True
                unique.append((g, score))
        before = len(scored_genomes)
        scored_genomes = unique
        if before > len(unique):
            warnings.append(
                f"Selected best assembly for {len(unique)} species "
                f"(from {before} total assemblies)."
            )

    # ── 5. Build output ─────────────────────────────────────
    output_species = []
    for g, score in scored_genomes:
        cls = g.external_taxon.classification or {} if g.external_taxon else {}
        output_species.append({
            # Taxonomy (carried from Step 2)
            "accession": g.accession,
            "organism_name": g.organism_name,
            "taxid": g.taxon.taxid if g.taxon else None,
            "scientific_name": g.taxon.scientific_name if g.taxon else g.organism_name,
            "kingdom": cls.get("kingdom", ""),
            "phylum": cls.get("phylum", ""),
            "class": cls.get("class", ""),
            "order": cls.get("order", ""),
            "family": cls.get("family", ""),
            "genus": cls.get("genus", ""),
            "col_name": g.external_taxon.name if g.external_taxon else "",
            # Assembly Info
            "genome_level": g.genome_level or "",
            "refseq_category": g.refseq_category or "",
            "source_database": g.source_database or "",
            "release_date": g.release_date or "",
            # Quality Metrics
            "quality_score": g.quality_score,
            "genome_coverage": g.genome_coverage,
            "contig_n50_kb": g.contig_n50_kb,
            "scaffold_n50_kb": g.scaffold_n50_kb,
            # Genome Stats
            "total_sequence_length": g.total_sequence_length,
            "gc_percent": g.gc_percent,
            "chromosome_count": g.chromosome_count,
            "scaffold_count": g.scaffold_count,
            "contig_count": g.contig_count,
            # Gene Annotation
            "genes": g.genes,
            "protein_coding": g.protein_coding,
            "non_coding_genes": g.non_coding_genes,
            "pseudogenes": g.pseudogenes,
            # BUSCO
            "busco_complete": g.busco_complete,
            "busco_single_copy": g.busco_single_copy,
            "busco_duplicated": g.busco_duplicated,
            "busco_fragmented": g.busco_fragmented,
            "busco_missing": g.busco_missing,
            # Computed
            "assembly_score": score,
        })

    # Aggregate stats
    scores = [s["assembly_score"] for s in output_species]
    stats = {
        "score_min": round(min(scores), 4) if scores else 0,
        "score_max": round(max(scores), 4) if scores else 0,
        "score_avg": round(sum(scores) / len(scores), 4) if scores else 0,
    }

    return AssemblyFilterResult(
        mode=config.mode,
        input_species=input_count,
        output_species=len(output_species),
        filtered_out=input_count - len(output_species),
        species=output_species,
        stats=stats,
        warnings=warnings,
    )


def get_filter_fields() -> Dict[str, Any]:
    """
    Return the full registry of filterable fields with metadata.
    Used by the frontend to build the dynamic filter UI.
    """
    return {
        "assembly_info": {
            fname: {**meta, "field": fname}
            for fname, meta in ASSEMBLY_INFO_FIELDS.items()
        },
        "quality_metrics": {
            fname: {**meta, "field": fname}
            for fname, meta in QUALITY_METRIC_FIELDS.items()
        },
        "genome_stats": {
            fname: {**meta, "field": fname}
            for fname, meta in GENOME_STAT_FIELDS.items()
        },
        "gene_annotation": {
            fname: {**meta, "field": fname}
            for fname, meta in GENE_ANNOTATION_FIELDS.items()
        },
        "busco": {
            fname: {**meta, "field": fname}
            for fname, meta in BUSCO_FIELDS.items()
        },
        "default_weights": DEFAULT_SCORING_WEIGHTS,
    }
