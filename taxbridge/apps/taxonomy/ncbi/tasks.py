# apps/taxonomy/ncbi/tasks.py
"""
Celery tasks for NCBI synchronization.

Uses centralized ncbi_sync service for all sync logic.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

# Import from NCBI module service
from apps.taxonomy.ncbi.service import (
    KINGDOMS,
    QUALITY_CRITERIA,
    COL_DATASET,
    NCBISyncService,
    GenomeFilters,
    GenomeData,
    fetch_ncbi_genomes,
    fetch_taxonomy,
    save_genome_to_db,
    get_kingdom_taxid,
    get_quality_criteria,
)

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="apps.taxonomy.tasks.sync_ncbi_genomes",
    max_retries=3,
    default_retry_delay=60 * 5,  # 5 minutes between retries
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def sync_ncbi_genomes(
    self,
    sync_run_id: Optional[int] = None,
    taxids: Optional[list[int]] = None,
    rank_filter: Optional[str] = None,
    limit: int = 0,
    check_proteomes: bool = False,
    trigger: str = "scheduled",
) -> dict:
    """
    Main task for NCBI genome synchronization.
    
    Args:
        sync_run_id: Existing NCBISyncRun ID (if provided)
        taxids: Specific list of taxids to process
        rank_filter: Filter by rank (e.g., "species")
        limit: Taxa processing limit (0 = no limit)
        check_proteomes: Check proteomes
        trigger: Trigger type (scheduled/manual/webhook)
    
    Returns:
        Dict with sync statistics
    """
    from apps.taxonomy.models import NCBIGenome, NCBISyncRun, Taxon

    # Create or retrieve sync run record
    if sync_run_id:
        try:
            sync_run = NCBISyncRun.objects.get(pk=sync_run_id)
        except NCBISyncRun.DoesNotExist:
            sync_run = None
    else:
        sync_run = None

    if not sync_run:
        sync_run = NCBISyncRun.objects.create(
            trigger=trigger,
            celery_task_id=self.request.id or "",
            config={
                "taxids": taxids,
                "rank_filter": rank_filter,
                "limit": limit,
                "check_proteomes": check_proteomes,
            },
        )

    # Mark as started
    sync_run.celery_task_id = self.request.id or ""
    sync_run.mark_started()
    sync_run.add_log("INFO", "Sync started", task_id=self.request.id)

    try:
        # Build queryset
        qs = Taxon.objects.all().order_by("taxid")
        
        if taxids:
            qs = qs.filter(taxid__in=taxids)
        if rank_filter:
            qs = qs.filter(rank__iexact=rank_filter)
        if limit and limit > 0:
            qs = qs[:limit]

        total = qs.count()
        sync_run.total_taxa = total
        sync_run.save(update_fields=["total_taxa"])

        if total == 0:
            sync_run.add_log("WARN", "No taxa to process")
            sync_run.mark_completed()
            return {"status": "completed", "total": 0, "processed": 0}

        sync_run.add_log("INFO", f"Processing {total} taxa")

        # Process in batches
        batch_size = getattr(settings, "NCBI_SYNC_BATCH_SIZE", 100)
        processed = 0
        successful = 0
        failed = 0
        skipped = 0
        genomes_created = 0
        genomes_updated = 0

        for taxon in qs.iterator(chunk_size=batch_size):
            try:
                # Check if already has recent genomes (last 24h)
                recent_genome = NCBIGenome.objects.filter(
                    taxon=taxon,
                    updated_at__gte=timezone.now() - timedelta(hours=24),
                ).exists()

                if recent_genome and not taxids:  # If specific, always update
                    skipped += 1
                    processed += 1
                    continue

                # Get genomes
                count = NCBIGenome.fetch_and_save(taxon, check_proteomes=check_proteomes)
                
                if count > 0:
                    successful += 1
                    genomes_created += count  # Simplified, could be more precise
                else:
                    skipped += 1

                processed += 1

                # Update progress every 10 taxa
                if processed % 10 == 0:
                    sync_run.processed_taxa = processed
                    sync_run.successful_taxa = successful
                    sync_run.failed_taxa = failed
                    sync_run.skipped_taxa = skipped
                    sync_run.genomes_created = genomes_created
                    sync_run.save(update_fields=[
                        "processed_taxa", "successful_taxa", "failed_taxa",
                        "skipped_taxa", "genomes_created"
                    ])

                    # Progress log
                    if processed % 100 == 0:
                        sync_run.add_log(
                            "INFO",
                            f"Progress: {processed}/{total} ({sync_run.progress_percent}%)",
                        )

            except Exception as e:
                failed += 1
                processed += 1
                logger.error(f"Error processing taxid {taxon.taxid}: {e}")
                sync_run.add_log("ERROR", f"Error on taxid {taxon.taxid}", error=str(e))

        # Update final statistics
        sync_run.processed_taxa = processed
        sync_run.successful_taxa = successful
        sync_run.failed_taxa = failed
        sync_run.skipped_taxa = skipped
        sync_run.genomes_created = genomes_created
        sync_run.genomes_updated = genomes_updated
        sync_run.mark_completed()

        sync_run.add_log(
            "INFO",
            "Sync completed",
            total=total,
            processed=processed,
            successful=successful,
            failed=failed,
            skipped=skipped,
        )

        return {
            "status": "completed",
            "sync_run_id": sync_run.pk,
            "total": total,
            "processed": processed,
            "successful": successful,
            "failed": failed,
            "skipped": skipped,
            "genomes_created": genomes_created,
        }

    except Exception as e:
        logger.exception(f"Critical error in sync: {e}")
        sync_run.mark_failed(str(e))
        sync_run.add_log("ERROR", "Critical error", error=str(e))
        raise  # Re-raise so Celery can retry


@shared_task(
    name="apps.taxonomy.tasks.sync_single_taxon",
    bind=True,
    max_retries=3,
)
def sync_single_taxon(self, taxid: int, check_proteomes: bool = True) -> dict:
    """
    Sync a single taxon on demand.
    Useful for one-off updates from the UI.
    """
    from apps.taxonomy.models import NCBIGenome, Taxon

    try:
        taxon = Taxon.objects.get(taxid=taxid)
    except Taxon.DoesNotExist:
        return {"status": "error", "error": f"Taxid {taxid} not found"}

    try:
        count = NCBIGenome.fetch_and_save(taxon, check_proteomes=check_proteomes)
        return {
            "status": "completed",
            "taxid": taxid,
            "genomes_saved": count,
        }
    except Exception as e:
        logger.error(f"Error syncing taxid {taxid}: {e}")
        return {
            "status": "error",
            "taxid": taxid,
            "error": str(e),
        }


@shared_task(name="apps.taxonomy.tasks.cleanup_old_sync_runs")
def cleanup_old_sync_runs(days: int = 30) -> dict:
    """
    Clean up old sync run records.
    Keeps only the last N days.
    """
    from apps.taxonomy.models import NCBISyncRun

    cutoff = timezone.now() - timedelta(days=days)
    
    # Keep at least the last 10 completed
    recent_ids = list(
        NCBISyncRun.objects.filter(status="completed")
        .order_by("-created_at")[:10]
        .values_list("id", flat=True)
    )

    deleted_count, _ = (
        NCBISyncRun.objects.filter(created_at__lt=cutoff)
        .exclude(pk__in=recent_ids)
        .delete()
    )

    logger.info(f"Cleaned {deleted_count} old sync run records")
    return {"deleted": deleted_count}


@shared_task(name="apps.taxonomy.tasks.get_sync_status")
def get_sync_status(sync_run_id: int) -> dict:
    """
    Get the current status of a sync run.
    """
    from apps.taxonomy.models import NCBISyncRun

    try:
        run = NCBISyncRun.objects.get(pk=sync_run_id)
        return {
            "id": run.pk,
            "status": run.status,
            "progress": run.progress_percent,
            "total_taxa": run.total_taxa,
            "processed_taxa": run.processed_taxa,
            "successful_taxa": run.successful_taxa,
            "failed_taxa": run.failed_taxa,
            "skipped_taxa": run.skipped_taxa,
            "genomes_created": run.genomes_created,
            "duration_seconds": run.duration_seconds,
            "error_message": run.error_message,
        }
    except NCBISyncRun.DoesNotExist:
        return {"error": "Sync run not found"}


# ============================================================
# Taxon Sync Task (NCBI + COL)
# ============================================================

@shared_task(
    bind=True,
    name="apps.taxonomy.tasks.sync_taxon_with_col",
    max_retries=2,
    default_retry_delay=60 * 2,
    autoretry_for=(Exception,),
    retry_backoff=True,
    time_limit=3600 * 6,  # 6 hours max
    soft_time_limit=3600 * 5,  # 5 hours soft limit
)
def sync_taxon_with_col(
    self,
    sync_run_id: int,
) -> dict:
    """
    Celery task for Taxon Sync: downloads from NCBI and matches with COL.
    
    Uses centralized NCBISyncService for all sync operations.
    
    Args:
        sync_run_id: TaxonSyncRun ID to track progress
    
    Returns:
        Dict with sync statistics
    """
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

    try:
        sync_run = TaxonSyncRun.objects.get(pk=sync_run_id)
    except TaxonSyncRun.DoesNotExist:
        logger.error(f"TaxonSyncRun {sync_run_id} not found")
        return {"error": "Sync run not found"}

    # Update with celery task id
    sync_run.celery_task_id = self.request.id or ""
    sync_run.save(update_fields=["celery_task_id"])

    try:
        sync_run.mark_started()
        sync_run.add_log("INFO", f"Started taxon sync for {sync_run.kingdom}")
        logger.info(f"Starting TaxonSync #{sync_run_id} for {sync_run.kingdom}")

        # ========== PHASE 1: Fetch from NCBI (using centralized service) ==========
        config = sync_run.config
        kingdom = sync_run.kingdom
        taxid = config.get("taxid") or get_kingdom_taxid(kingdom)
        limit = config.get("limit", 0)
        skip_quality = config.get("skip_quality", False)
        quality = get_quality_criteria(kingdom)

        sync_run.add_log("INFO", f"Fetching from NCBI taxid {taxid}")
        taxonomy_cache = {}
        
        count = 0
        for genome_data in fetch_ncbi_genomes(taxid):
            sync_run.ncbi_total += 1
            
            # Check for cancellation periodically
            if sync_run.ncbi_total % 100 == 0:
                sync_run.refresh_from_db(fields=["status"])
                if sync_run.status == "cancelled":
                    logger.info(f"TaxonSync #{sync_run_id} cancelled")
                    return {"status": "cancelled"}

            # Apply filters using centralized GenomeFilters
            if not GenomeFilters.passes_refseq(genome_data):
                sync_run.ncbi_filtered += 1
                continue
            if not GenomeFilters.passes_level(genome_data):
                sync_run.ncbi_filtered += 1
                continue
            if not skip_quality and not GenomeFilters.passes_quality(genome_data, quality):
                sync_run.ncbi_filtered += 1
                continue

            sync_run.ncbi_fetched += 1
            
            # Get taxonomy using centralized function
            org = genome_data.get("organism", {}) or {}
            org_taxid = org.get("tax_id")
            taxonomy = fetch_taxonomy(org_taxid, taxonomy_cache) if org_taxid else {}
            
            # Parse genome data and save to DB
            genome = GenomeData.from_ncbi_report(genome_data, taxonomy)
            tax_created, gen_created = save_genome_to_db(genome, sync_run)
            
            if tax_created:
                sync_run.taxa_created += 1
            if gen_created:
                sync_run.genomes_created += 1
            
            count += 1
            if count % 50 == 0:
                sync_run.save(update_fields=[
                    "ncbi_total", "ncbi_fetched", "ncbi_filtered",
                    "taxa_created", "genomes_created",
                ])
                sync_run.add_log("INFO", f"NCBI progress: {count} valid genomes")
                logger.info(f"TaxonSync #{sync_run_id}: {count} genomes fetched")
            
            if limit and count >= limit:
                break

        sync_run.save(update_fields=[
            "ncbi_total", "ncbi_fetched", "ncbi_filtered",
            "taxa_created", "genomes_created",
        ])
        sync_run.add_log("INFO", f"NCBI phase complete: {sync_run.ncbi_fetched} genomes")

        # ========== PHASE 2: Match with COL ==========
        sync_run.mark_col_phase()
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
                    return {"status": "cancelled"}

            try:
                canonical_name = canonicalize_scientific_name(taxon.scientific_name)
                result = client.match_nameusage(
                    dataset=COL_DATASET,
                    scientific_name=canonical_name,
                    rank=taxon.rank if taxon.rank else None,
                )

                if result.matched and result.external_id:
                    sync_run.col_matched += 1
                    _create_col_crosswalk_task(taxon, result, sync_run, COL_DATASET)
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
                logger.info(f"TaxonSync #{sync_run_id}: COL {i+1}/{sync_run.col_total}")

        sync_run.save(update_fields=[
            "col_matched", "col_unmatched",
            "external_taxa_created", "crosswalks_created",
        ])
        sync_run.add_log("INFO", f"COL phase complete: {sync_run.col_matched} matched")

        # Mark as completed
        sync_run.mark_completed()
        sync_run.add_log("INFO", "Sync completed successfully")
        logger.info(f"TaxonSync #{sync_run_id} completed successfully")

        return {
            "status": "completed",
            "ncbi_fetched": sync_run.ncbi_fetched,
            "taxa_created": sync_run.taxa_created,
            "col_matched": sync_run.col_matched,
            "crosswalks_created": sync_run.crosswalks_created,
        }

    except Exception as e:
        logger.exception(f"TaxonSync #{sync_run_id} failed")
        sync_run.mark_failed(str(e))
        sync_run.add_log("ERROR", f"Sync failed: {e}")
        raise


# ============================================================
# Helper function for COL crosswalk (kept for COL matching phase)
# ============================================================

def _create_col_crosswalk_task(taxon, result, sync_run, col_dataset: str):
    """Create ExternalTaxon and TaxonCrosswalk for a COL match."""
    from apps.taxonomy.models import ExternalTaxon, TaxonCrosswalk
    
    with transaction.atomic():
        external, created = ExternalTaxon.objects.update_or_create(
            system="col",
            dataset_code=col_dataset,
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
