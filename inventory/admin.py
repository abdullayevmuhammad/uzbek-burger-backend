from django.contrib import admin, messages
from django.db.models import Sum
from django.utils import timezone

from users.utils import get_profile, get_user_branch_id, is_admin_user, is_cashier_role_value, is_super_recovery_user

from .models import BranchProduct, StockImport, StockImportItem
from .services import post_stock_import, reverse_stock_import


@admin.action(description="Post qilish (stock + cost hisoblanadi)")
def post_imports(modeladmin, request, queryset):
    posted = 0

    for imp in queryset:
        if imp.status == StockImport.Status.POSTED:
            continue

        try:
            post_stock_import(imp, by_user=request.user)

            changed = []
            if hasattr(imp, "posted_by_id") and not imp.posted_by_id:
                imp.posted_by = request.user
                changed.append("posted_by")
            if hasattr(imp, "posted_at") and not imp.posted_at:
                imp.posted_at = timezone.now()
                changed.append("posted_at")
            if changed:
                imp.save(update_fields=changed)

            posted += 1
        except Exception as e:
            modeladmin.message_user(
                request,
                f"Import {str(imp.id)[:8]} POST bo'lmadi: {e}",
                level=messages.ERROR,
            )

    if posted:
        modeladmin.message_user(
            request,
            f"{posted} ta import POST qilindi.",
            level=messages.SUCCESS,
        )


@admin.register(BranchProduct)
class BranchProductAdmin(admin.ModelAdmin):
    list_display = ("branch", "product", "product_count_type", "stock_qty_display", "avg_unit_cost", "last_unit_cost")
    list_filter = ("branch", "product__count_type")
    search_fields = ("branch__name", "product__name", "product__sku", "product__barcode")
    autocomplete_fields = ("branch", "product")
    list_select_related = ("branch", "product")
    ordering = ("branch__name", "product__name")
    list_per_page = 50

    def has_module_permission(self, request):
        return is_admin_user(request.user)

    def has_view_permission(self, request, obj=None):
        return is_admin_user(request.user)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_admin_user(request.user):
            return qs
        bid = get_user_branch_id(request.user)
        if not bid:
            return qs.none()
        return qs.filter(branch_id=bid)

    @admin.display(description="count_type")
    def product_count_type(self, obj):
        return obj.product.count_type

    @admin.display(description="Qoldiq")
    def stock_qty_display(self, obj):
        return obj.stock_qty


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
            return is_super_recovery_user(request.user)
        return super().has_delete_permission(request, obj)

    def delete_model(self, request, obj):
        reverse_stock_import(obj, actor=request.user)

    def delete_queryset(self, request, queryset):
        for imp in queryset:
            reverse_stock_import(imp, actor=request.user)


@admin.register(StockImport)
class StockImportAdmin(admin.ModelAdmin):
    inlines = (StockImportItemInline,)
    list_display = ("id_short", "branch", "status", "note", "created_at", "created_by", "posted_by", "posted_at", "items_count", "total_cost")
    list_filter = ("branch", "status", "created_at")
    search_fields = ("id", "note", "branch__name")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    save_on_top = False
    list_per_page = 50
    actions = (post_imports,)
    readonly_fields = ("created_at", "status", "cash_txn", "created_by", "posted_by", "posted_at")
    raw_id_fields = ("created_by", "posted_by")

    def has_module_permission(self, request):
        return is_admin_user(request.user)

    def has_view_permission(self, request, obj=None):
        return is_admin_user(request.user)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_admin_user(request.user):
            return qs
        bid = get_user_branch_id(request.user)
        if not bid:
            return qs.none()
        return qs.filter(branch_id=bid)

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
        for f in ("created_by", "posted_by", "posted_at"):
            if f not in ro:
                ro.append(f)
        return tuple(dict.fromkeys(ro))

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status == StockImport.Status.POSTED:
            return False
        return super().has_delete_permission(request, obj)

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user

        prof = get_profile(request.user)
        if prof and getattr(prof, "is_active", False) and is_cashier_role_value(getattr(prof, "role", None)):
            obj.branch_id = prof.branch_id

        super().save_model(request, obj, form, change)
