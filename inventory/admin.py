from django.contrib import admin, messages
from django.db.models import Sum

from .models import BranchProduct, StockImport, StockImportItem
from .services import post_stock_import


# ====== ACTIONS (module level) ======
@admin.action(description="Post qilish (stock + cost hisoblanadi)")
def post_imports(modeladmin, request, queryset):
    posted = 0

    for imp in queryset:
        if imp.status == StockImport.Status.POSTED:
            continue

        try:
            post_stock_import(imp)
            posted += 1
        except Exception as e:
            modeladmin.message_user(
                request,
                f"Import {str(imp.id)[:8]} POST bo‘lmadi: {e}",
                level=messages.ERROR,
            )

    if posted:
        modeladmin.message_user(
            request,
            f"{posted} ta import POST qilindi.",
            level=messages.SUCCESS,
        )


# ====== BRANCH PRODUCT ======
@admin.register(BranchProduct)
class BranchProductAdmin(admin.ModelAdmin):
    list_display = ("branch", "product", "product_count_type", "stock_qty", "avg_unit_cost", "last_unit_cost")
    list_filter = ("branch", "product__count_type")
    search_fields = ("branch__name", "product__name", "product__sku", "product__barcode")
    autocomplete_fields = ("branch", "product")
    list_select_related = ("branch", "product")
    ordering = ("branch__name", "product__name")
    list_per_page = 50

    @admin.display(description="count_type")
    def product_count_type(self, obj):
        return obj.product.count_type


# ====== IMPORT INLINE ======
class StockImportItemInline(admin.TabularInline):
    model = StockImportItem
    extra = 1
    autocomplete_fields = ("product",)
    fields = ("product", "qty", "line_total_cost")
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        if obj and obj.status == StockImport.Status.POSTED:
            return False
        return super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj and obj.status == StockImport.Status.POSTED:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status == StockImport.Status.POSTED:
            return False
        return super().has_delete_permission(request, obj)


# ====== STOCK IMPORT ======
@admin.register(StockImport)
class StockImportAdmin(admin.ModelAdmin):
    inlines = (StockImportItemInline,)
    list_display = ("id_short", "branch", "status", "note", "created_at", "items_count", "total_cost")
    list_filter = ("branch", "status", "created_at")
    search_fields = ("id", "note", "branch__name")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "status", "cash_txn")
    save_on_top = False
    list_per_page = 50

    actions = (post_imports,)

    @admin.display(description="ID")
    def id_short(self, obj):
        return str(obj.id)[:8]

    @admin.display(description="Items")
    def items_count(self, obj):
        return obj.items.count()

    @admin.display(description="Total cost (so'm)")
    def total_cost(self, obj):
        agg = obj.items.aggregate(s=Sum("line_total_cost"))
        return agg["s"] or 0

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj and obj.status == StockImport.Status.POSTED:
            ro += ["branch", "note", "paid_from_account"]
        return tuple(dict.fromkeys(ro))

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status == StockImport.Status.POSTED:
            return False
        return super().has_delete_permission(request, obj)


# ====== STOCK IMPORT ITEM (optional separate admin) ======
@admin.register(StockImportItem)
class StockImportItemAdmin(admin.ModelAdmin):
    list_display = ("stock_import", "product", "qty", "line_total_cost")
    list_filter = ("product__count_type",)
    search_fields = ("product__name", "product__sku", "product__barcode", "stock_import__id")
    autocomplete_fields = ("stock_import", "product")
    list_select_related = ("stock_import", "product")
