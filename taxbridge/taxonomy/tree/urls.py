from django.urls import path
from .views import tree_data, tree_search, tree_page

urlpatterns = [
    path("data/", tree_data, name="tree-data"),
    path("search/", tree_search, name="tree-search"),
    path("", tree_page, name="tree-page"),

]