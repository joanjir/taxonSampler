"""
API URL configuration for taxonomy module.

All API routes are defined here with RESTful naming conventions.
"""
from django.urls import path

from . import views

app_name = "taxonomy_api"

urlpatterns = [
    # Tree API
    path("tree/data/", views.tree_data, name="tree-data"),
    path("tree/search/", views.tree_search, name="tree-search"),
    
    # COL Navigation API
    path("col/next-ranks/", views.col_next_ranks, name="col-next-ranks"),
    path("col/nodes/", views.col_nodes, name="col-nodes"),
    path("col/species/", views.col_species, name="col-species"),
    path("col/resolve/", views.col_resolve_selection, name="col-resolve"),
]
