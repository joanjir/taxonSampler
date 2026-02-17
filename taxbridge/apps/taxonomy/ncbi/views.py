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
from typing import Dict, Iterator, Optional

import requests

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
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
    get_kingdom_taxid,
    get_quality_criteria,
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

    stats = {
        "total_taxa": Taxon.objects.count(),
        "total_genomes": NCBIGenome.objects.count(),
        "external_taxa": ExternalTaxon.objects.filter(system="col").count(),
        "crosswalks": TaxonCrosswalk.objects.filter(is_active=True).count(),
        "matched_taxa": (
            Taxon.objects.filter(
                crosswalks__is_active=True,
                crosswalks__external_taxon__isnull=False,
            )
            .distinct()
            .count()
        ),
        "total_syncs": TaxonSyncRun.objects.count(),
        "successful_syncs": TaxonSyncRun.objects.filter(status="completed").count(),
    }
    
    # Calculate unlinked taxa
    stats["unlinked_taxa"] = stats["total_taxa"] - stats["matched_taxa"]
    
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

@csrf_exempt
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
    if kingdom not in KINGDOMS:
        return JsonResponse({
            "error": f"Unknown kingdom: {kingdom}",
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
            "taxid": KINGDOMS[kingdom],
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


@csrf_exempt
@require_POST
def api_cancel_taxon_sync(request, sync_id: int):
    """Cancel a running sync. Admin only."""
    if not (request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)):
        return JsonResponse({"error": "Permission denied"}, status=403)
    try:
        run = TaxonSyncRun.objects.get(pk=sync_id)
    except TaxonSyncRun.DoesNotExist:
        return JsonResponse({"error": "Sync not found"}, status=404)

    if not run.is_running:
        return JsonResponse({"error": "Sync is not running"}, status=400)

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
    skipped_existing = 0
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
            skipped_existing += 1
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
                "taxa_created", "genomes_created",
            ])
            sync_run.add_log("INFO", f"NCBI progress: {new_count} new genomes (skipped {skipped_existing} existing)")
        
        # limit applies to NEW genomes only
        if limit and new_count >= limit:
            break

    # Final save
    sync_run.save(update_fields=[
        "ncbi_total", "ncbi_fetched", "ncbi_filtered",
        "taxa_created", "genomes_created",
    ])
    sync_run.add_log("INFO", f"Skipped {skipped_existing} genomes that already exist in DB")
    sync_run.add_log("INFO", f"NCBI phase complete: {new_count} new genomes ({sync_run.ncbi_fetched} processed, {skipped_existing} skipped)")


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
            genome.external_taxon = active_cw.external_taxon
            genome.col_match_status = "matched"
            genome.save(update_fields=["external_taxon", "col_match_status"])
            fixed_count += 1

    if fixed_count:
        sync_run.add_log("INFO", f"Fixed {fixed_count} unlinked genomes with existing COL crosswalks")


def _create_col_crosswalk(taxon: Taxon, result, sync_run: TaxonSyncRun):
    """Create ExternalTaxon and TaxonCrosswalk for a COL match."""
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
                "method": "exact" if result.matched else "no_match",
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
        else:
            NCBIGenome.objects.filter(taxon=taxon).update(
                col_match_status="no_match",
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
            active_cw = TaxonCrosswalk.objects.filter(
                ncbi_taxon=taxon,
                is_active=True,
                external_taxon__system="col",
            ).select_related("external_taxon").first()
            if active_cw:
                genome.external_taxon = active_cw.external_taxon
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

@csrf_exempt
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

    from apps.taxonomy.ncbi.tasks import discover_new_species
    from apps.taxonomy.models import DiscoveryRun

    # Check if already running
    running = DiscoveryRun.objects.filter(status="running").exists()
    if running:
        return JsonResponse({"success": False, "error": "A discovery is already in progress"}, status=409)

    result = discover_new_species.delay(kingdoms=kingdoms, trigger="manual")
    return JsonResponse({
        "success": True,
        "task_id": result.id,
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


@csrf_exempt
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
    from apps.taxonomy.ncbi.tasks import sync_single_taxon
    sync_single_taxon.delay(taxid=sp.taxid, check_proteomes=True)

    sp.is_imported = True
    sp.save(update_fields=["is_imported"])

    return JsonResponse({
        "success": True,
        "taxid": sp.taxid,
        "scientific_name": sp.scientific_name,
        "created": created,
    })


@csrf_exempt
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
