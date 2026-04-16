from __future__ import absolute_import

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("taxbridge")
app.config_from_object("django.conf:settings", namespace="CELERY")

# autodiscovery estándar
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "sync-ncbi-genomes-daily": {
        "task": "apps.taxonomy.ncbi.tasks.sync_ncbi_genomes",
        "schedule": crontab(hour=3, minute=0),
        "options": {"queue": "ncbi_sync"},
    },
    "cleanup-old-syncs-weekly": {
        "task": "apps.taxonomy.ncbi.tasks.cleanup_old_sync_runs",
        "schedule": crontab(hour=4, minute=0, day_of_week=0),
    },
    "discover-new-species-weekly": {
        "task": "apps.taxonomy.ncbi.tasks.discover_new_species",
        "schedule": crontab(hour=5, minute=0, day_of_week=1),
        "options": {"queue": "ncbi_sync"},
    },
    "refresh-home-dashboard-cache-every-15-min": {
        "task": "apps.taxonomy.ncbi.tasks.refresh_home_dashboard_cache",
        "schedule": crontab(minute="*/15"),
        "options": {"queue": "default"},
    },
}

app.conf.task_routes = {
    "apps.taxonomy.ncbi.tasks.sync_ncbi_genomes": {"queue": "ncbi_sync"},
    "apps.taxonomy.ncbi.tasks.sync_single_taxon": {"queue": "ncbi_sync"},
    "apps.taxonomy.ncbi.tasks.sync_taxon_with_col": {"queue": "ncbi_sync"},
    "apps.taxonomy.ncbi.tasks.discover_new_species": {"queue": "ncbi_sync"},
    "apps.taxonomy.ncbi.tasks.refresh_home_dashboard_cache": {"queue": "default"},
    "apps.taxonomy.ncbi.tasks.invalidate_home_dashboard_cache": {"queue": "default"},
}