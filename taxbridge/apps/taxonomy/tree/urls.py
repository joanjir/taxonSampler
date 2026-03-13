from django.urls import path
from .views import tree_data, tree_search, tree_page, invalidate_tree_cache, tree_version

urlpatterns = [
    path("data/", tree_data, name="tree-data"),
    path("search/", tree_search, name="tree-search"),
    path("version/", tree_version, name="tree-version"),
    path("cache/invalidate/", invalidate_tree_cache, name="tree-cache-invalidate"),
    path("", tree_page, name="tree-page"),

]