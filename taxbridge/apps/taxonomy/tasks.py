# apps/taxonomy/tasks.py
"""
Tareas Celery para sincronización con NCBI.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="apps.taxonomy.tasks.sync_ncbi_genomes",
    max_retries=3,
    default_retry_delay=60 * 5,  # 5 minutos entre reintentos
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
    Tarea principal de sincronización de genomas NCBI.
    
    Args:
        sync_run_id: ID de NCBISyncRun existente (si se proporciona)
        taxids: Lista específica de taxids a procesar
        rank_filter: Filtrar por rank (ej: "species")
        limit: Límite de taxa a procesar (0 = sin límite)
        check_proteomes: Verificar proteomas
        trigger: Tipo de disparo (scheduled/manual/webhook)
    
    Returns:
        Dict con estadísticas de la sincronización
    """
    from apps.taxonomy.models import NCBIGenome, NCBISyncRun, Taxon
    from apps.taxonomy.services.ncbi_api import fetch_and_save_genomes

    # Crear o recuperar el registro de sincronización
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

    # Marcar como iniciado
    sync_run.celery_task_id = self.request.id or ""
    sync_run.mark_started()
    sync_run.add_log("INFO", "Sincronización iniciada", task_id=self.request.id)

    try:
        # Construir queryset
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
            sync_run.add_log("WARN", "No hay taxa para procesar")
            sync_run.mark_completed()
            return {"status": "completed", "total": 0, "processed": 0}

        sync_run.add_log("INFO", f"Procesando {total} taxa")

        # Procesar en batches
        batch_size = getattr(settings, "NCBI_SYNC_BATCH_SIZE", 100)
        processed = 0
        successful = 0
        failed = 0
        skipped = 0
        genomes_created = 0
        genomes_updated = 0

        for taxon in qs.iterator(chunk_size=batch_size):
            try:
                # Verificar si ya tiene genomas recientes (últimas 24h)
                recent_genome = NCBIGenome.objects.filter(
                    taxon=taxon,
                    updated_at__gte=timezone.now() - timedelta(hours=24),
                ).exists()

                if recent_genome and not taxids:  # Si es específico, siempre actualizar
                    skipped += 1
                    processed += 1
                    continue

                # Obtener genomas
                count = fetch_and_save_genomes(taxon, check_proteomes=check_proteomes)
                
                if count > 0:
                    successful += 1
                    genomes_created += count  # Simplificado, podría ser más preciso
                else:
                    skipped += 1

                processed += 1

                # Actualizar progreso cada 10 taxa
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

                    # Log de progreso
                    if processed % 100 == 0:
                        sync_run.add_log(
                            "INFO",
                            f"Progreso: {processed}/{total} ({sync_run.progress_percent}%)",
                        )

            except Exception as e:
                failed += 1
                processed += 1
                logger.error(f"Error procesando taxid {taxon.taxid}: {e}")
                sync_run.add_log("ERROR", f"Error en taxid {taxon.taxid}", error=str(e))

        # Actualizar estadísticas finales
        sync_run.processed_taxa = processed
        sync_run.successful_taxa = successful
        sync_run.failed_taxa = failed
        sync_run.skipped_taxa = skipped
        sync_run.genomes_created = genomes_created
        sync_run.genomes_updated = genomes_updated
        sync_run.mark_completed()

        sync_run.add_log(
            "INFO",
            "Sincronización completada",
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
        logger.exception(f"Error crítico en sincronización: {e}")
        sync_run.mark_failed(str(e))
        sync_run.add_log("ERROR", "Error crítico", error=str(e))
        raise  # Re-raise para que Celery pueda reintentar


@shared_task(
    name="apps.taxonomy.tasks.sync_single_taxon",
    bind=True,
    max_retries=3,
)
def sync_single_taxon(self, taxid: int, check_proteomes: bool = True) -> dict:
    """
    Sincroniza un solo taxón bajo demanda.
    Útil para actualizaciones puntuales desde la UI.
    """
    from apps.taxonomy.models import Taxon
    from apps.taxonomy.services.ncbi_api import fetch_and_save_genomes

    try:
        taxon = Taxon.objects.get(taxid=taxid)
    except Taxon.DoesNotExist:
        return {"status": "error", "error": f"Taxid {taxid} no encontrado"}

    try:
        count = fetch_and_save_genomes(taxon, check_proteomes=check_proteomes)
        return {
            "status": "completed",
            "taxid": taxid,
            "genomes_saved": count,
        }
    except Exception as e:
        logger.error(f"Error sincronizando taxid {taxid}: {e}")
        return {
            "status": "error",
            "taxid": taxid,
            "error": str(e),
        }


@shared_task(name="apps.taxonomy.tasks.cleanup_old_sync_runs")
def cleanup_old_sync_runs(days: int = 30) -> dict:
    """
    Limpia registros de sincronización antiguos.
    Mantiene solo los últimos N días.
    """
    from apps.taxonomy.models import NCBISyncRun

    cutoff = timezone.now() - timedelta(days=days)
    
    # Mantener al menos los últimos 10 completados
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

    logger.info(f"Limpiados {deleted_count} registros de sincronización antiguos")
    return {"deleted": deleted_count}


@shared_task(name="apps.taxonomy.tasks.get_sync_status")
def get_sync_status(sync_run_id: int) -> dict:
    """
    Obtiene el estado actual de una sincronización.
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
