from __future__ import annotations

from typing import Any, Dict, List

from django.core.cache import cache
from django.db.models import Count, F

from apps.taxonomy.models import ExternalTaxon, NCBIGenome, Taxon, TaxonCrosswalk

DASHBOARD_CACHE_KEY = "taxonomy:dashboard:home_context"
DASHBOARD_CACHE_TTL = 60 * 15  # 15 minutos


def _infer_superkingdom_from_kingdom(kingdom: str | None) -> str | None:
    if not kingdom:
        return None

    lname = kingdom.lower()

    if lname in {"animalia", "plantae", "fungi", "protozoa"}:
        return "Eukarya"
    if "archaea" in lname or "thermoprote" in lname or "methan" in lname:
        return "Archaea"
    return "Bacteria"


def _fill_missing_superkingdoms(kingdom_stats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Evita consultas por fila. Resuelve faltantes en memoria.
    Si en tus datos no existe superkingdom para algunos registros,
    usa una heurística conservadora sin volver a consultar la BD.
    """
    for entry in kingdom_stats:
        if entry.get("superkingdom"):
            continue

        entry["superkingdom"] = _infer_superkingdom_from_kingdom(entry.get("kingdom"))

    return kingdom_stats


def build_home_context() -> Dict[str, Any]:
    """
    Construye el contexto completo del dashboard.
    Pensado para ejecutarse fuera del request y cachearse.
    """

    # ======================
    # Genomas: total + breakdown por status en una sola query
    # ======================
    total_genomes = NCBIGenome.objects.count()

    status_counts = (
        NCBIGenome.objects
        .values("col_match_status")
        .annotate(count=Count("id"))
    )
    status_map = {row["col_match_status"]: row["count"] for row in status_counts}

    matched_genomes = status_map.get("matched", 0)
    manual_genomes = status_map.get("manual", 0)
    unmatched_genomes = status_map.get("unmatched", 0)
    not_in_col_genomes = status_map.get("not_in_col", 0)
    mismatch_genomes = status_map.get("mismatch", 0)
    linked_genomes = matched_genomes + manual_genomes

    # ======================
    # Especies muestreables / excluidas
    # ======================
    samplable_species = (
        ExternalTaxon.objects
        .filter(
            rank__in=["species", "subspecies", "variety", "form"],
            system__in=["col", "manual"],
            ncbi_genomes__col_match_status__in=["matched", "manual"],
        )
        .values("pk")
        .distinct()
        .count()
    )

    excluded_species = (
        Taxon.objects
        .filter(genomes__col_match_status__in=["not_in_col", "mismatch"])
        .values("pk")
        .distinct()
        .count()
    )

    # ======================
    # Taxonomía COL
    # ======================
    total_col_species = (
        ExternalTaxon.objects
        .filter(system="col", rank="species", status="accepted")
        .count()
    )

    total_ncbi_taxa = Taxon.objects.count()
    total_col_taxa = ExternalTaxon.objects.filter(system="col").count()
    total_crosswalks = TaxonCrosswalk.objects.filter(is_active=True).count()

    # ======================
    # Niveles de genoma
    # ======================
    genome_levels = list(
        NCBIGenome.objects
        .values("genome_level")
        .annotate(count=Count("pk"))
        .order_by("-count")
    )

    # ======================
    # Estadísticas por reino
    # ======================
    kingdom_stats = list(
        NCBIGenome.objects
        .filter(external_taxon__isnull=False)
        .exclude(external_taxon__classification__kingdom__isnull=True)
        .exclude(external_taxon__classification__kingdom="")
        .values(
            kingdom=F("external_taxon__classification__kingdom"),
            superkingdom=F("external_taxon__classification__superkingdom"),
        )
        .annotate(count=Count("pk"))
        .order_by("-count")
    )
    kingdom_stats = _fill_missing_superkingdoms(kingdom_stats)

    # ======================
    # Breakdown de estado COL para taxa vinculados con genomas
    # ======================
    col_status_qs = (
        ExternalTaxon.objects
        .filter(system="col", ncbi_genomes__isnull=False)
        .values("status")
        .annotate(count=Count("pk", distinct=True))
    )
    col_status_map = {row["status"]: row["count"] for row in col_status_qs}

    accepted_count = col_status_map.get("accepted", 0)
    synonym_count = (
        col_status_map.get("synonym", 0) +
        col_status_map.get("ambiguous synonym", 0)
    )
    provisional_count = col_status_map.get("provisionally accepted", 0)

    # ======================
    # Coverage COL y taxa manuales
    # ======================
    col_matched_taxa = (
        Taxon.objects
        .filter(genomes__col_match_status="matched")
        .values("pk")
        .distinct()
        .count()
    )

    manual_taxa = (
        Taxon.objects
        .filter(genomes__col_match_status="manual")
        .values("pk")
        .distinct()
        .count()
    )

    col_coverage_pct = round(col_matched_taxa / total_genomes * 100) if total_genomes else 0
    not_in_col_total = not_in_col_genomes + manual_taxa
    mismatch_pending = mismatch_genomes if mismatch_genomes > 0 else not_in_col_genomes

    context = {
        "total_genomes": total_genomes,
        "matched_genomes": matched_genomes,
        "manual_genomes": manual_genomes,
        "linked_genomes": linked_genomes,
        "unmatched_genomes": unmatched_genomes,
        "not_in_col_genomes": not_in_col_genomes,
        "mismatch_genomes": mismatch_genomes,
        "samplable_species": samplable_species,
        "excluded_species": excluded_species,
        "col_matched_taxa": col_matched_taxa,
        "col_coverage_pct": col_coverage_pct,
        "not_in_col_total": not_in_col_total,
        "manual_taxa": manual_taxa,
        "mismatch_pending": mismatch_pending,
        "accepted_count": accepted_count,
        "synonym_count": synonym_count,
        "provisional_count": provisional_count,
        "total_ncbi_taxa": total_ncbi_taxa,
        "total_col_taxa": total_col_taxa,
        "total_col_species": total_col_species,
        "total_crosswalks": total_crosswalks,
        "genome_levels": genome_levels,
        "kingdom_stats": kingdom_stats,
    }
    return context


def get_home_context(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Obtiene el contexto desde cache. Si no existe o se fuerza, lo reconstruye.
    """
    if not force_refresh:
        cached = cache.get(DASHBOARD_CACHE_KEY)
        if cached is not None:
            return cached

    context = build_home_context()
    cache.set(DASHBOARD_CACHE_KEY, context, DASHBOARD_CACHE_TTL)
    return context


def invalidate_home_context_cache() -> None:
    cache.delete(DASHBOARD_CACHE_KEY)