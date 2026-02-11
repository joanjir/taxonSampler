"""
API URL configuration for taxonomy module.

All API routes are defined here with RESTful naming conventions.
"""
from django.urls import path

from . import views
from apps.taxonomy.ncbi.views import (
    api_start_taxon_sync,
    api_taxon_sync_status,
    api_cancel_taxon_sync,
)

app_name = "taxonomy_api"

urlpatterns = [
    # Tree API
    path("tree/data/", views.tree_data, name="tree-data"),
    path("tree/search/", views.tree_search, name="tree-search"),
    
    # Sampling API
    path("sampling/scope-info/", views.sampling_scope_info, name="sampling-scope-info"),
    path("sampling/run/", views.sampling_run, name="sampling-run"),
    
    # COL Navigation API
    path("col/next-ranks/", views.col_next_ranks, name="col-next-ranks"),
    path("col/nodes/", views.col_nodes, name="col-nodes"),
    path("col/species/", views.col_species, name="col-species"),
    path("col/resolve/", views.col_resolve_selection, name="col-resolve"),
    
    # Genomes API
    path("genomes/", views.genomes_list, name="genomes-list"),
    path("genomes/<str:accession>/", views.genome_detail, name="genome-detail"),
    path("genomes/<str:accession>/update/", views.genome_update, name="genome-update"),
    
    # COL Search API (for edit modal)
    path("col/search/", views.col_search, name="col-search"),
    
    # Taxon Sync API (NCBI + COL)
    path("taxon-sync/start/", api_start_taxon_sync, name="taxon-sync-start"),
    path("taxon-sync/<int:sync_id>/status/", api_taxon_sync_status, name="taxon-sync-status"),
    path("taxon-sync/<int:sync_id>/cancel/", api_cancel_taxon_sync, name="taxon-sync-cancel"),
]
