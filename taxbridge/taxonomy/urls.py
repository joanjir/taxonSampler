from django.urls import path
from .views import health, tree_page, colnav_page
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
]
