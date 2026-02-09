# config/celery.py
"""
Configuración de Celery para TaxaBridge.
Para iniciar el worker:
    celery -A config worker -l info

Para iniciar el scheduler (beat):
    celery -A config beat -l info

O ambos en uno:
    celery -A config worker -B -l info
"""
from __future__ import absolute_import

import os

from celery import Celery
from celery.schedules import crontab

# Configurar settings module por defecto
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("taxbridge")

# Usar string para evitar problemas de serialización
app.config_from_object("django.conf:settings", namespace="CELERY")

# Autodiscover tasks en todas las apps instaladas
app.autodiscover_tasks()

# ======================
# Tareas programadas
# ======================
app.conf.beat_schedule = {
    # Sincronizar NCBI genomas diariamente a las 3:00 AM
    "sync-ncbi-genomes-daily": {
        "task": "apps.taxonomy.tasks.sync_ncbi_genomes",
        "schedule": crontab(hour=3, minute=0),
        "options": {"queue": "ncbi_sync"},
    },
    # Limpieza de sincronizaciones antiguas (semanal)
    "cleanup-old-syncs-weekly": {
        "task": "apps.taxonomy.tasks.cleanup_old_sync_runs",
        "schedule": crontab(hour=4, minute=0, day_of_week=0),  # Domingos 4 AM
    },
}

app.conf.task_routes = {
    "apps.taxonomy.tasks.sync_ncbi_genomes": {"queue": "ncbi_sync"},
    "apps.taxonomy.tasks.sync_single_taxon": {"queue": "ncbi_sync"},
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Task de prueba para verificar que Celery funciona."""
    print(f"Request: {self.request!r}")
