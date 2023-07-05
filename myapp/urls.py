from django.contrib import admin
from django.urls import path,include
from myapp import views

urlpatterns = [
    path("", views.index, name="index"),
    path("add_child_component", views.add_child_component, name="add_child_component"),
    path("add_child_image", views.add_child_image, name="add_new_image"),
    path("manual_sync_on_image", views.manual_sync_on_image, name="manual_sync_on_image"),
    path("manual_sync_on_node", views.manual_sync_on_node, name="manual_sync_on_node"),
    path("edit_node", views.edit_node, name="edit_node"),
    path("delete_node", views.delete_node, name="delete_node")
]
