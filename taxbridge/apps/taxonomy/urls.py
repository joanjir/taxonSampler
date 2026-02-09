"""
UI URL configuration for taxonomy module.

Only HTML page routes are defined here. API routes are in api/urls.py.
"""
from django.urls import path

from .views import (
    home,
    scroll_test,
    export_sampling,
    search_debug_page,
    tree_cut_debug_page,
)
from .tree.views import tree_page

app_name = "taxonomy"

urlpatterns = [
    # Main pages
    path("", home, name="home"),
    path("tree/", tree_page, name="tree"),
    
    # Export endpoints (POST - special case, keeps here for now)
    path("sampling/export/<str:fmt>/", export_sampling, name="sampling-export"),
    
    # Debug/development pages
    path("dev/scroll-test/", scroll_test, name="scroll-test"),
    path("dev/search-debug/", search_debug_page, name="search-debug"),
    path("dev/tree-cut-debug/", tree_cut_debug_page, name="tree-cut-debug"),
]
