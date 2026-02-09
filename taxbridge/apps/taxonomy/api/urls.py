"""
API URL configuration for taxonomy module.

All API routes are defined here with RESTful naming conventions.
"""
from django.urls import path

from . import views
from ..views_sync import (
    api_start_sync,
    api_sync_status,
    api_sync_log,
    api_cancel_sync,
    api_sync_list,
    api_sync_stats,
    api_sync_taxon,
)

app_name = "taxonomy_api"

urlpatterns = [
    # Tree API
    path("tree/data/", views.tree_data, name="tree-data"),
    path("tree/search/", views.tree_search, name="tree-search"),
    
    # Sampling API
    path("sampling/run/", views.sampling_run, name="sampling-run"),
    
    # COL Navigation API
    path("col/next-ranks/", views.col_next_ranks, name="col-next-ranks"),
    path("col/nodes/", views.col_nodes, name="col-nodes"),
    path("col/species/", views.col_species, name="col-species"),
    path("col/resolve/", views.col_resolve_selection, name="col-resolve"),
    
    # NCBI Sync API
    path("sync/start/", api_start_sync, name="sync-start"),
    path("sync/list/", api_sync_list, name="sync-list"),
    path("sync/stats/", api_sync_stats, name="sync-stats"),
    path("sync/<int:sync_id>/status/", api_sync_status, name="sync-status"),
    path("sync/<int:sync_id>/log/", api_sync_log, name="sync-log"),
    path("sync/<int:sync_id>/cancel/", api_cancel_sync, name="sync-cancel"),
    path("sync/taxon/<int:taxid>/", api_sync_taxon, name="sync-taxon"),
]
