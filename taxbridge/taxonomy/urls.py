from django.urls import path
from .views import health, tree_page, colnav_page,base, scroll_test, sampling_create,sampling_tree_page, sampling_tree_newick
from .tree_view import tree_data
from . import views_colnav
app_name = "taxonomy"

urlpatterns = [
    path("health/", health),
    path("tree/", tree_page, name="tree"),
    path("tree/data/", tree_data, name="tree_data"),
    path("ui/colnav/", colnav_page, name="ui_colnav"),

    
    path("col/next-ranks/", views_colnav.next_ranks, name="col_next_ranks"),
    path("col/nodes/", views_colnav.nodes, name="col_nodes"),
    path("col/species/", views_colnav.species, name="col_species"),
    path("col/resolve/", views_colnav.resolve_selection, name="col_resolve"),
    
    
    path("dev/scroll-test/", scroll_test, name="scroll_test"),

    path("layout/base/", base, name="layout_base"),
    
    path("sampling/create/", sampling_create, name="sampling_create"),
    path("sampling/<int:pk>/tree/", sampling_tree_page, name="sampling_tree_page"),
    path("sampling/<int:pk>/tree.nwk", sampling_tree_newick, name="sampling_tree_newick"),

]
