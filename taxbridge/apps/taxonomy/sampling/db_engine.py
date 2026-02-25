# apps/taxonomy/sampling/db_engine.py
"""
Database-based taxonomic sampling engine.

Uses NCBIGenome records with COL classification data
to perform stratified sampling by taxonomic rank.

Strategies:
  - none:         Natural order (by accession) up to max_sample_size
  - random:       Global random selection of K species
  - proportional: n_i = floor(size_i / total * K) + largest-remainder
  - balanced:     n_i = min(floor(K / num_clades), available_i)  (strict)
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from django.db.models import Q, Count
from django.utils import timezone


# Canonical rank hierarchy (coarse to fine)
RANK_HIERARCHY = [
    "kingdom", "phylum", "class", "order", "family", "genus", "species",
]


def _rank_index(rank: str) -> int:
    """Returns the position of a rank in the hierarchy, or -1."""
    r = rank.strip().lower()
    try:
        return RANK_HIERARCHY.index(r)
    except ValueError:
        return -1


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


def _apply_scope_filters(
    qs,
    scope_kingdom: str = "",
    scope_phylum: str = "",
    scope_filters: Optional[Dict[str, str]] = None,
    species_names: Optional[List[str]] = None,
):
    """
    Apply taxonomy scope filters to a queryset.

    scope_filters is a dict like {"kingdom": "Animalia", "phylum": "Chordata",
    "class": "Mammalia"} — each key is a rank, value is the taxon name.
    Filters are intersected (AND).

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

    # Restrict to specific species if provided (from Step 1 targets)
    if species_names:
        qs = qs.filter(organism_name__in=species_names)

    return qs


def run_db_sampling(
    max_sample_size: int,
    start_rank: str = "phylum",
    end_rank: str = "species",
    strategy: str = "proportional",
    scope_kingdom: str = "",
    scope_phylum: str = "",
    scope_filters: Optional[Dict[str, str]] = None,
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
        max_sample_size: Maximum number of species to return
        start_rank: Top grouping rank (e.g. phylum)
        end_rank: Bottom grouping rank before selecting species
        strategy: none | random | proportional | balanced
        scope_kingdom: Filter by kingdom (optional, legacy)
        scope_phylum: Filter by phylum (optional, legacy)
        scope_filters: Dict of rank→taxon filters from Step 1 scope
        species_names: List of specific organism names from Step 1 targets
        config_id: SamplingConfiguration PK (optional)

    Returns:
        SamplingResult with selected species
    """
    from apps.taxonomy.models import NCBIGenome

    warnings: List[str] = []

    # ── 1. Build base queryset ──────────────────────────────
    qs = NCBIGenome.objects.filter(
        col_match_status="matched",
        external_taxon__isnull=False,
    ).select_related("taxon", "external_taxon")

    # Apply scope filters (Step 1 scope + legacy kingdom/phylum)
    qs = _apply_scope_filters(
        qs,
        scope_kingdom=scope_kingdom,
        scope_phylum=scope_phylum,
        scope_filters=scope_filters,
        species_names=species_names,
    )

    total_available = qs.values("organism_name").distinct().count()

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
            warnings=["No matched species found in the database."],
        )

    # Validate max_sample_size
    effective_k = min(max_sample_size, total_available)
    if max_sample_size > total_available:
        warnings.append(
            f"max_sample_size ({max_sample_size}) exceeds available species "
            f"({total_available}). Using {total_available}."
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

    for genome in qs.iterator():
        cls = genome.external_taxon.classification or {}
        clade_name = cls.get(rank_key, "")

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

    # Add unclassified genomes to a special group
    if no_clade_genomes:
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

    if strategy == "none":
        # No grouping logic — just take first K
        _allocate_none(clades_info, effective_k)

    elif strategy == "random":
        # Global random: quotas set after selection (see below)
        pass

    elif strategy == "proportional":
        _allocate_proportional(clades_info, effective_k)

    elif strategy == "balanced":
        _allocate_balanced(clades_info, effective_k)

    else:
        warnings.append(f"Unknown strategy '{strategy}', using 'none'.")
        _allocate_none(clades_info, effective_k)

    # ── 3b. Global random pre-selection ─────────────────────
    _random_selected: set = set()
    if strategy == "random":
        all_genomes = []
        for _name in sorted(clade_genomes.keys()):
            all_genomes.extend(clade_genomes[_name])
        random.shuffle(all_genomes)
        _random_selected = {g.organism_name for g in all_genomes[:effective_k]}
        # Set quotas per clade based on how many fell in each
        for clade in clades_info:
            cg = clade_genomes.get(clade.name, [])
            clade.quota = sum(1 for g in cg if g.organism_name in _random_selected)

    # ── 4. Select species within each clade ─────────────────
    selected_species: List[Dict[str, Any]] = []
    clades_result: List[Dict[str, Any]] = []

    for clade in clades_info:
        genomes = clade_genomes.get(clade.name, [])

        if strategy == "random":
            # Global random: pick genomes whose organism was pre-selected
            picks = [g for g in genomes if g.organism_name in _random_selected]
        elif strategy == "none":
            # Natural order (by accession)
            genomes.sort(key=lambda g: g.accession)
            picks = genomes[:clade.quota]
        else:
            # Proportional / balanced: sort alphabetically for determinism
            genomes.sort(key=lambda g: g.organism_name)
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

    # ── 5. Final limit (safety cap) ────────────────────────
    if len(selected_species) > effective_k:
        selected_species = selected_species[:effective_k]
        warnings.append(
            f"Trimmed result from {len(selected_species)} to {effective_k} species."
        )

    return SamplingResult(
        config_id=config_id,
        strategy=strategy,
        max_sample_size=max_sample_size,
        start_rank=start_rank,
        end_rank=end_rank,
        total_available=total_available,
        total_selected=len(selected_species),
        clades=clades_result,
        species=selected_species,
        warnings=warnings,
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
    """
    total = sum(c.species_count for c in clades) or 1

    # Calculate raw proportional allocation
    raw = [(k * c.species_count) / total for c in clades]

    # Floor values
    floors = [int(math.floor(r)) for r in raw]

    # Distribute remainder by highest fractional part
    remainder = k - sum(floors)
    fracs = [(i, raw[i] - floors[i]) for i in range(len(raw))]
    fracs.sort(key=lambda x: x[1], reverse=True)

    for j in range(min(remainder, len(fracs))):
        floors[fracs[j][0]] += 1

    # Assign quotas, capped by available species
    for i, clade in enumerate(clades):
        clade.quota = min(floors[i], clade.species_count)


def _allocate_balanced(clades: List[CladeAllocation], k: int) -> None:
    """
    Distribute K equally among clades (strict balanced).
    n_i = min(floor(K / num_clades), N_i)
    No redistribution — avoids over-representation of large clades.
    """
    m = len(clades)
    if m == 0:
        return

    base = k // m

    for clade in clades:
        clade.quota = min(base, clade.species_count)


# ============================================================
# Utility: Get available stats for UI
# ============================================================

def get_sampling_stats(
    scope_kingdom: str = "",
    scope_phylum: str = "",
    scope_filters: Optional[Dict[str, str]] = None,
    species_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Returns statistics about available species for sampling config UI.
    Accepts the same scope filters as run_db_sampling.
    """
    from apps.taxonomy.models import NCBIGenome

    qs = NCBIGenome.objects.filter(
        col_match_status="matched",
        external_taxon__isnull=False,
    ).select_related("external_taxon")

    qs = _apply_scope_filters(
        qs,
        scope_kingdom=scope_kingdom,
        scope_phylum=scope_phylum,
        scope_filters=scope_filters,
        species_names=species_names,
    )

    total = qs.count()

    # Count by rank
    rank_counts: Dict[str, Dict[str, int]] = {}
    for rank in RANK_HIERARCHY[:-1]:  # Skip 'species'
        groups: Dict[str, int] = defaultdict(int)
        for genome in qs.iterator():
            cls = genome.external_taxon.classification or {}
            val = cls.get(rank, "")
            if val:
                groups[val] += 1
        rank_counts[rank] = dict(sorted(groups.items()))

    # Available kingdoms
    kingdoms = set()
    phyla = set()
    for genome in qs.only("external_taxon").select_related("external_taxon").iterator():
        cls = genome.external_taxon.classification or {}
        if cls.get("kingdom"):
            kingdoms.add(cls["kingdom"])
        if cls.get("phylum"):
            phyla.add(cls["phylum"])

    return {
        "total_species": total,
        "kingdoms": sorted(kingdoms),
        "phyla": sorted(phyla),
        "rank_breakdown": {
            rank: {
                "num_groups": len(groups),
                "groups": groups,
            }
            for rank, groups in rank_counts.items()
        },
    }
