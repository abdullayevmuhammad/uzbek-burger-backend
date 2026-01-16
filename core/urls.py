from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("select-branch/", views.select_branch, name="select_branch"),
    path("dashboard/", views.dashboard, name="dashboard"),
]