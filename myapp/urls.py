from django.contrib import admin
from django.urls import path,include
from myapp import views

urlpatterns = [
    path("", views.index, name="index"),
    path("add_node", views.add_node, name="add_node"),
    path("manual_sync", views.manual_sync, name="manual_sync"),
    path("edit_node", views.edit_node, name="edit_node"),
    path("delete_node", views.delete_node, name="delete_node")
]
