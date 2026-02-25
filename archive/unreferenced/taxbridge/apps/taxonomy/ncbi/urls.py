# apps/taxonomy/ncbi/urls.py
"""
URL configuration for NCBI Taxon Sync views.
"""
from django.urls import path

from .views import (
    api_start_taxon_sync,
    api_taxon_sync_status,
    api_cancel_taxon_sync,
    api_start_discovery,
    api_discovery_list,
    api_discovered_species,
    api_import_discovered,
    api_dismiss_discovered,
)

app_name = "ncbi"

urlpatterns = [
    path("start/", api_start_taxon_sync, name="taxon-sync-start"),
    path("<int:sync_id>/status/", api_taxon_sync_status, name="taxon-sync-status"),
    path("<int:sync_id>/cancel/", api_cancel_taxon_sync, name="taxon-sync-cancel"),
    # Discovery endpoints
    path("discovery/start/", api_start_discovery, name="discovery-start"),
    path("discovery/runs/", api_discovery_list, name="discovery-runs"),
    path("discovery/species/", api_discovered_species, name="discovered-species"),
    path("discovery/<int:species_id>/import/", api_import_discovered, name="discovery-import"),
    path("discovery/<int:species_id>/dismiss/", api_dismiss_discovered, name="discovery-dismiss"),
]
