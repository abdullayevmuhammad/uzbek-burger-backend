from django.urls import path

from . import views

app_name = "sales"

urlpatterns = [
    path("", views.pos_orders, name="pos_orders"),
    path("analytics/", views.pos_analytics, name="pos_analytics"),
    path("order/new/", views.pos_order_create, name="pos_order_create"),
    path("api/pending-tasks/", views.pos_pending_tasks_feed, name="pos_pending_tasks_feed"),
    path("order/<uuid:pk>/", views.pos_order_detail, name="pos_order_detail"),
    path("order/<uuid:pk>/pay/", views.pos_order_pay, name="pos_order_pay"),
    path("order/<uuid:pk>/deliver/", views.pos_order_deliver, name="pos_order_deliver"),
    path("order/<uuid:pk>/cancel/", views.pos_order_cancel, name="pos_order_cancel"),
    path("order/<uuid:pk>/kitchen/", views.pos_order_kitchen_task, name="pos_order_kitchen"),
    path("order/<uuid:pk>/receipt/", views.pos_order_receipt, name="pos_order_receipt"),
    path("order/<uuid:pk>/receipt-data/", views.pos_order_receipt_data, name="pos_order_receipt_data"),
    path("order/<uuid:pk>/kitchen-print-data/", views.pos_order_kitchen_print_data, name="pos_order_kitchen_print_data"),
    path("api/menu/", views.pos_menu_json, name="pos_menu_json"),
]
