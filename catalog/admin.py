from django.contrib import admin
from .models import Product


@admin.action(description="Tanlangan productlarni aktiv qilish")
def make_active(modeladmin, request, queryset):
    queryset.update(is_active=True)


@admin.action(description="Tanlangan productlarni noaktiv qilish")
def make_inactive(modeladmin, request, queryset):
    queryset.update(is_active=False)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "count_type", "sku", "barcode", "is_active", "created_at")
    list_filter = ("count_type", "is_active")
    search_fields = ("name", "sku", "barcode")
    list_editable = ("is_active",)
    ordering = ("name",)
    date_hierarchy = "created_at"
    actions = (make_active, make_inactive)

    # Kichik UX
    list_per_page = 50
    save_on_top = False
