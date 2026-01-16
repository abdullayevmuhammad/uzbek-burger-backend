from django.contrib import admin
from django.utils.html import format_html

from .models import Food, FoodItem, FoodCategory
from django.utils.safestring import mark_safe


class FoodItemInline(admin.TabularInline):
    model = FoodItem
    extra = 1
    autocomplete_fields = ("product",)
    fields = ("product", "qty")


@admin.register(FoodCategory)
class FoodCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "branch", "sort_order", "is_active")
    list_filter = ("type", "is_active", "branch")
    search_fields = ("name",)
    list_editable = ("sort_order", "is_active")
    ordering = ("type", "sort_order", "name")


@admin.register(Food)
class FoodAdmin(admin.ModelAdmin):
    inlines = (FoodItemInline,)
    list_display = ("name", "type", "category", "branch", "sell_price", "is_active")
    list_filter = ("type", "is_active", "branch", "category")
    search_fields = ("name",)
    list_editable = ("is_active",)
    ordering = ("type", "category__sort_order", "sort_order", "name")
    list_per_page = 50
    readonly_fields = ("image_preview",)  # preview read-only bo'ladi

    fieldsets = (
        (None, {
            "fields": (
                "branch",
                "type",
                "category",
                "name",
                "image",
                "image_preview",  # image tagidan keyin qo'ying
                "sell_price",
                "sort_order",
                "is_active",
            )
        }),
        # sizda inline/items bo'lsa qolaversin
    )

    def image_preview(self, obj):
        if obj and getattr(obj, "image", None):
            try:
                return format_html(
                    '<img id="image-preview" src="{}" style="max-height:160px; border-radius:12px; border:1px solid #334; padding:4px;" />',
                    obj.image.url
                )
            except Exception:
                pass

        return mark_safe(
            '<img id="image-preview" style="display:none; max-height:160px; border-radius:12px; border:1px solid #334; padding:4px;" />'
        )

    image_preview.short_description = "Preview"

    class Media:
        js = ("admin/js/image_preview.js",)

@admin.register(FoodItem)
class FoodItemAdmin(admin.ModelAdmin):
    list_display = ("food", "product", "qty")
    search_fields = ("food__name", "product__name", "product__sku", "product__barcode")
    autocomplete_fields = ("food", "product")
    list_select_related = ("food", "product")
