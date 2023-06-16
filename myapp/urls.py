from django.contrib import admin
from django.urls import path,include
from myapp import views

urlpatterns = [
    path("", views.index, name="index"),
    path("add_node", views.add_node, name="add_node")
]
