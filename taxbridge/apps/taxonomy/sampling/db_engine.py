# apps/taxonomy/sampling/db_engine.py
"""
Database-based taxonomic sampling engine.

Uses NCBIGenome records with COL classification data
to perform stratified sampling by taxonomic rank.

Strategies:
  - natural:                Natural order (by accession) up to max_sample_size
  - quality_random:         Random selection within balanced quotas, prioritizing quality
  - stratified_proportional: n_i = floor(size_i / total * K) + largest-remainder
  - balanced_hierarchical:  n_i = floor(K / num_clades) per clade (strictly equal)
"""
from __future__ import annotations

import logging
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from django.db.models import Q, Count
from django.utils import timezone

logger = logging.getLogger(__name__)


# Canonical rank hierarchy (coarse to fine)
RANK_HIERARCHY = [
    "domain", "superkingdom", "kingdom", "phylum", "class", "order",
    "family", "genus", "species",
]

# Model organisms — always prioritize these in sampling
MODEL_ORGANISMS = {
    "Homo sapiens",           # Human
    "Mus musculus",           # Mouse
    "Rattus norvegicus",      # Rat
    "Drosophila melanogaster", # Fruit fly
    "Caenorhabditis elegans", # C. elegans
    "Arabidopsis thaliana",   # Thale cress
    "Danio rerio",            # Zebrafish
    "Gallus gallus",          # Chicken
    "Sus scrofa",             # Pig
    "Bos taurus",             # Cattle
    "Equus caballus",         # Horse
    "Ovis aries",             # Sheep
    "Canis lupus familiaris", # Dog
    "Felis catus",            # Cat
    "Panthera leo",           # Lion
    "Chlorocebus aethiops",   # African green monkey
    "Macaca mulatta",         # Rhesus macaque
    "Pan troglodytes",        # Chimpanzee
    "Gorilla gorilla",        # Gorilla
}


def _rank_index(rank: str) -> int:
    """Returns the position of a rank in the hierarchy, or -1."""
    r = rank.strip().lower()
    try:
        return RANK_HIERARCHY.index(r)
    except ValueError:
        return -1


# ── Species quality scoring ──────────────────────────────────────

# Assembly level ordinal (higher = better)
_LEVEL_SCORE = {
    "complete genome": 4,
    "chromosome":      3,
    "scaffold":        2,
    "contig":          1,
}

# RefSeq category ordinal
_REFSEQ_SCORE = {
    "reference genome":      3,
    "representative genome": 2,
    "na":                    1,
}


def compute_species_score(genome) -> float:
    """
    Compute a composite quality score for a genome assembly.

    The score ranges from 0 to 1 and combines:
      - assembly_level  (20%): Complete > Chromosome > Scaffold > Contig
      - refseq_category (15%): reference > representative > na
      - quality_score   (20%): NCBI pre-computed quality score
      - scaffold_n50    (15%): higher is better (log-scaled, typical 0-500 Mb)
      - genome_coverage (10%): higher is better (capped at 200×)
      - busco_complete  (15%): % of complete BUSCO genes
      - has_annotation  ( 5%): bonus if protein-coding gene count > 0

    Species with missing data get 0 for that component (not penalised
    beyond receiving no bonus).
    """
    score = 0.0

    # 1. Assembly level (0.20)
    level = (getattr(genome, "genome_level", "") or "").lower()
    score += 0.20 * (_LEVEL_SCORE.get(level, 0) / 4)

    # 2. RefSeq category (0.15)
    cat = (getattr(genome, "refseq_category", "") or "").lower()
    score += 0.15 * (_REFSEQ_SCORE.get(cat, 0) / 3)

    # 3. Pre-computed quality_score (0.20)
    qs = getattr(genome, "quality_score", None) or 0.0
    score += 0.20 * min(1.0, max(0.0, qs))

    # 4. Scaffold N50 (0.15) — log-normalised, cap at 500 Mb
    n50 = getattr(genome, "scaffold_n50_kb", None) or 0.0
    if n50 > 0:
        import math as _m
        # log10(1)=0, log10(500_000)=5.7
        score += 0.15 * min(1.0, _m.log10(n50 + 1) / 5.7)

    # 5. Genome coverage (0.10) — linear, capped at 200×
    cov = getattr(genome, "genome_coverage", None) or 0.0
    score += 0.10 * min(1.0, max(0.0, cov / 200))

    # 6. BUSCO complete (0.15) — direct percentage
    busco = getattr(genome, "busco_complete", None) or 0.0
    score += 0.15 * min(1.0, max(0.0, busco / 100))

    # 7. Has annotation bonus (0.05)
    pc = getattr(genome, "protein_coding", None) or 0
    if pc > 0:
        score += 0.05

    return round(score, 6)


@dataclass
class CladeAllocation:
    """A clade with its species count and sampling quota."""
    rank: str
    name: str
    species_count: int
    quota: int = 0
    selected_species: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SamplingResult:
    """Complete sampling result."""
    config_id: Optional[int]
    strategy: str
    max_sample_size: int
    start_rank: str
    end_rank: str
    total_available: int
    total_selected: int
    clades: List[Dict[str, Any]]
    species: List[Dict[str, Any]]
    warnings: List[str] = field(default_factory=list)
    available_species: List[Dict[str, Any]] = field(default_factory=list)  # All species data in scope (for adding)


def _apply_scope_filters(
    qs,
    scope_kingdom: str = "",
    scope_phylum: str = "",
    scope_filters: Optional[Dict[str, str]] = None,
    target_keys: Optional[List[str]] = None,
    species_names: Optional[List[str]] = None,
):
    """
    Apply taxonomy scope filters to a queryset.

    scope_filters is a dict like {"kingdom": "Animalia", "phylum": "Chordata",
    "class": "Mammalia"} — each key is a rank, value is the taxon name.
    Filters are intersected (AND).

    target_keys is a list of tree path keys like
    ["kingdom:Animalia|phylum:Chordata", "kingdom:Animalia|phylum:Arthropoda"].
    Each key is parsed into rank→name pairs and the species must belong to
    at least ONE of the target clades (OR).

    species_names is a list of organism names to restrict the queryset to
    (e.g., from Step 1 target selection).
    """
    # Legacy simple filters
    if scope_kingdom:
        qs = qs.filter(external_taxon__classification__kingdom=scope_kingdom)
    if scope_phylum:
        qs = qs.filter(external_taxon__classification__phylum=scope_phylum)

    # New: arbitrary rank filters from Step 1 scope key
    if scope_filters:
        for rank, taxon_name in scope_filters.items():
            rank_lower = rank.strip().lower()
            if rank_lower in RANK_HIERARCHY and taxon_name:
                lookup = f"external_taxon__classification__{rank_lower}"
                qs = qs.filter(**{lookup: taxon_name})

    # Target clades: species must belong to at least one target (OR)
    if target_keys:
        combined_q = Q()
        for tk in target_keys:
            target_q = Q()
            for seg in str(tk).split("|"):
                idx = seg.find(":")
                if idx < 0:
                    continue
                rank = seg[:idx].strip().lower()
                name = seg[idx + 1:].strip()
                if rank in RANK_HIERARCHY and name:
                    target_q &= Q(**{f"external_taxon__classification__{rank}": name})
            if target_q:
                combined_q |= target_q
        if combined_q:
            logger.info("[_apply_scope_filters] Applying target_keys filter: %s", target_keys)
            qs = qs.filter(combined_q)

    # Restrict to specific species if provided (from Step 1 targets)
    if species_names:
        qs = qs.filter(organism_name__in=species_names)

    return qs


def run_db_sampling(
    max_sample_size: int,
    start_rank: str = "phylum",
    end_rank: str = "species",
    strategy: str = "stratified_proportional",
    scope_kingdom: str = "",
    scope_phylum: str = "",
    scope_filters: Optional[Dict[str, str]] = None,
    target_keys: Optional[List[str]] = None,
    species_names: Optional[List[str]] = None,
    config_id: Optional[int] = None,
) -> SamplingResult:
    """
    Execute sampling on the local database.

    Flow:
      1. Get the taxonomic subset (species with matched COL data)
      2. Group by start_rank → (optionally cascade to end_rank)
      3. Apply sampling strategy to determine quotas
      4. Select species within each clade according to strategy
      5. Limit total to max_sample_size

    Args:
        max_sample_size: Maximum number of species to return (0 = all)
        start_rank: Top grouping rank (e.g. phylum)
        end_rank: Bottom grouping rank before selecting species
        strategy: natural | quality_random | stratified_proportional | balanced_hierarchical
        scope_kingdom: Filter by kingdom (optional, legacy)
        scope_phylum: Filter by phylum (optional, legacy)
        scope_filters: Dict of rank→taxon filters from Step 1 scope
        target_keys: List of tree path keys for target clades
        species_names: List of specific organism names from Step 1 targets
        config_id: SamplingConfiguration PK (optional)

    Returns:
        SamplingResult with selected species
    """
    from apps.taxonomy.models import NCBIGenome

    warnings: List[str] = []

    # ── 1. Build base queryset ──────────────────────────────
    qs = NCBIGenome.objects.filter(
        col_match_status__in=("matched", "manual"),
        external_taxon__isnull=False,
    ).select_related("taxon", "external_taxon")

    # Apply scope filters (Step 1 scope + legacy kingdom/phylum)
    qs = _apply_scope_filters(
        qs,
        scope_kingdom=scope_kingdom,
        scope_phylum=scope_phylum,
        scope_filters=scope_filters,
        target_keys=target_keys,
        species_names=species_names,
    )

    total_available_raw = qs.values("organism_name").distinct().count()

    # Debug: log the actual species names to compare with tree
    if target_keys:
        _debug_species = list(qs.values_list("organism_name", flat=True).distinct()[:50])
        logger.info(
            "[run_db_sampling] DEBUG target_keys=%s → found %d species (first 50: %s)",
            target_keys[:3] if target_keys else [],
            total_available_raw,
            _debug_species,
        )

    logger.info(
        "[run_db_sampling] scope applied → total_available=%d, "
        "max_sample_size=%d, strategy=%s, start_rank=%s, end_rank=%s",
        total_available_raw, max_sample_size, strategy, start_rank, end_rank,
    )

    if total_available_raw == 0:
        return SamplingResult(
            config_id=config_id,
            strategy=strategy,
            max_sample_size=max_sample_size,
            start_rank=start_rank,
            end_rank=end_rank,
            total_available=0,
            total_selected=0,
            clades=[],
            species=[],
            warnings=["No matched species found in the database."],
        )

    # ── 2. Group species by taxonomic rank ──────────────────
    # We group by the start_rank extracted from classification JSON
    rank_key = start_rank.lower()

    # Build clade → genome mapping (deduplicated: best genome per species)
    clade_genomes: Dict[str, List] = defaultdict(list)
    no_clade_genomes: List = []

    # First pass: collect all genomes per clade
    _clade_all: Dict[str, List] = defaultdict(list)
    _no_clade_all: List = []
    _genus_skipped = 0
    _valid_species: set = set()
    _all_genomes_by_name: Dict[str, Any] = {}  # Best genome per organism_name (for available_species)

    for genome in qs.iterator():
        # ── Genus-validation safeguard ──
        # Skip genomes whose organism_name genus diverges completely from
        # the linked COL taxon (bad matches that slipped past audit).
        _org = (genome.organism_name or "").strip()
        _org_g = _org.split()[0].lower() if _org else ""
        
        # Handle bracketed genus names like [Clostridium]
        if _org.startswith("[") and "]" in _org:
            _org_g = _org.split("]")[0][1:].lower()
        
        if _org_g and genome.external_taxon:
            _col_name = (genome.external_taxon.name or "").lower()
            _col_cls = genome.external_taxon.classification or {}
            _col_g = (_col_cls.get("genus", "") or "").lower()
            _col_sp = (_col_cls.get("species", "") or "").lower()
            
            # Only skip if genus doesn't appear anywhere in COL data
            if (_org_g not in _col_g and 
                _org_g not in _col_sp and 
                _org_g not in _col_name):
                _genus_skipped += 1
                continue

        _valid_species.add(genome.organism_name)
        
        # Track best genome per organism for available_species data
        org_name = genome.organism_name
        if org_name not in _all_genomes_by_name:
            _all_genomes_by_name[org_name] = genome
        elif (genome.quality_score or 0) > (_all_genomes_by_name[org_name].quality_score or 0):
            _all_genomes_by_name[org_name] = genome
        
        cls = genome.external_taxon.classification or {}
        clade_name = cls.get(rank_key, "")

        # Fallback: if the target rank is missing, walk up the hierarchy
        if not clade_name:
            rank_idx = _rank_index(rank_key)
            for fallback_rank in reversed(RANK_HIERARCHY[:rank_idx]):
                clade_name = cls.get(fallback_rank, "")
                if clade_name:
                    break

        if not clade_name:
            _no_clade_all.append(genome)
            continue

        # If end_rank != species, we group further down
        if end_rank.lower() != "species" and _rank_index(end_rank) < _rank_index("species"):
            sub_key = cls.get(end_rank.lower(), "")
            if sub_key:
                composite_key = f"{clade_name} > {sub_key}"
            else:
                composite_key = clade_name
        else:
            composite_key = clade_name

        _clade_all[composite_key].append(genome)

    if _genus_skipped > 0:
        warnings.append(
            f"{_genus_skipped} genomes skipped: COL genus mismatch "
            f"(run 'manage.py audit_col_matches --fix' to clean)."
        )
        logger.warning(
            "[run_db_sampling] %d genomes skipped due to genus mismatch",
            _genus_skipped,
        )

    # Recalculate total_available using valid (post-filter) species count
    total_available = len(_valid_species)

    if total_available == 0:
        return SamplingResult(
            config_id=config_id,
            strategy=strategy,
            max_sample_size=max_sample_size,
            start_rank=start_rank,
            end_rank=end_rank,
            total_available=0,
            total_selected=0,
            clades=[],
            species=[],
            warnings=warnings + ["No valid species after genus-mismatch filtering."],
        )

    # Validate max_sample_size (0 = use all available)
    if max_sample_size <= 0:
        max_sample_size = total_available
    effective_k = min(max_sample_size, total_available)
    if max_sample_size > total_available:
        warnings.append(
            f"max_sample_size ({max_sample_size}) exceeds available species "
            f"({total_available}). Using {total_available}."
        )

    # Second pass: deduplicate — keep best genome per organism_name
    # (highest quality_score) within each clade
    def _dedup_genomes(genomes_list):
        best: Dict[str, Any] = {}
        for g in genomes_list:
            name = g.organism_name
            if name not in best or (g.quality_score or 0) > (best[name].quality_score or 0):
                best[name] = g
        return list(best.values())

    for key, genomes_list in _clade_all.items():
        clade_genomes[key] = _dedup_genomes(genomes_list)

    if _no_clade_all:
        no_clade_genomes = _dedup_genomes(_no_clade_all)

    # Only include unclassified genomes if NO specific targets are set.
    # If user selected targets explicitly, unclassified species are excluded
    # because we cannot verify they belong to the selected targets.
    if no_clade_genomes:
        if target_keys:
            # User selected specific targets → exclude unclassified
            warnings.append(
                f"{len(no_clade_genomes)} species excluded: lack '{rank_key}' "
                f"classification (cannot verify target membership)."
            )
            logger.info(
                "[run_db_sampling] Excluded %d unclassified species (targets specified)",
                len(no_clade_genomes),
            )
        else:
            # No specific targets → include unclassified in sampling
            clade_genomes["(unclassified)"] = no_clade_genomes
            warnings.append(
                f"{len(no_clade_genomes)} species lack '{rank_key}' classification."
            )

    # ── 3. Calculate quotas per clade ───────────────────────
    clades_info: List[CladeAllocation] = []
    for name, genomes in sorted(clade_genomes.items()):
        clades_info.append(CladeAllocation(
            rank=rank_key,
            name=name,
            species_count=len(genomes),
        ))

    num_clades = len(clades_info)

    if strategy == "natural":
        # Natural order: take first K by accession within each clade
        _allocate_none(clades_info, effective_k)

    elif strategy == "quality_random":
        # Quality-weighted random: balanced quotas with random selection
        # (prioritizes quality during selection)
        _allocate_balanced(clades_info, effective_k)

    elif strategy == "stratified_proportional":
        # Proportional to clade size: n_i = floor(K * N_i / N_total) + largest-remainder
        _allocate_proportional(clades_info, effective_k)

    elif strategy == "balanced_hierarchical":
        # Balanced: equal quota per clade n_i = floor(K / num_clades)
        _allocate_balanced(clades_info, effective_k)

    else:
        warnings.append(f"Unknown strategy '{strategy}', using 'natural'.")
        _allocate_none(clades_info, effective_k)

    # ── 4. Select species within each clade ─────────────────
    selected_species: List[Dict[str, Any]] = []
    clades_result: List[Dict[str, Any]] = []

    for clade in clades_info:
        genomes = clade_genomes.get(clade.name, [])

        if strategy == "quality_random":
            # Quality-random: sort by quality score (best first), then random sample
            if clade.quota > 0 and len(genomes) > 0:
                genomes.sort(key=lambda g: (-compute_species_score(g), g.organism_name))
                # Take best 2x quota candidates, then random sample from them
                candidates = genomes[:min(len(genomes), clade.quota * 2)]
                num_to_pick = min(clade.quota, len(candidates))
                picks = random.sample(candidates, num_to_pick)
            else:
                picks = []
        elif strategy == "natural":
            # Natural order: by accession, take first K
            genomes.sort(key=lambda g: g.accession)
            picks = genomes[:clade.quota]
        else:
            # Proportional / balanced: rank by quality score (best first).
            # Deterministic tie-breaking by organism_name for reproducibility.
            genomes.sort(
                key=lambda g: (-compute_species_score(g), g.organism_name)
            )
            picks = genomes[:clade.quota]

        clade_species = []
        for g in picks:
            cls = g.external_taxon.classification or {} if g.external_taxon else {}
            species_data = {
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
                "clade_group": clade.name,
                # Genome metadata for Excel export
                "genome_level": g.genome_level or "",
                "refseq_category": g.refseq_category or "",
                "genome_coverage": g.genome_coverage,
                "total_sequence_length": g.total_sequence_length,
                "gc_percent": g.gc_percent,
                "contig_n50_kb": g.contig_n50_kb,
                "scaffold_n50_kb": g.scaffold_n50_kb,
                "scaffold_count": g.scaffold_count,
                "chromosome_count": g.chromosome_count,
                "genes": g.genes,
                "protein_coding": g.protein_coding,
                "quality_score": g.quality_score,
                "release_date": g.release_date or "",
                "source_database": g.source_database or "",
                "sequencing_tech": g.sequencing_tech or "",
                "busco_complete": g.busco_complete,
                "species_score": compute_species_score(g),
            }
            clade_species.append(species_data)
            selected_species.append(species_data)

        clades_result.append({
            "rank": clade.rank,
            "name": clade.name,
            "species_available": clade.species_count,
            "quota": clade.quota,
            "selected": len(clade_species),
            "species": clade_species,
        })

    # ── 4b. Global dedup (same species may appear in multiple clades) ──
    _seen_names: set = set()
    _deduped: List[Dict[str, Any]] = []
    for sp in selected_species:
        oname = sp.get("organism_name", "")
        if oname not in _seen_names:
            _seen_names.add(oname)
            _deduped.append(sp)
    if len(_deduped) < len(selected_species):
        warnings.append(
            f"Removed {len(selected_species) - len(_deduped)} cross-clade "
            f"duplicate species (kept best per clade)."
        )
        selected_species = _deduped

    # ── 5. Final limit (safety cap) ────────────────────────
    if len(selected_species) > effective_k:
        pre_trim = len(selected_species)
        selected_species = selected_species[:effective_k]
        warnings.append(
            f"Trimmed result from {pre_trim} to {effective_k} species."
        )

    logger.info(
        "[run_db_sampling] result → total_selected=%d, effective_k=%d, "
        "num_clades=%d, sum_quotas=%d",
        len(selected_species), effective_k, len(clades_result),
        sum(c.get('quota', 0) if isinstance(c, dict) else c.quota for c in clades_info),
    )

    # ── Apply model organism boost ──
    # Reorganize to prioritize model organisms in the result
    model_species = []
    other_species = []
    for sp in selected_species:
        if sp.get("organism_name") in MODEL_ORGANISMS:
            model_species.append(sp)
        else:
            other_species.append(sp)
    
    # Sort model organisms first, then others
    final_selected = model_species + other_species

    # ── Build available_species with full data ──
    # Include all species in scope with their taxonomic classification
    # and ALL genome metadata (needed when user adds species manually)
    _selected_names = {sp.get("organism_name") for sp in final_selected}
    _available_species_data: List[Dict[str, Any]] = []
    
    for org_name in sorted(_valid_species):
        g = _all_genomes_by_name.get(org_name)
        if not g:
            continue
        cls = g.external_taxon.classification or {} if g.external_taxon else {}
        _available_species_data.append({
            # Identification
            "organism_name": org_name,
            "accession": g.accession,
            "taxid": g.taxon.taxid if g.taxon else None,
            "scientific_name": g.taxon.scientific_name if g.taxon else org_name,
            # Taxonomy (for tree placement and Excel)
            "kingdom": cls.get("kingdom", ""),
            "phylum": cls.get("phylum", ""),
            "class": cls.get("class", ""),
            "order": cls.get("order", ""),
            "family": cls.get("family", ""),
            "genus": cls.get("genus", ""),
            "col_name": g.external_taxon.name if g.external_taxon else "",
            # Assembly metadata (for Excel export - scientific articles)
            "genome_level": g.genome_level or "",
            "refseq_category": g.refseq_category or "",
            "genome_coverage": g.genome_coverage,
            "total_sequence_length": g.total_sequence_length,
            "gc_percent": g.gc_percent,
            "contig_n50_kb": g.contig_n50_kb,
            "scaffold_n50_kb": g.scaffold_n50_kb,
            "scaffold_count": g.scaffold_count,
            "chromosome_count": g.chromosome_count,
            "genes": g.genes,
            "protein_coding": g.protein_coding,
            "quality_score": g.quality_score,
            "release_date": g.release_date or "",
            "source_database": g.source_database or "",
            "sequencing_tech": g.sequencing_tech or "",
            "busco_complete": g.busco_complete,
            "species_score": compute_species_score(g),
        })

    return SamplingResult(
        config_id=config_id,
        strategy=strategy,
        max_sample_size=max_sample_size,
        start_rank=start_rank,
        end_rank=end_rank,
        total_available=total_available,
        total_selected=len(final_selected),
        clades=clades_result,
        species=final_selected,
        warnings=warnings,
        available_species=_available_species_data,  # All species data in scope
    )


# ============================================================
# Allocation strategies
# ============================================================

def _allocate_none(clades: List[CladeAllocation], k: int) -> None:
    """No real allocation — assign quota sequentially until K is reached."""
    remaining = k
    for clade in clades:
        take = min(remaining, clade.species_count)
        clade.quota = take
        remaining -= take
        if remaining <= 0:
            break


def _allocate_proportional(clades: List[CladeAllocation], k: int) -> None:
    """
    Distribute K proportionally to species richness.
    n_i = (size_i / total_size) * K
    Uses largest-remainder method for fair rounding.

    Tie-breaking: when two clades have the same fractional remainder,
    the *smaller* clade gets priority.  This guarantees minimum
    representation for rare lineages (e.g. 152+8 with K=50 → 47+3,
    not 48+2).
    """
    total = sum(c.species_count for c in clades) or 1

    # Calculate raw proportional allocation
    raw = [(k * c.species_count) / total for c in clades]

    # Floor values
    floors = [int(math.floor(r)) for r in raw]

    # Distribute remainder by highest fractional part.
    # Secondary sort: prefer smaller clades (fewer species) in ties
    # so rare lineages get the rounding bump.
    remainder = k - sum(floors)
    fracs = [
        (i, raw[i] - floors[i], clades[i].species_count)
        for i in range(len(raw))
    ]
    fracs.sort(key=lambda x: (x[1], -x[2]), reverse=True)

    for j in range(min(remainder, len(fracs))):
        floors[fracs[j][0]] += 1

    # Assign quotas, capped by available species
    for i, clade in enumerate(clades):
        clade.quota = min(floors[i], clade.species_count)


def _allocate_balanced(clades: List[CladeAllocation], k: int) -> None:
    """
    Distribute K equally among clades (balanced).
    
    When num_clades <= K:
        Each clade gets floor(K / num_clades), with remainder distributed
        to clades with available species (smallest clades first for fairness).
    
    When num_clades > K:
        Only K clades can receive 1 species each. Priority is given to:
        1. Clades that have species available
        2. Smaller clades (to maximize diversity)
    """
    m = len(clades)
    if m == 0:
        return

    if m <= k:
        # Normal case: more quota than clades
        base = k // m
        remainder = k % m
        
        # Sort by species_count ascending (prioritize smaller clades for remainder)
        indexed = list(enumerate(clades))
        indexed.sort(key=lambda x: x[1].species_count)
        
        # Assign base quota to all clades
        for clade in clades:
            clade.quota = min(base, clade.species_count)
        
        # Distribute remainder to clades that can still take more
        for i, clade in indexed:
            if remainder <= 0:
                break
            if clade.quota < clade.species_count:
                clade.quota += 1
                remainder -= 1
    else:
        # More clades than K: select 1 species from K different clades
        # Sort clades by size (smallest first) to maximize diversity
        indexed = [(i, c) for i, c in enumerate(clades) if c.species_count > 0]
        indexed.sort(key=lambda x: x[1].species_count)
        
        # Give quota=1 to at most K clades
        assigned = 0
        for i, clade in indexed:
            if assigned >= k:
                break
            clade.quota = 1
            assigned += 1


# ============================================================
# Utility: Get available stats for UI
# ============================================================

import time as _time

# Simple in-memory cache for sampling stats
_stats_cache: Dict[str, Any] = {}
_stats_cache_key: str = ""
_stats_cache_ts: float = 0.0
_STATS_CACHE_TTL = 300  # 5 minutes


def get_sampling_stats(
    scope_kingdom: str = "",
    scope_phylum: str = "",
    scope_filters: Optional[Dict[str, str]] = None,
    target_keys: Optional[List[str]] = None,
    species_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Returns statistics about available species for sampling config UI.
    Accepts the same scope filters as run_db_sampling.

    Optimised: single pass over the queryset instead of N iterations.
    Results are cached for 5 minutes per unique parameter combination.
    """
    global _stats_cache, _stats_cache_key, _stats_cache_ts

    import json as _json
    cache_key = _json.dumps(
        [scope_kingdom, scope_phylum, scope_filters, sorted(target_keys or []),
         sorted(species_names or [])],
        sort_keys=True,
    )
    now = _time.monotonic()
    if cache_key == _stats_cache_key and _stats_cache and (now - _stats_cache_ts) < _STATS_CACHE_TTL:
        return _stats_cache

    from apps.taxonomy.models import NCBIGenome

    qs = NCBIGenome.objects.filter(
        col_match_status__in=("matched", "manual"),
        external_taxon__isnull=False,
    ).select_related("external_taxon")

    qs = _apply_scope_filters(
        qs,
        scope_kingdom=scope_kingdom,
        scope_phylum=scope_phylum,
        scope_filters=scope_filters,
        target_keys=target_keys,
        species_names=species_names,
    )

    total = qs.values("organism_name").distinct().count()

    # Single pass: gather kingdoms, phyla and rank counts at once
    # Also apply genus-validation safeguard (skip bad COL links)
    ranks_of_interest = RANK_HIERARCHY[:-1]  # skip 'species'
    rank_counts: Dict[str, Dict[str, int]] = {r: defaultdict(int) for r in ranks_of_interest}
    kingdoms: set = set()
    phyla: set = set()
    valid_species: set = set()

    for genome in qs.only(
        "organism_name",
        "external_taxon__classification",
        "external_taxon__name",
    ).select_related("external_taxon").iterator():
        # Genus-validation safeguard - DISABLED TO DEBUG
        # _org = (genome.organism_name or "").strip()
        # _org_g = _org.split()[0].lower() if _org else ""
        # if _org_g and genome.external_taxon:
        #     _col_name = (genome.external_taxon.name or "").lower()
        #     _col_cls = genome.external_taxon.classification or {}
        #     _col_g = (_col_cls.get("genus", "") or "").lower()
        #     _col_sp = (_col_cls.get("species", "") or "").lower()
        #     if _org_g not in _col_g and _org_g not in _col_sp and _org_g not in _col_name:
        #         continue

        cls = genome.external_taxon.classification or {}
        valid_species.add(genome.organism_name)
        k = cls.get("kingdom", "")
        p = cls.get("phylum", "")
        if k:
            kingdoms.add(k)
        if p:
            phyla.add(p)
        for rank in ranks_of_interest:
            val = cls.get(rank, "")
            if val:
                rank_counts[rank][val] += 1

    result = {
        "total_species": len(valid_species),
        "kingdoms": sorted(kingdoms),
        "phyla": sorted(phyla),
        "rank_breakdown": {
            rank: {
                "num_groups": len(groups),
                "groups": dict(sorted(groups.items())),
            }
            for rank, groups in rank_counts.items()
        },
    }

    _stats_cache = result
    _stats_cache_key = cache_key
    _stats_cache_ts = now
    return result
