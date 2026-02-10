from django.urls import path
from . import views

app_name = "landing"

urlpatterns = [
    path("", views.home, name="home"),
    path("biz-haqimizda/", views.about, name="about"),
    path("menu/", views.menu, name="menu"),
    path("filiallar/", views.branches, name="branches"),
    path("postlar/", views.posts_list, name="posts"),
    path("postlar/<slug:slug>/", views.post_detail, name="post_detail"),
    path("aloqa/", views.contact, name="contact"),
]
