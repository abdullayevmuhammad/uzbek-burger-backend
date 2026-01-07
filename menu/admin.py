from django.contrib import admin
from .models import Food, FoodItem


class FoodItemInline(admin.TabularInline):
    model = FoodItem
    extra = 1
    autocomplete_fields = ("product",)
    fields = ("product", "qty")
    show_change_link = True


@admin.register(Food)
class FoodAdmin(admin.ModelAdmin):
    inlines = (FoodItemInline,)
    list_display = ("name", "sell_price", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    list_editable = ("is_active",)
    ordering = ("name",)
    save_on_top = False
    list_per_page = 50


@admin.register(FoodItem)
class FoodItemAdmin(admin.ModelAdmin):
    list_display = ("food", "product", "qty", "product_count_type")
    list_filter = ("product__count_type",)
    search_fields = ("food__name", "product__name", "product__sku", "product__barcode")
    autocomplete_fields = ("food", "product")
    list_select_related = ("food", "product")

    @admin.display(description="count_type")
    def product_count_type(self, obj: FoodItem):
        return obj.product.count_type
