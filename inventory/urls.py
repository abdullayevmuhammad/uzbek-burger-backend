from django.urls import path
from . import views

urlpatterns = [
    path("ombor/", views.warehouse_home, name="warehouse_home"),

    # TAB 1: mahsulotlar (qoldiq)
    path("ombor/mahsulotlar/", views.stock_list, name="stock_list"),
    path("ombor/mahsulotlar/yangi/", views.product_create, name="product_create"),
    path("ombor/mahsulotlar/<uuid:pk>/", views.product_detail, name="product_detail"),

    # TAB 2: importlar
    path("ombor/importlar/", views.import_list, name="import_list"),
    path("ombor/importlar/yangi/", views.import_create, name="import_create"),
    path("ombor/importlar/<uuid:pk>/", views.import_detail, name="import_detail"),
    path("ombor/importlar/<uuid:pk>/add-item/", views.import_add_item, name="import_add_item"),
    path("ombor/importlar/<uuid:pk>/post/", views.import_post, name="import_post"),
]
