from django.urls import path

from . import views

app_name = "menu"

urlpatterns = [
    path("board/", views.menu_board, name="menu_board"),

    # food JSON (dialog)
    path("food/<uuid:food_id>/json/", views.food_json, name="menu_food_json"),

    # CRUD
    path("foods/", views.food_list, name="menu_food_list"),
    path("foods/add/", views.food_add, name="menu_food_add"),
    path("foods/<uuid:food_id>/edit/", views.food_edit, name="menu_food_edit"),
    path("foods/<uuid:food_id>/delete/", views.food_delete, name="menu_food_delete"),
]
