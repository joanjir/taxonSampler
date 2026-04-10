# apps/taxonomy/ncbi/views.py
"""
Views for Taxon Sync - Downloads from NCBI and matches with COL.

This interface allows:
1. Selecting a kingdom to sync (Metazoa, Fungi, etc.)
2. Downloading genomes from NCBI with quality filters
3. Matching NCBI taxa with COL via ChecklistBank API
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, Iterator, Optional

import requests

from django.db import transaction
from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.taxonomy.models import (
    ExternalTaxon,
    NCBIGenome,
    Taxon,
    TaxonCrosswalk,
    TaxonSyncRun,
)
from apps.taxonomy.ncbi.clients import (
    ChecklistBankClient,
    canonicalize_scientific_name,
)

# Import from NCBI module service
from apps.taxonomy.ncbi.service import (
    KINGDOMS,
    QUALITY_CRITERIA,
    COL_DATASET,
    GenomeFilters,
    fetch_ncbi_genomes,
    get_kingdom_taxid,
    get_quality_criteria,
    compute_quality_score,
)

logger = logging.getLogger(__name__)

# NCBI API base URL
NCBI_API = "https://api.ncbi.nlm.nih.gov/datasets/v2"


# ============================================================
# Dashboard View
# ============================================================

@require_GET
def taxon_sync_dashboard(request):
    """Main page for Taxon Sync."""
    from apps.taxonomy.models import DiscoveredSpecies

    recent_syncs = TaxonSyncRun.objects.all()[:10]
    running_sync = TaxonSyncRun.objects.filter(
        status__in=["pending", "fetching_ncbi", "matching_col"]
    ).first()

    total_genomes = NCBIGenome.objects.count()
    matched_genomes = NCBIGenome.objects.filter(col_match_status="matched").count()
    manual_genomes = NCBIGenome.objects.filter(col_match_status="manual").count()
    linked_genomes = matched_genomes + manual_genomes
    total_taxa = Taxon.objects.count()

    # Samplable species = species that appear in the tree (matched + manual)
    # Must match the tree badge and home dashboard.
    samplable_col = (
        ExternalTaxon.objects
        .filter(
            system="col",
            rank__in=["species", "subspecies", "variety", "form"],
            ncbi_genomes__col_match_status="matched",
        )
        .distinct()
        .count()
    )
    samplable_manual = ExternalTaxon.objects.filter(
        system="manual",
        rank__in=["species", "subspecies", "variety", "form"],
        ncbi_genomes__col_match_status="manual",
    ).distinct().count()
    samplable_species = samplable_col + samplable_manual

    # Not in COL = status "not_in_col" + "manual" (added manually because not found in COL)
    not_in_col_status = (
        Taxon.objects.filter(genomes__col_match_status="not_in_col")
        .distinct()
        .count()
    )
    manual_taxa = (
        Taxon.objects.filter(genomes__col_match_status="manual")
        .distinct()
        .count()
    )
    not_in_col_taxa = not_in_col_status + manual_taxa
    mismatch_taxa = (
        Taxon.objects.filter(genomes__col_match_status="mismatch")
        .distinct()
        .count()
    )
    unresolved_taxa = not_in_col_status + mismatch_taxa

    # COL coverage: only auto-matched taxa count (manual are NOT in COL)
    col_matched_taxa = (
        Taxon.objects.filter(genomes__col_match_status="matched")
        .distinct()
        .count()
    )
    col_coverage_pct = round(col_matched_taxa / total_taxa * 100) if total_taxa else 0

    stats = {
        "total_taxa": total_taxa,
        "total_genomes": total_genomes,
        "linked_genomes": linked_genomes,
        "samplable_species": samplable_species,
        "col_matched_taxa": col_matched_taxa,
        "col_coverage_pct": col_coverage_pct,
        "not_in_col_taxa": not_in_col_taxa,
        "manual_taxa": manual_taxa,
        "mismatch_taxa": mismatch_taxa,
        "unresolved_taxa": unresolved_taxa,
        "total_syncs": TaxonSyncRun.objects.count(),
        "successful_syncs": TaxonSyncRun.objects.filter(status="completed").count(),
        "crosswalks": TaxonCrosswalk.objects.filter(is_active=True).count(),
    }
    
    # Sync status breakdown for chart
    sync_status_counts = {
        "completed": TaxonSyncRun.objects.filter(status="completed").count(),
        "failed": TaxonSyncRun.objects.filter(status="failed").count(),
        "cancelled": TaxonSyncRun.objects.filter(status="cancelled").count(),
    }

    # Statistics per kingdom
    kingdom_stats = []
    for kingdom, taxid in KINGDOMS.items():
        phylum_filter = kingdom.capitalize()
        count = Taxon.objects.filter(
            genomes__isnull=False
        ).distinct().count()  # Simplified, improve with a real filter
        kingdom_stats.append({"name": kingdom, "taxid": taxid, "count": count})

    # Pending discoveries count
    pending_discoveries = DiscoveredSpecies.objects.filter(
        is_imported=False, is_dismissed=False
    ).count()

    context = {
        "recent_syncs": recent_syncs,
        "running_sync": running_sync,
        "stats": stats,
        "sync_status_counts": sync_status_counts,
        "kingdoms": KINGDOMS,
        "kingdom_stats": kingdom_stats,
        "pending_discoveries": pending_discoveries,
    }

    return render(request, "taxonomy/pages/taxon-sync/dashboard.html", context)


# ============================================================
# API Endpoints
# ============================================================

@require_POST
def api_start_taxon_sync(request):
    """Start a new taxon sync via Celery. Admin only."""
    if not (request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)):
        return JsonResponse({"error": "Permission denied"}, status=403)
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    kingdom = data.get("kingdom", "metazoa").lower()
    
    # Resolve taxid: known kingdoms, numeric taxid, or NCBI search by name
    try:
        taxid = get_kingdom_taxid(kingdom)
    except ValueError as e:
        return JsonResponse({
            "error": str(e),
            "available": list(KINGDOMS.keys()),
        }, status=400)

    # Check if already running
    running = TaxonSyncRun.objects.filter(
        status__in=["pending", "fetching_ncbi", "matching_col"]
    ).exists()
    if running:
        return JsonResponse({
            "success": False,
            "error": "A sync is already in progress",
        }, status=409)

    # Create sync run
    sync_run = TaxonSyncRun.objects.create(
        kingdom=kingdom,
        config={
            "limit": data.get("limit", 0),
            "skip_quality": data.get("skip_quality", False),
            "skip_existing": data.get("skip_existing", True),  # Skip existing by default
            "taxid": taxid,
        },
    )

    # Decide whether to use Celery or threading
    # Use Celery only if explicitly enabled and workers are available
    use_celery = False
    from django.conf import settings
    celery_enabled = getattr(settings, 'USE_CELERY_FOR_SYNC', False)
    
    if celery_enabled:
        try:
            from apps.taxonomy.ncbi.tasks import sync_taxon_with_col
            from celery import current_app
            
            # Check if there are active Celery workers
            inspector = current_app.control.inspect()
            active_workers = inspector.active()
            
            if active_workers:
                task = sync_taxon_with_col.delay(sync_run_id=sync_run.pk)
                sync_run.celery_task_id = task.id
                sync_run.save(update_fields=["celery_task_id"])
                use_celery = True
                logger.info(f"Launched Celery task {task.id} for sync {sync_run.pk}")
            else:
                logger.warning("No Celery workers available, using threading")
        except Exception as e:
            logger.warning(f"Celery error ({e}), using threading fallback")
    
    if not use_celery:
        # Use threading (default for development)
        import threading
        thread = threading.Thread(
            target=_run_taxon_sync,
            args=(sync_run.pk,),
            daemon=True,
        )
        thread.start()
        logger.info(f"Launched thread for sync {sync_run.pk}")

    return JsonResponse({
        "success": True,
        "sync_run_id": sync_run.pk,
        "task_id": sync_run.celery_task_id if use_celery else None,
        "backend": "celery" if use_celery else "threading",
    })


@require_GET
def api_taxon_sync_status(request, sync_id: int):
    """Get status of a taxon sync run."""
    try:
        run = TaxonSyncRun.objects.get(pk=sync_id)
    except TaxonSyncRun.DoesNotExist:
        return JsonResponse({"error": "Sync not found"}, status=404)

    return JsonResponse({
        "id": run.pk,
        "status": run.status,
        "kingdom": run.kingdom,
        "progress_percent": run.progress_percent,
        "ncbi_total": run.ncbi_total,
        "ncbi_fetched": run.ncbi_fetched,
        "ncbi_skipped": run.ncbi_skipped,
        "taxa_created": run.taxa_created,
        "genomes_created": run.genomes_created,
        "col_total": run.col_total,
        "col_matched": run.col_matched,
        "col_unmatched": run.col_unmatched,
        "crosswalks_created": run.crosswalks_created,
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_seconds": run.duration_seconds,
    })


@require_POST
def api_cancel_taxon_sync(request, sync_id: int):
    """Cancel a pending or running sync. Admin only."""
    if not (request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)):
        return JsonResponse({"error": "Permission denied"}, status=403)
    try:
        run = TaxonSyncRun.objects.get(pk=sync_id)
    except TaxonSyncRun.DoesNotExist:
        return JsonResponse({"error": "Sync not found"}, status=404)

    # Can't cancel if already completed, failed or cancelled
    if run.status in ("completed", "failed", "cancelled"):
        return JsonResponse({
            "error": f"Cannot cancel sync with status '{run.status}'"
        }, status=400)

    run.status = "cancelled"
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "finished_at"])

    return JsonResponse({"success": True})


# ============================================================
# Sync Logic
# ============================================================

def _run_taxon_sync(sync_run_id: int):
    """
    Background function to execute the full taxon sync.
    Phase 1: Fetch from NCBI
    Phase 2: Match with COL
    """
    try:
        sync_run = TaxonSyncRun.objects.get(pk=sync_run_id)
    except TaxonSyncRun.DoesNotExist:
        return

    try:
        sync_run.mark_started()
        sync_run.add_log("INFO", f"Started taxon sync for {sync_run.kingdom}")

        # Phase 1: Fetch from NCBI
        _phase_fetch_ncbi(sync_run)

        if sync_run.status == "cancelled":
            return

        # Phase 2: Match with COL
        sync_run.mark_col_phase()
        _phase_match_col(sync_run)

        sync_run.mark_completed()
        sync_run.add_log("INFO", "Sync completed successfully")

    except Exception as e:
        logger.exception("Taxon sync failed")
        sync_run.mark_failed(str(e))
        sync_run.add_log("ERROR", f"Sync failed: {e}")


def _phase_fetch_ncbi(sync_run: TaxonSyncRun):
    """Phase 1: Fetch genomes from NCBI."""
    config = sync_run.config
    taxid = config.get("taxid", KINGDOMS.get(sync_run.kingdom, 33208))
    limit = config.get("limit", 0)
    skip_quality = config.get("skip_quality", False)
    skip_existing = config.get("skip_existing", True)  # Skip genomes already in DB
    quality = QUALITY_CRITERIA.get(sync_run.kingdom, QUALITY_CRITERIA["default"])

    sync_run.add_log("INFO", f"Fetching from NCBI taxid {taxid}")
    
    # Cache for taxonomy lookups
    taxonomy_cache: Dict[int, Dict] = {}
    
    # Pre-load existing genome accessions to skip them
    existing_accessions = set()
    if skip_existing:
        existing_accessions = set(
            NCBIGenome.objects.values_list("accession", flat=True)
        )
        sync_run.add_log("INFO", f"Skipping {len(existing_accessions)} existing genomes")
    
    new_count = 0  # Only counts genuinely NEW genomes created
    for genome_data in _fetch_ncbi_genomes_paged(taxid):
        sync_run.ncbi_total += 1
        
        # Refresh to check for cancellation
        if sync_run.ncbi_total % 50 == 0:
            sync_run.refresh_from_db(fields=["status"])
            if sync_run.status == "cancelled":
                return

        # Skip already synced genomes
        accession = genome_data.get("accession", "")
        if skip_existing and accession and accession in existing_accessions:
            sync_run.ncbi_skipped += 1
            continue

        # Apply filters
        if not _passes_refseq_filter(genome_data):
            sync_run.ncbi_filtered += 1
            continue
        if not _passes_level_filter(genome_data):
            sync_run.ncbi_filtered += 1
            continue
        if not skip_quality and not _passes_quality_filter(genome_data, quality):
            sync_run.ncbi_filtered += 1
            continue

        sync_run.ncbi_fetched += 1
        
        # Get taxonomy
        org = genome_data.get("organism", {}) or {}
        org_taxid = org.get("tax_id")
        taxonomy = _get_taxonomy(org_taxid, taxonomy_cache) if org_taxid else {}
        
        # Save to DB
        prev_genomes = sync_run.genomes_created
        _save_genome_to_db(genome_data, taxonomy, sync_run)
        
        # Only count toward limit if a NEW genome was actually created
        if sync_run.genomes_created > prev_genomes:
            new_count += 1
        
        if new_count % 50 == 0 and new_count > 0:
            sync_run.save(update_fields=[
                "ncbi_total", "ncbi_fetched", "ncbi_filtered",
                "ncbi_skipped", "taxa_created", "genomes_created",
            ])
            sync_run.add_log("INFO", f"NCBI progress: {new_count} new genomes ({sync_run.ncbi_skipped} already in DB)")
        
        # limit applies to NEW genomes only
        if limit and new_count >= limit:
            break

    # Final save
    sync_run.save(update_fields=[
        "ncbi_total", "ncbi_fetched", "ncbi_filtered",
        "ncbi_skipped", "taxa_created", "genomes_created",
    ])
    if sync_run.ncbi_skipped:
        sync_run.add_log("INFO", f"Skipped {sync_run.ncbi_skipped} genomes that already exist in DB")
    sync_run.add_log("INFO", f"NCBI phase complete: {new_count} new genomes ({sync_run.ncbi_fetched} processed, {sync_run.ncbi_skipped} already in DB)")


def _phase_match_col(sync_run: TaxonSyncRun):
    """Phase 2: Match NCBI taxa with COL."""
    client = ChecklistBankClient()
    
    # Get all taxa without active crosswalk
    taxa_to_match = Taxon.objects.exclude(
        crosswalks__is_active=True,
        crosswalks__external_taxon__system="col",
    ).distinct()
    
    sync_run.col_total = taxa_to_match.count()
    sync_run.save(update_fields=["col_total"])
    sync_run.add_log("INFO", f"Matching {sync_run.col_total} taxa with COL")

    for i, taxon in enumerate(taxa_to_match.iterator()):
        # Check for cancellation
        if i % 50 == 0:
            sync_run.refresh_from_db(fields=["status"])
            if sync_run.status == "cancelled":
                return

        try:
            canonical_name = canonicalize_scientific_name(taxon.scientific_name)
            result = client.match_nameusage(
                dataset=COL_DATASET,
                scientific_name=canonical_name,
                rank=taxon.rank if taxon.rank else None,
            )

            if result.matched and result.external_id:
                sync_run.col_matched += 1
                _create_col_crosswalk(taxon, result, sync_run)
            else:
                sync_run.col_unmatched += 1
                # Fallback: use taxonomy from a sibling species in the same genus
                from apps.taxonomy.utils import create_genus_fallback
                if create_genus_fallback(taxon, taxon.scientific_name):
                    sync_run.add_log("INFO", f"Genus fallback created for {taxon.scientific_name}")
                else:
                    # No sibling found either — mark as not_in_col
                    NCBIGenome.objects.filter(taxon=taxon).exclude(
                        col_match_status="manual"
                    ).update(col_match_status="not_in_col")

        except Exception as e:
            logger.warning(f"COL match failed for {taxon.scientific_name}: {e}")
            sync_run.col_unmatched += 1

        if (i + 1) % 50 == 0:
            sync_run.save(update_fields=[
                "col_matched", "col_unmatched",
                "external_taxa_created", "crosswalks_created",
            ])

    # Final save
    sync_run.save(update_fields=[
        "col_matched", "col_unmatched",
        "external_taxa_created", "crosswalks_created",
    ])
    sync_run.add_log("INFO", f"COL phase complete: {sync_run.col_matched} matched")

    # Cleanup: ensure all genomes with a matched crosswalk have external_taxon set
    unlinked_genomes = NCBIGenome.objects.filter(
        external_taxon__isnull=True,
        taxon__crosswalks__is_active=True,
        taxon__crosswalks__external_taxon__system="col",
    ).select_related("taxon").distinct()

    fixed_count = 0
    for genome in unlinked_genomes:
        active_cw = TaxonCrosswalk.objects.filter(
            ncbi_taxon=genome.taxon,
            is_active=True,
            external_taxon__system="col",
        ).select_related("external_taxon").first()
        if active_cw:
            # Genus validation before re-linking
            from apps.taxonomy.utils import genera_match
            ext = active_cw.external_taxon
            g_ok, _ = genera_match(genome.taxon.scientific_name, ext.name, ext.classification)
            if not g_ok:
                continue
            genome.external_taxon = ext
            genome.col_match_status = "matched"
            genome.save(update_fields=["external_taxon", "col_match_status"])
            fixed_count += 1

    if fixed_count:
        sync_run.add_log("INFO", f"Fixed {fixed_count} unlinked genomes with existing COL crosswalks")
    
    # CACHE INVALIDATION: Ensure new species appear in the tree
    from apps.taxonomy.utils import invalidate_all_tree_caches
    invalidate_all_tree_caches()
    sync_run.add_log("INFO", "Tree cache invalidated")


def _create_col_crosswalk(taxon: Taxon, result, sync_run: TaxonSyncRun):
    """Create ExternalTaxon and TaxonCrosswalk for a COL match."""
    from apps.taxonomy.utils import genera_match
    
    # GENUS VALIDATION: Prevent cross-genus mismatches
    col_classification = getattr(result, "classification", {}) or {}
    genus_ok, genus_reason = genera_match(
        ncbi_name=taxon.scientific_name,
        col_name=result.name or "",
        col_classification=col_classification
    )
    
    if not genus_ok:
        logger.warning(
            f"[GENUS_MISMATCH] taxid={taxon.taxid} '{taxon.scientific_name}' "
            f"≠ COL '{result.name}' reason={genus_reason}"
        )
        sync_run.add_log("WARNING", f"Genus mismatch: {taxon.scientific_name} ≠ {result.name}")
        # Fallback: use taxonomy from a sibling species in the same genus
        from apps.taxonomy.utils import create_genus_fallback
        if create_genus_fallback(taxon, taxon.scientific_name):
            sync_run.add_log("INFO", f"Genus fallback created for {taxon.scientific_name}")
        return  # Skip this COL match
    
    with transaction.atomic():
        # Get or create ExternalTaxon
        external, created = ExternalTaxon.objects.update_or_create(
            system="col",
            dataset_code=COL_DATASET,
            external_id=result.external_id,
            defaults={
                "name": result.name or taxon.scientific_name,
                "rank": result.rank or taxon.rank or "",
                "status": result.status or "unknown",
                "classification": result.classification,
                "classification_path": result.classification_path,
                "raw": result.raw,
            },
        )
        if created:
            sync_run.external_taxa_created += 1

        # Create crosswalk
        crosswalk, cw_created = TaxonCrosswalk.objects.update_or_create(
            ncbi_taxon=taxon,
            external_taxon=external,
            defaults={
                "score": 1.0 if result.matched else 0.0,
                "decision": "high",
                "method": "exact",
                "is_active": True,
                "evidence": {"source": "checklistbank", "matched": result.matched},
            },
        )
        if cw_created:
            sync_run.crosswalks_created += 1
        
        # Update col_match_status in NCBIGenome for this taxon
        if result.matched:
            NCBIGenome.objects.filter(taxon=taxon).update(
                col_match_status="matched",
                external_taxon=external,
            )


# ============================================================
# NCBI API Helpers
# ============================================================

def _fetch_ncbi_genomes_paged(taxid: int, page_size: int = 100) -> Iterator[dict]:
    """Fetch genomes from NCBI with pagination."""
    url = f"{NCBI_API}/genome/taxon/{taxid}/dataset_report"
    params = {"page_size": page_size, "filters.assembly_source": "refseq"}
    headers = {"Accept": "application/json"}
    page_token = None

    while True:
        if page_token:
            params["page_token"] = page_token

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"NCBI API error: {e}")
            break

        reports = data.get("reports", [])
        if not reports:
            break

        for report in reports:
            yield report

        page_token = data.get("next_page_token")
        if not page_token:
            break
        time.sleep(0.3)


def _get_taxonomy(taxid: int, cache: dict) -> Dict:
    """Get taxonomy from NCBI with caching."""
    if taxid in cache:
        return cache[taxid]

    result = {}
    try:
        # First call to get lineage
        url = f"{NCBI_API}/taxonomy/taxon/{taxid}"
        resp = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
        if resp.status_code != 200:
            return {}

        data = resp.json()
        nodes = data.get("taxonomy_nodes", [])
        if not nodes:
            return {}

        taxonomy = nodes[0].get("taxonomy", {})
        lineage_taxids = taxonomy.get("lineage", []) or []

        if not lineage_taxids:
            return {}

        # Batch query for lineage names
        batch_taxids = lineage_taxids[-20:] if len(lineage_taxids) > 20 else lineage_taxids
        taxids_str = ",".join(str(t) for t in batch_taxids)

        url2 = f"{NCBI_API}/taxonomy/taxon/{taxids_str}"
        resp2 = requests.get(url2, headers={"Accept": "application/json"}, timeout=30)
        if resp2.status_code != 200:
            return {}

        data2 = resp2.json()

        rank_map = {
            "KINGDOM": "kingdom",
            "PHYLUM": "phylum",
            "CLASS": "class",
            "ORDER": "order",
            "FAMILY": "family",
            "GENUS": "genus",
        }

        for node in data2.get("taxonomy_nodes", []):
            tax = node.get("taxonomy", {})
            rank = tax.get("rank", "")
            name = tax.get("organism_name", "")
            if rank in rank_map:
                result[rank_map[rank]] = name

        cache[taxid] = result

    except Exception as e:
        logger.warning(f"Taxonomy fetch error for {taxid}: {e}")

    return result


def _passes_refseq_filter(data: dict) -> bool:
    info = data.get("assembly_info", {}) or {}
    refcat = (info.get("refseq_category") or "").upper()
    return "REFERENCE" in refcat or "REPRESENTATIVE" in refcat


def _passes_level_filter(data: dict) -> bool:
    info = data.get("assembly_info", {}) or {}
    level = (info.get("assembly_level") or "").lower()
    return any(k in level for k in ["complete", "chromosome", "scaffold"])


def _passes_quality_filter(data: dict, quality: dict) -> bool:
    stats = data.get("assembly_stats", {}) or {}
    info = data.get("assembly_info", {}) or {}
    level = (info.get("assembly_level") or "").lower()

    coverage = _safe_float(stats.get("genome_coverage"), 0.0)
    scaffold_n50_kb = _safe_float(stats.get("scaffold_n50"), 0.0) / 1000.0

    if coverage == 0 and "complete" in level:
        coverage = 100.0

    return (
        coverage >= quality["min_coverage"]
        or scaffold_n50_kb >= quality["min_scaffold_n50_kb"]
    )


def _safe_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _save_genome_to_db(genome_data: dict, taxonomy: dict, sync_run: TaxonSyncRun):
    """Save genome and taxon to database."""
    org = genome_data.get("organism", {}) or {}
    info = genome_data.get("assembly_info", {}) or {}
    stats = genome_data.get("assembly_stats", {}) or {}
    ann = genome_data.get("annotation_info", {}) or {}

    taxid = org.get("tax_id")
    if not taxid:
        return

    # NCBI API uses organism_name, not sci_name
    scientific_name = org.get("organism_name", "")
    accession = genome_data.get("accession", "")

    if not accession:
        return

    with transaction.atomic():
        # Create or update taxon
        taxon, tax_created = Taxon.objects.update_or_create(
            taxid=taxid,
            defaults={
                "scientific_name": scientific_name,
                "rank": taxonomy.get("genus", "") and "species" or info.get("assembly_level", ""),
            },
        )
        if tax_created:
            sync_run.taxa_created += 1

        # Prepare valid fields for NCBIGenome
        genome_defaults = {
            "taxon": taxon,
            "organism_name": org.get("organism_name", ""),
            "refseq_category": info.get("refseq_category", ""),
            "genome_level": info.get("assembly_level", ""),
            "genome_coverage": _safe_float(stats.get("genome_coverage")),
            "contig_n50_kb": _safe_float(stats.get("contig_n50"), 0.0) / 1000.0 if stats.get("contig_n50") else None,
            "scaffold_n50_kb": _safe_float(stats.get("scaffold_n50"), 0.0) / 1000.0 if stats.get("scaffold_n50") else None,
            "scaffold_count": _safe_int(stats.get("number_of_scaffolds")),
            "genes": _safe_int(ann.get("stats", {}).get("gene_counts", {}).get("total")),
            "protein_coding": _safe_int(ann.get("stats", {}).get("gene_counts", {}).get("protein_coding")),
            "phylum": taxonomy.get("phylum", ""),
            "class_name": taxonomy.get("class", ""),
            "directory_name": info.get("assembly_name", ""),
            "raw": genome_data,
        }
        # Remove None values
        genome_defaults = {k: v for k, v in genome_defaults.items() if v is not None}

        # Truncate string values to respect CharField max_length
        for key, val in genome_defaults.items():
            if isinstance(val, str):
                try:
                    field = NCBIGenome._meta.get_field(key)
                    if hasattr(field, 'max_length') and field.max_length and len(val) > field.max_length:
                        genome_defaults[key] = val[:field.max_length]
                except Exception:
                    pass

        genome, gen_created = NCBIGenome.objects.update_or_create(
            accession=accession,
            defaults=genome_defaults,
        )
        if gen_created:
            sync_run.genomes_created += 1

        # If this taxon already has a COL crosswalk, link the genome to it
        if not genome.external_taxon:
            from apps.taxonomy.utils import genera_match
            active_cw = TaxonCrosswalk.objects.filter(
                ncbi_taxon=taxon,
                is_active=True,
                external_taxon__system="col",
            ).select_related("external_taxon").first()
            if active_cw:
                ext = active_cw.external_taxon
                g_ok, _ = genera_match(taxon.scientific_name, ext.name, ext.classification)
                if g_ok:
                    genome.external_taxon = ext
                    genome.col_match_status = "matched"
                    genome.save(update_fields=["external_taxon", "col_match_status"])


def _safe_int(val, default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


# ============================================================
# Discovery API Endpoints
# ============================================================

@require_POST
def api_start_discovery(request):
    """Start a manual species discovery scan. Admin only."""
    if not (request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)):
        return JsonResponse({"error": "Permission denied"}, status=403)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    kingdoms = data.get("kingdoms", ["metazoa", "fungi", "viridiplantae"])
    valid_kingdoms = list(KINGDOMS.keys())
    invalid = [k for k in kingdoms if k.lower() not in valid_kingdoms]
    if invalid:
        return JsonResponse({"error": f"Unknown kingdoms: {invalid}"}, status=400)

    from apps.taxonomy.models import DiscoveryRun

    # Check if already running
    running = DiscoveryRun.objects.filter(status="running").exists()
    if running:
        return JsonResponse({"success": False, "error": "A discovery is already in progress"}, status=409)

    # Try Celery first, fall back to threading
    use_celery = False
    task_id = None
    celery_enabled = getattr(settings, 'USE_CELERY_FOR_SYNC', False)

    if celery_enabled:
        try:
            from apps.taxonomy.ncbi.tasks import discover_new_species
            from celery import current_app

            inspector = current_app.control.inspect()
            active_workers = inspector.active()
            if active_workers:
                result = discover_new_species.delay(kingdoms=kingdoms, trigger="manual")
                task_id = result.id
                use_celery = True
            else:
                logger.warning("No Celery workers available for discovery, using threading")
        except Exception as e:
            logger.warning(f"Celery error ({e}), using threading fallback for discovery")

    if not use_celery:
        import threading
        thread = threading.Thread(
            target=_run_discovery,
            args=(kingdoms,),
            daemon=True,
        )
        thread.start()

    return JsonResponse({
        "success": True,
        "task_id": task_id,
        "backend": "celery" if use_celery else "threading",
        "message": f"Discovery started for: {', '.join(kingdoms)}",
    })


@require_GET
def api_discovery_list(request):
    """List recent discovery runs with their results."""
    from apps.taxonomy.models import DiscoveredSpecies, DiscoveryRun

    runs = DiscoveryRun.objects.all()[:10]
    data = []
    for run in runs:
        data.append({
            "id": run.pk,
            "status": run.status,
            "trigger": run.trigger,
            "kingdoms": run.kingdoms_searched,
            "total_scanned": run.total_scanned,
            "new_species_found": run.new_species_found,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "duration_seconds": run.duration_seconds,
        })
    return JsonResponse({"runs": data})


@require_GET
def api_discovered_species(request):
    """
    List discovered species (paginated).
    Query params: run_id, page, page_size, status (all|pending|imported|dismissed)
    """
    from apps.taxonomy.models import DiscoveredSpecies

    run_id = request.GET.get("run_id")
    page = int(request.GET.get("page", 1))
    page_size = int(request.GET.get("page_size", 20))
    status_filter = request.GET.get("status", "pending")

    qs = DiscoveredSpecies.objects.select_related("discovery_run")

    if run_id:
        qs = qs.filter(discovery_run_id=run_id)

    if status_filter == "pending":
        qs = qs.filter(is_imported=False, is_dismissed=False)
    elif status_filter == "imported":
        qs = qs.filter(is_imported=True)
    elif status_filter == "dismissed":
        qs = qs.filter(is_dismissed=True)
    # "all" = no filter

    total = qs.count()
    start = (page - 1) * page_size
    species_list = qs[start : start + page_size]

    results = []
    for sp in species_list:
        results.append({
            "id": sp.pk,
            "taxid": sp.taxid,
            "scientific_name": sp.scientific_name,
            "common_name": sp.common_name,
            "kingdom": sp.kingdom,
            "accession": sp.accession,
            "quality_score": sp.quality_score,
            "genome_level": sp.genome_level,
            "refseq_category": sp.refseq_category,
            "protein_coding": sp.protein_coding,
            "scaffold_n50_kb": sp.scaffold_n50_kb,
            "genome_coverage": sp.genome_coverage,
            "total_sequence_length": sp.total_sequence_length,
            "is_imported": sp.is_imported,
            "is_dismissed": sp.is_dismissed,
            "run_id": sp.discovery_run_id,
            "created_at": sp.created_at.isoformat() if sp.created_at else None,
        })

    return JsonResponse({
        "results": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size else 1,
    })


@require_POST
def api_import_discovered(request, species_id: int):
    """Import a discovered species into the main database. Admin only."""
    if not (request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)):
        return JsonResponse({"error": "Permission denied"}, status=403)

    from apps.taxonomy.models import DiscoveredSpecies, Taxon

    try:
        sp = DiscoveredSpecies.objects.get(pk=species_id)
    except DiscoveredSpecies.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)

    if sp.is_imported:
        return JsonResponse({"success": False, "error": "Already imported"})

    # Create Taxon + trigger genome fetch
    taxon, created = Taxon.objects.get_or_create(
        taxid=sp.taxid,
        defaults={
            "scientific_name": sp.scientific_name,
            "rank": "species",
        },
    )

    # Trigger single taxon sync to fetch full genome data
    celery_enabled = getattr(settings, 'USE_CELERY_FOR_SYNC', False)
    if celery_enabled:
        try:
            from apps.taxonomy.ncbi.tasks import sync_single_taxon
            sync_single_taxon.delay(taxid=sp.taxid, check_proteomes=True)
        except Exception:
            logger.warning(f"Celery unavailable for import sync of taxid {sp.taxid}")
    else:
        import threading
        thread = threading.Thread(
            target=_import_single_taxon,
            args=(sp.taxid,),
            daemon=True,
        )
        thread.start()

    sp.is_imported = True
    sp.save(update_fields=["is_imported"])

    return JsonResponse({
        "success": True,
        "taxid": sp.taxid,
        "scientific_name": sp.scientific_name,
        "created": created,
    })


@require_POST
def api_dismiss_discovered(request, species_id: int):
    """Dismiss a discovered species (not interesting). Admin only."""
    if not (request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)):
        return JsonResponse({"error": "Permission denied"}, status=403)

    from apps.taxonomy.models import DiscoveredSpecies

    try:
        sp = DiscoveredSpecies.objects.get(pk=species_id)
    except DiscoveredSpecies.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)

    sp.is_dismissed = True
    sp.save(update_fields=["is_dismissed"])

    return JsonResponse({"success": True, "taxid": sp.taxid})


@require_POST
def api_bulk_import_discovered(request):
    """Bulk import all pending discovered species: fetch GCF genomes + COL match. Admin only."""
    if not (request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)):
        return JsonResponse({"error": "Permission denied"}, status=403)

    from apps.taxonomy.models import DiscoveredSpecies

    pending = DiscoveredSpecies.objects.filter(is_imported=False, is_dismissed=False)
    count = pending.count()
    if count == 0:
        return JsonResponse({"success": False, "error": "No pending species to import"})

    import threading
    thread = threading.Thread(
        target=_run_bulk_import,
        daemon=True,
    )
    thread.start()

    return JsonResponse({
        "success": True,
        "message": f"Bulk import started for {count} species",
        "total": count,
    })


# ============================================================
# Discovery Threading Fallback
# ============================================================

def _import_single_taxon(taxid: int):
    """Thread target to sync a single taxon's genome data from NCBI."""
    from apps.taxonomy.models import NCBIGenome, Taxon
    try:
        taxon = Taxon.objects.get(taxid=taxid)
        NCBIGenome.fetch_and_save(taxon, check_proteomes=True)
    except Exception as e:
        logger.error(f"Error syncing taxid {taxid}: {e}")


def _run_bulk_import():
    """
    Background thread: bulk-import all pending DiscoveredSpecies.
    For each species:
      1. Create Taxon
      2. Fetch GCF genomes from NCBI (RefSeq only, same as main sync)
      3. Match with COL via ChecklistBank
      4. Mark as imported
    """
    import time as _time
    from apps.taxonomy.models import (
        DiscoveredSpecies, DiscoveryRun, Taxon,
        NCBIGenome, ExternalTaxon, TaxonCrosswalk,
    )

    client = ChecklistBankClient()
    taxonomy_cache: Dict[int, Dict] = {}
    pending = list(
        DiscoveredSpecies.objects.filter(is_imported=False, is_dismissed=False)
        .order_by("pk")
    )
    total = len(pending)
    logger.info(f"Bulk import: {total} species to process")

    imported = 0
    errors = 0

    for i, sp in enumerate(pending, 1):
        try:
            # 1. Fetch GCF genomes from NCBI (RefSeq only via _fetch_ncbi_genomes_paged)
            genome_saved = False
            taxon = None
            try:
                for genome_data in _fetch_ncbi_genomes_paged(sp.taxid, page_size=10):
                    accession = genome_data.get("accession", "")
                    if not accession or not accession.startswith("GCF_"):
                        continue
                    if not _passes_refseq_filter(genome_data):
                        continue
                    if not _passes_level_filter(genome_data):
                        continue

                    # Get taxonomy info for the genome
                    org = genome_data.get("organism", {}) or {}
                    org_taxid = org.get("tax_id", sp.taxid)
                    taxonomy = _get_taxonomy(org_taxid, taxonomy_cache) if org_taxid else {}

                    # Create taxon if not yet created
                    if taxon is None:
                        taxon, _ = Taxon.objects.get_or_create(
                            taxid=sp.taxid,
                            defaults={
                                "scientific_name": sp.scientific_name,
                                "rank": "species",
                            },
                        )

                    # Save genome using the same function as the main sync
                    # We use a lightweight wrapper since _save_genome_to_db needs a sync_run
                    with transaction.atomic():
                        genome_defaults = {
                            "taxon": taxon,
                            "organism_name": org.get("organism_name", sp.scientific_name),
                            "refseq_category": (genome_data.get("assembly_info", {}) or {}).get("refseq_category", ""),
                            "genome_level": (genome_data.get("assembly_info", {}) or {}).get("assembly_level", ""),
                            "genome_coverage": _safe_float((genome_data.get("assembly_stats", {}) or {}).get("genome_coverage")),
                            "contig_n50_kb": _safe_float((genome_data.get("assembly_stats", {}) or {}).get("contig_n50"), 0.0) / 1000.0 if (genome_data.get("assembly_stats", {}) or {}).get("contig_n50") else None,
                            "scaffold_n50_kb": _safe_float((genome_data.get("assembly_stats", {}) or {}).get("scaffold_n50"), 0.0) / 1000.0 if (genome_data.get("assembly_stats", {}) or {}).get("scaffold_n50") else None,
                            "scaffold_count": _safe_int((genome_data.get("assembly_stats", {}) or {}).get("number_of_scaffolds")),
                            "genes": _safe_int((genome_data.get("annotation_info", {}) or {}).get("stats", {}).get("gene_counts", {}).get("total")),
                            "protein_coding": _safe_int((genome_data.get("annotation_info", {}) or {}).get("stats", {}).get("gene_counts", {}).get("protein_coding")),
                            "phylum": taxonomy.get("phylum", ""),
                            "class_name": taxonomy.get("class", ""),
                            "directory_name": (genome_data.get("assembly_info", {}) or {}).get("assembly_name", ""),
                            "raw": genome_data,
                        }
                        genome_defaults = {k: v for k, v in genome_defaults.items() if v is not None}

                        # Truncate string fields
                        for key, val in genome_defaults.items():
                            if isinstance(val, str):
                                try:
                                    field = NCBIGenome._meta.get_field(key)
                                    if hasattr(field, 'max_length') and field.max_length and len(val) > field.max_length:
                                        genome_defaults[key] = val[:field.max_length]
                                except Exception:
                                    pass

                        NCBIGenome.objects.update_or_create(
                            accession=accession,
                            defaults=genome_defaults,
                        )
                    genome_saved = True
                    break  # Take only the first (best) GCF genome

            except Exception as e:
                logger.warning(f"Bulk import: genome fetch failed for {sp.scientific_name}: {e}")

            # Ensure taxon exists even if no genome was found
            if taxon is None:
                taxon, _ = Taxon.objects.get_or_create(
                    taxid=sp.taxid,
                    defaults={
                        "scientific_name": sp.scientific_name,
                        "rank": "species",
                    },
                )

            # 2. COL match
            try:
                canonical = canonicalize_scientific_name(sp.scientific_name)
                result = client.match_nameusage(
                    dataset=COL_DATASET,
                    scientific_name=canonical,
                    rank="species",
                )
                if result.matched and result.external_id:
                    with transaction.atomic():
                        external, _ = ExternalTaxon.objects.update_or_create(
                            system="col",
                            dataset_code=COL_DATASET,
                            external_id=result.external_id,
                            defaults={
                                "name": result.name or sp.scientific_name,
                                "rank": result.rank or "species",
                                "status": result.status or "unknown",
                                "classification": result.classification,
                                "classification_path": result.classification_path,
                                "raw": result.raw,
                            },
                        )
                        TaxonCrosswalk.objects.update_or_create(
                            ncbi_taxon=taxon,
                            external_taxon=external,
                            defaults={
                                "score": 1.0,
                                "decision": "high",
                                "method": "exact",
                                "is_active": True,
                                "evidence": {"source": "checklistbank", "matched": True},
                            },
                        )
                        NCBIGenome.objects.filter(taxon=taxon).update(
                            col_match_status="matched",
                            external_taxon=external,
                        )
                else:
                    from apps.taxonomy.utils import create_genus_fallback
                    if not create_genus_fallback(taxon, sp.scientific_name):
                        NCBIGenome.objects.filter(taxon=taxon).exclude(
                            col_match_status="manual"
                        ).update(col_match_status="not_in_col")
            except Exception as e:
                logger.warning(f"Bulk import: COL match failed for {sp.scientific_name}: {e}")

            # 3. Mark as imported
            sp.is_imported = True
            sp.save(update_fields=["is_imported"])
            imported += 1

            if i % 20 == 0:
                logger.info(f"Bulk import progress: {i}/{total} ({imported} imported, {errors} errors)")

        except Exception as e:
            errors += 1
            logger.error(f"Bulk import error for {sp.scientific_name} (taxid {sp.taxid}): {e}")

    # Invalidate tree cache
    from apps.taxonomy.utils import invalidate_all_tree_caches
    try:
        invalidate_all_tree_caches()
    except Exception:
        pass

    logger.info(f"Bulk import complete: {imported}/{total} imported, {errors} errors")


def _run_discovery(kingdoms: list[str]):
    """
    Run species discovery in a background thread (no Celery needed).
    Mirrors the logic in the discover_new_species Celery task.
    """
    from apps.taxonomy.models import DiscoveredSpecies, DiscoveryRun, Taxon

    run = DiscoveryRun.objects.create(
        trigger="manual",
        celery_task_id="",
        kingdoms_searched=kingdoms,
    )
    run.mark_started()
    run.add_log("INFO", f"Discovery started (thread) for kingdoms: {', '.join(kingdoms)}")

    try:
        existing_taxids = set(Taxon.objects.values_list("taxid", flat=True))
        already_discovered = set(
            DiscoveredSpecies.objects.filter(is_dismissed=False)
            .values_list("taxid", flat=True)
        )

        total_scanned = 0
        total_new = 0

        for kingdom in kingdoms:
            try:
                taxid = get_kingdom_taxid(kingdom)
                quality = get_quality_criteria(kingdom)
            except ValueError as e:
                run.add_log("WARN", f"Unknown kingdom {kingdom}: {e}")
                continue

            run.add_log("INFO", f"Scanning {kingdom} (taxid {taxid})...")
            kingdom_scanned = 0
            kingdom_new = 0

            for genome_data in fetch_ncbi_genomes(taxid):
                total_scanned += 1
                kingdom_scanned += 1

                if not GenomeFilters.passes_refseq(genome_data):
                    continue
                if not GenomeFilters.passes_level(genome_data):
                    continue
                if not GenomeFilters.passes_quality(genome_data, quality):
                    continue

                org = genome_data.get("organism", {}) or {}
                org_taxid = org.get("tax_id")
                if not org_taxid:
                    continue

                if org_taxid in existing_taxids or org_taxid in already_discovered:
                    continue

                info = genome_data.get("assembly_info", {}) or {}
                stats = genome_data.get("assembly_stats", {}) or {}
                ann = genome_data.get("annotation_info", {}) or {}
                gene_counts = (ann.get("stats", {}) or {}).get("gene_counts", {}) or {}

                coverage = _safe_float(stats.get("genome_coverage"))
                scaffold_n50 = _safe_float(stats.get("scaffold_n50"))
                scaffold_n50_kb = scaffold_n50 / 1000.0 if scaffold_n50 else None
                protein_coding = _safe_int(gene_counts.get("protein_coding"))
                total_seq_len = _safe_int(stats.get("total_sequence_length"))

                refseq_cat = info.get("refseq_category", "")
                genome_level = info.get("assembly_level", "")
                contig_n50 = _safe_float(stats.get("contig_n50"))
                contig_n50_kb = contig_n50 / 1000.0 if contig_n50 else None
                scaffold_count = _safe_int(stats.get("number_of_scaffolds")) or 0

                q_score = compute_quality_score(
                    refseq_cat, genome_level, coverage or 0,
                    scaffold_n50_kb, contig_n50_kb, scaffold_count,
                )

                if q_score < 0.4:
                    continue

                try:
                    DiscoveredSpecies.objects.create(
                        discovery_run=run,
                        taxid=org_taxid,
                        scientific_name=org.get("organism_name", "Unknown"),
                        common_name=org.get("common_name", ""),
                        kingdom=kingdom,
                        accession=genome_data.get("accession", ""),
                        quality_score=q_score,
                        genome_level=genome_level,
                        refseq_category=refseq_cat,
                        protein_coding=protein_coding,
                        scaffold_n50_kb=scaffold_n50_kb,
                        genome_coverage=coverage,
                        total_sequence_length=total_seq_len,
                    )
                    total_new += 1
                    kingdom_new += 1
                    already_discovered.add(org_taxid)
                except Exception as e:
                    logger.warning(f"Could not save discovery taxid {org_taxid}: {e}")

                if kingdom_scanned % 500 == 0:
                    run.add_log("INFO", f"{kingdom}: scanned {kingdom_scanned}, new {kingdom_new}")

            run.add_log("INFO", f"{kingdom} complete: scanned {kingdom_scanned}, new species {kingdom_new}")

        run.total_scanned = total_scanned
        run.new_species_found = total_new
        run.save(update_fields=["total_scanned", "new_species_found"])
        run.mark_completed()
        run.add_log("INFO", f"Discovery completed: {total_new} new species from {total_scanned} scanned")
        logger.info(f"Discovery #{run.pk} completed: {total_new} new species found")

    except Exception as e:
        logger.exception(f"Discovery #{run.pk} failed: {e}")
        run.mark_failed(str(e))
        run.add_log("ERROR", f"Discovery failed: {e}")


def _safe_float(val, default=None):
    """Safely convert to float."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=None):
    """Safely convert to int."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


# ============================================================
# NCBI Genome / Proteome / GBFF Download Proxy
# ============================================================

_VALID_TYPES = {"GENOME_FASTA", "PROT_FASTA", "GENOME_GBFF"}


@require_POST
def api_ncbi_download_proxy(request):
    """
    Stream a ZIP from the NCBI Datasets v2 download API back to the browser.

    Expected JSON body:
        accessions     – list of assembly accession strings  (required)
        include_types  – list of NCBI annotation types       (required)
        filename       – suggested ZIP filename              (optional)
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    accessions = data.get("accessions")
    include_types = data.get("include_types")
    filename = data.get("filename", "ncbi_download.zip")

    # ── Validation ──────────────────────────────────────────────
    if not accessions or not isinstance(accessions, list):
        return JsonResponse({"error": "accessions is required (list)."}, status=400)
    if not include_types or not isinstance(include_types, list):
        return JsonResponse({"error": "include_types is required (list)."}, status=400)

    # sanitise accessions (GCF_/GCA_ + digits + version)
    acc_re = re.compile(r"^GC[AF]_\d{9}\.\d+$")
    clean_accs = [a for a in accessions if isinstance(a, str) and acc_re.match(a)]
    if not clean_accs:
        return JsonResponse({"error": "No valid accessions."}, status=400)
    clean_accs = clean_accs[:500]  # safety cap

    clean_types = [t for t in include_types if t in _VALID_TYPES]
    if not clean_types:
        return JsonResponse({"error": "No valid include_types."}, status=400)

    # sanitise filename
    filename = re.sub(r"[^\w\-.]", "_", filename)
    if not filename.endswith(".zip"):
        filename += ".zip"

    # ── Call NCBI Datasets v2 ───────────────────────────────────
    ncbi_url = f"{NCBI_API}/genome/download"
    payload = {
        "accessions": clean_accs,
        "include_annotation_type": clean_types,
    }
    headers = {"Accept": "application/zip"}

    try:
        upstream = requests.post(
            ncbi_url,
            json=payload,
            headers=headers,
            stream=True,
            timeout=(15, 600),  # 15 s connect, 10 min read
        )
        upstream.raise_for_status()
    except requests.Timeout:
        return JsonResponse({"error": "NCBI API timed out."}, status=504)
    except requests.RequestException as exc:
        logger.warning("NCBI download proxy error: %s", exc)
        return JsonResponse({"error": f"NCBI API error: {exc}"}, status=502)

    # If client requests a single-folder repackage, rezip only matching files
    single_folder = bool(data.get("single_folder", True))

    # map NCBI types to simple keys and file extensions
    TYPE_TO_KEY = {
        "GENOME_GBFF": "gbff",
        "PROT_FASTA": "proteomes",
        "GENOME_FASTA": "genomes",
    }
    EXTENSIONS = {
        "gbff": (".gbff", ".gbff.gz"),
        "proteomes": (".faa", ".faa.gz", ".protein.faa"),
        "genomes": (".fna", ".fna.gz", ".fasta", ".fa", ".fa.gz"),
    }

    if single_folder:
        import tempfile
        import zipfile
        import os
        # save upstream zip to temp file to avoid loading into memory
        upstream_tmp = None
        out_tmp = None
        try:
            upstream_tmp = tempfile.NamedTemporaryFile(delete=False)
            for chunk in upstream.iter_content(chunk_size=524_288):
                upstream_tmp.write(chunk)
            upstream_tmp.flush()
            upstream_tmp.close()

            # Prepare output zip
            out_tmp = tempfile.NamedTemporaryFile(delete=False)
            out_tmp.close()

            with zipfile.ZipFile(upstream_tmp.name, 'r') as zin, zipfile.ZipFile(out_tmp.name, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
                # determine which keys client asked for
                wanted_keys = [TYPE_TO_KEY.get(t) for t in clean_types]
                wanted_keys = [k for k in wanted_keys if k]
                if not wanted_keys:
                    # fallback: stream original
                    raise RuntimeError("No wanted keys for repackage")

                # create a single top folder name based on requested types
                if len(wanted_keys) == 1:
                    top_folder = wanted_keys[0]
                else:
                    top_folder = "ncbi_data"

                for zi in zin.infolist():
                    name = zi.filename
                    # skip directories
                    if name.endswith('/'):
                        continue
                    lname = name.lower()
                    # if any extension matches the wanted keys, include
                    include = False
                    for k in wanted_keys:
                        for ext in EXTENSIONS.get(k, ()): 
                            if lname.endswith(ext):
                                include = True
                                break
                        if include:
                            break
                    if include:
                        # normalize filename to put under top_folder/
                        base = os.path.basename(name)
                        arcname = os.path.join(top_folder, base)
                        try:
                            with zin.open(zi) as src:
                                data_bytes = src.read()
                                zout.writestr(arcname, data_bytes)
                        except Exception:
                            # skip problematic entries
                            logger.debug("Skipping zip entry %s due to read error", name, exc_info=True)

            # stream out_tmp back to client
            def _stream_file(path):
                with open(path, 'rb') as fh:
                    while True:
                        chunk = fh.read(524_288)
                        if not chunk:
                            break
                        yield chunk

            response = StreamingHttpResponse(_stream_file(out_tmp.name), content_type="application/zip")
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            fs = os.path.getsize(out_tmp.name)
            response["Content-Length"] = str(fs)
            return response
        except Exception as exc:
            logger.debug("Repackage to single folder failed, streaming original zip: %s", exc, exc_info=True)
            # fallthrough to streaming original
        finally:
            try:
                if upstream_tmp is not None:
                    os.unlink(upstream_tmp.name)
            except Exception:
                pass
            try:
                if out_tmp is not None and os.path.exists(out_tmp.name):
                    os.unlink(out_tmp.name)
            except Exception:
                pass

    # ── Stream back to browser (original upstream zip) ─────────────────
    def _chunks():
        for chunk in upstream.iter_content(chunk_size=524_288):
            yield chunk

    response = StreamingHttpResponse(_chunks(), content_type="application/zip")
    cl = upstream.headers.get("Content-Length")
    if cl:
        response["Content-Length"] = cl
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
