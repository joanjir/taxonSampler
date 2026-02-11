"""
UI URL configuration for taxonomy module.

Only HTML page routes are defined here. API routes are in api/urls.py.
"""
from django.urls import path

from .dashboard.views import home, export_sampling
from .ncbi.views import taxon_sync_dashboard
from .tree.views import tree_page

app_name = "taxonomy"

urlpatterns = [
    # Main pages
    path("", home, name="home"),
    path("tree/", tree_page, name="tree"),
    
    # Taxon Sync Dashboard (NCBI + COL)
    path("taxon-sync/", taxon_sync_dashboard, name="taxon-sync-dashboard"),
    
    # Export endpoints (POST)
    path("sampling/export/<str:fmt>/", export_sampling, name="sampling-export"),
]
