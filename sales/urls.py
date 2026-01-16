from django.urls import path

from . import views

app_name = "sales"

urlpatterns = [
    path("", views.pos_orders, name="pos_orders"),
    path("order/new/", views.pos_order_create, name="pos_order_create"),
    path("order/<uuid:pk>/", views.pos_order_detail, name="pos_order_detail"),
    path("order/<uuid:pk>/pay/", views.pos_order_pay, name="pos_order_pay"),
    path("order/<uuid:pk>/deliver/", views.pos_order_deliver, name="pos_order_deliver"),
    path("api/menu/", views.pos_menu_json, name="pos_menu_json"),
]
