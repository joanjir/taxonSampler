"""
UI URL configuration for taxonomy module.

Only HTML page routes are defined here. API routes are in api/urls.py.
"""
from django.urls import path

from .dashboard.views import home, export_sampling, report_issue, create_github_issue, about, tutorials
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

    # Report issue
    path("report-issue/", report_issue, name="report-issue"),
    path("report-issue/create/", create_github_issue, name="create-github-issue"),

    # Help & Documentation
    path("about/", about, name="about"),
    path("tutorials/", tutorials, name="tutorials"),
]
