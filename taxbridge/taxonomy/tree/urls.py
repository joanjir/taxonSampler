from django.urls import path
from .views import tree_data

urlpatterns = [
    path("data/", tree_data, name="tree-data"),
]