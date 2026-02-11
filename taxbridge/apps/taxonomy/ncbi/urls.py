# apps/taxonomy/ncbi/urls.py
"""
URL configuration for NCBI Taxon Sync views.
"""
from django.urls import path

from .views import (
    api_start_taxon_sync,
    api_taxon_sync_status,
    api_cancel_taxon_sync,
)

app_name = "ncbi"

urlpatterns = [
    path("start/", api_start_taxon_sync, name="taxon-sync-start"),
    path("<int:sync_id>/status/", api_taxon_sync_status, name="taxon-sync-status"),
    path("<int:sync_id>/cancel/", api_cancel_taxon_sync, name="taxon-sync-cancel"),
]
