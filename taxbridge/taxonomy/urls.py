from django.urls import path, include
from .views import  colnav_page, base, scroll_test, export_sampling, search_debug_page, tree_cut_debug_page

from . import views_colnav
app_name = "taxonomy"

urlpatterns = [
    path("ui/colnav/", colnav_page, name="ui_colnav"),
    
    path("col/next-ranks/", views_colnav.next_ranks, name="col_next_ranks"),
    path("col/nodes/", views_colnav.nodes, name="col_nodes"),
    path("col/species/", views_colnav.species, name="col_species"),
    path("col/resolve/", views_colnav.resolve_selection, name="col_resolve"),
    
    path("dev/scroll-test/", scroll_test, name="scroll_test"),

    path("layout/base/", base, name="layout_base"),
    path("sampling/export/<str:fmt>/", export_sampling, name="sampling_export"),

    path("tree/", include("taxonomy.tree.urls")),
  
    path("search-debug/", search_debug_page, name="tree-search-debug"),
    path("tree-cut-debug/", tree_cut_debug_page, name="tree-cut-debug"),

]
