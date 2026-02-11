# config/celery.py
"""
Celery configuration for TaxaBridge.
To start the worker:
    celery -A config worker -l info

To start the scheduler (beat):
    celery -A config beat -l info

Or both in one:
    celery -A config worker -B -l info
"""
from __future__ import absolute_import

import os

from celery import Celery
from celery.schedules import crontab

# Set default settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("taxbridge")

# Use string to avoid serialization issues
app.config_from_object("django.conf:settings", namespace="CELERY")

# Autodiscover tasks in all installed apps
app.autodiscover_tasks()

# ======================
# Scheduled tasks
# ======================
app.conf.beat_schedule = {
    # Sync NCBI genomes daily at 3:00 AM
    "sync-ncbi-genomes-daily": {
        "task": "apps.taxonomy.tasks.sync_ncbi_genomes",
        "schedule": crontab(hour=3, minute=0),
        "options": {"queue": "ncbi_sync"},
    },
    # Clean up old sync runs (weekly)
    "cleanup-old-syncs-weekly": {
        "task": "apps.taxonomy.tasks.cleanup_old_sync_runs",
        "schedule": crontab(hour=4, minute=0, day_of_week=0),  # Sundays 4 AM
    },
}

app.conf.task_routes = {
    "apps.taxonomy.tasks.sync_ncbi_genomes": {"queue": "ncbi_sync"},
    "apps.taxonomy.tasks.sync_single_taxon": {"queue": "ncbi_sync"},
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Test task to verify that Celery is working."""
    print(f"Request: {self.request!r}")
