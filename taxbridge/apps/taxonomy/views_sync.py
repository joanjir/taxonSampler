# apps/taxonomy/views_sync.py
"""
Vistas para el dashboard de sincronización NCBI.
"""
from __future__ import annotations

import logging

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.taxonomy.models import NCBIGenome, NCBISyncRun, Taxon

logger = logging.getLogger(__name__)


# ============================================================
# Dashboard View
# ============================================================

@require_GET
def sync_dashboard(request):
    """
    Página principal del dashboard de sincronización NCBI.
    """
    # Últimas sincronizaciones
    recent_syncs = NCBISyncRun.objects.all()[:10]
    
    # Sincronización en curso
    running_sync = NCBISyncRun.objects.filter(status="running").first()
    
    # Estadísticas generales
    stats = {
        "total_taxa": Taxon.objects.count(),
        "taxa_with_genomes": Taxon.objects.filter(genomes__isnull=False).distinct().count(),
        "total_genomes": NCBIGenome.objects.count(),
        "high_quality_genomes": NCBIGenome.objects.filter(quality_score__gte=0.8).count(),
        "with_proteome": NCBIGenome.objects.filter(has_proteome=True).count(),
        "total_syncs": NCBISyncRun.objects.count(),
        "successful_syncs": NCBISyncRun.objects.filter(status="completed").count(),
    }
    
    context = {
        "recent_syncs": recent_syncs,
        "running_sync": running_sync,
        "stats": stats,
    }
    
    return render(request, "taxonomy/pages/sync/dashboard.html", context)


@require_GET
def sync_detail(request, sync_id: int):
    """
    Detalle de una sincronización específica.
    """
    sync_run = get_object_or_404(NCBISyncRun, pk=sync_id)
    
    context = {
        "sync_run": sync_run,
    }
    
    return render(request, "taxonomy/pages/sync/detail.html", context)


# ============================================================
# API Endpoints
# ============================================================

@require_POST
def api_start_sync(request):
    """
    Inicia una nueva sincronización manual.
    
    POST /api/v1/taxonomy/sync/start/
    Body (JSON opcional):
        {
            "taxids": [9606, 7227],  // opcional
            "rank": "species",       // opcional
            "limit": 100,            // opcional
            "check_proteomes": false // opcional
        }
    """
    import json
    from apps.taxonomy.tasks import sync_ncbi_genomes
    
    try:
        if request.body:
            data = json.loads(request.body)
        else:
            data = {}
    except json.JSONDecodeError:
        data = {}
    
    # Verificar si ya hay una sincronización en curso
    running = NCBISyncRun.objects.filter(status="running").exists()
    if running:
        return JsonResponse({
            "success": False,
            "error": "Ya hay una sincronización en curso",
        }, status=409)
    
    # Crear registro de sync
    sync_run = NCBISyncRun.objects.create(
        trigger="manual",
        config=data,
    )
    
    # Lanzar tarea
    task = sync_ncbi_genomes.delay(
        sync_run_id=sync_run.pk,
        taxids=data.get("taxids"),
        rank_filter=data.get("rank"),
        limit=data.get("limit", 0),
        check_proteomes=data.get("check_proteomes", False),
        trigger="manual",
    )
    
    # Actualizar con task_id
    sync_run.celery_task_id = task.id
    sync_run.save(update_fields=["celery_task_id"])
    
    return JsonResponse({
        "success": True,
        "sync_run_id": sync_run.pk,
        "task_id": task.id,
    })


@require_GET
def api_sync_status(request, sync_id: int):
    """
    Obtiene el estado de una sincronización.
    
    GET /api/v1/taxonomy/sync/<id>/status/
    """
    try:
        run = NCBISyncRun.objects.get(pk=sync_id)
    except NCBISyncRun.DoesNotExist:
        return JsonResponse({"error": "Sync not found"}, status=404)
    
    return JsonResponse({
        "id": run.pk,
        "status": run.status,
        "trigger": run.trigger,
        "progress_percent": run.progress_percent,
        "total_taxa": run.total_taxa,
        "processed_taxa": run.processed_taxa,
        "successful_taxa": run.successful_taxa,
        "failed_taxa": run.failed_taxa,
        "skipped_taxa": run.skipped_taxa,
        "genomes_created": run.genomes_created,
        "genomes_updated": run.genomes_updated,
        "duration_seconds": run.duration_seconds,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    })


@require_GET
def api_sync_log(request, sync_id: int):
    """
    Obtiene el log de una sincronización.
    
    GET /api/v1/taxonomy/sync/<id>/log/
    """
    try:
        run = NCBISyncRun.objects.get(pk=sync_id)
    except NCBISyncRun.DoesNotExist:
        return JsonResponse({"error": "Sync not found"}, status=404)
    
    return JsonResponse({
        "id": run.pk,
        "log": run.log,
    })


@require_POST
def api_cancel_sync(request, sync_id: int):
    """
    Cancela una sincronización en curso.
    
    POST /api/v1/taxonomy/sync/<id>/cancel/
    """
    from celery.result import AsyncResult
    
    try:
        run = NCBISyncRun.objects.get(pk=sync_id)
    except NCBISyncRun.DoesNotExist:
        return JsonResponse({"error": "Sync not found"}, status=404)
    
    if run.status != "running":
        return JsonResponse({
            "success": False,
            "error": f"No se puede cancelar: estado actual es '{run.status}'",
        }, status=400)
    
    # Revocar tarea Celery
    if run.celery_task_id:
        AsyncResult(run.celery_task_id).revoke(terminate=True)
    
    run.status = "cancelled"
    from django.utils import timezone
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "finished_at"])
    run.add_log("WARN", "Sincronización cancelada manualmente")
    
    return JsonResponse({
        "success": True,
        "message": "Sincronización cancelada",
    })


@require_GET
def api_sync_list(request):
    """
    Lista las sincronizaciones recientes.
    
    GET /api/v1/taxonomy/sync/list/
    Query params:
        - limit: número de resultados (default: 20)
        - status: filtrar por estado
    """
    limit = int(request.GET.get("limit", 20))
    status = request.GET.get("status")
    
    qs = NCBISyncRun.objects.all()
    if status:
        qs = qs.filter(status=status)
    
    syncs = qs[:limit]
    
    return JsonResponse({
        "syncs": [
            {
                "id": s.pk,
                "status": s.status,
                "trigger": s.trigger,
                "progress_percent": s.progress_percent,
                "total_taxa": s.total_taxa,
                "processed_taxa": s.processed_taxa,
                "genomes_created": s.genomes_created,
                "duration_seconds": s.duration_seconds,
                "created_at": s.created_at.isoformat(),
            }
            for s in syncs
        ]
    })


@require_GET
def api_sync_stats(request):
    """
    Estadísticas generales de sincronización.
    
    GET /api/v1/taxonomy/sync/stats/
    """
    from django.db.models import Avg, Sum
    
    # Última sincronización exitosa
    last_completed = NCBISyncRun.objects.filter(status="completed").first()
    
    # Estadísticas agregadas
    completed_stats = NCBISyncRun.objects.filter(status="completed").aggregate(
        avg_duration=Avg("processed_taxa"),  # Placeholder, idealmente usar F()
        total_genomes=Sum("genomes_created"),
    )
    
    return JsonResponse({
        "total_taxa": Taxon.objects.count(),
        "taxa_with_genomes": Taxon.objects.filter(genomes__isnull=False).distinct().count(),
        "total_genomes": NCBIGenome.objects.count(),
        "high_quality_genomes": NCBIGenome.objects.filter(quality_score__gte=0.8).count(),
        "with_proteome": NCBIGenome.objects.filter(has_proteome=True).count(),
        "total_syncs": NCBISyncRun.objects.count(),
        "completed_syncs": NCBISyncRun.objects.filter(status="completed").count(),
        "failed_syncs": NCBISyncRun.objects.filter(status="failed").count(),
        "last_sync": {
            "id": last_completed.pk,
            "finished_at": last_completed.finished_at.isoformat() if last_completed and last_completed.finished_at else None,
        } if last_completed else None,
        "running_sync": NCBISyncRun.objects.filter(status="running").exists(),
    })


@require_POST
def api_sync_taxon(request, taxid: int):
    """
    Sincroniza un taxón específico bajo demanda.
    
    POST /api/v1/taxonomy/sync/taxon/<taxid>/
    """
    from apps.taxonomy.tasks import sync_single_taxon
    
    try:
        taxon = Taxon.objects.get(taxid=taxid)
    except Taxon.DoesNotExist:
        return JsonResponse({"error": f"Taxid {taxid} no encontrado"}, status=404)
    
    # Lanzar tarea
    task = sync_single_taxon.delay(taxid=taxid, check_proteomes=True)
    
    return JsonResponse({
        "success": True,
        "taxid": taxid,
        "task_id": task.id,
        "message": f"Sincronización iniciada para {taxon.scientific_name}",
    })
