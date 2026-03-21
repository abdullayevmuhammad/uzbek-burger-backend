from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _

from .models import CashTransaction, MoneyAccount, NON_SALES_TXN_TYPES
from .services import recalculate_account_balances
from users.utils import get_user_branch_id, is_admin_user, is_super_recovery_user


class CashTransactionInline(admin.TabularInline):
    model = CashTransaction
    extra = 0
    can_delete = False
    show_change_link = True
    fields = (
        "occurred_at",
        "direction",
        "txn_type",
        "amount",
        "reason",
        "note",
        "actor",
        "ref_type",
        "ref_id",
        "created_at",
    )
    readonly_fields = fields
    ordering = ("-occurred_at",)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MoneyAccount)
class MoneyAccountAdmin(admin.ModelAdmin):
    list_display = ("branch", "name", "kind", "balance_cache", "is_active")
    list_filter = ("branch", "kind", "is_active")
    search_fields = ("branch__name", "name")
    ordering = ("branch__name", "name")
    autocomplete_fields = ("branch",)
    list_editable = ("is_active",)
    inlines = (CashTransactionInline,)
    readonly_fields = ("balance_cache",)
    fields = ("branch", "name", "kind", "is_active", "balance_cache")

    def has_module_permission(self, request):
        return is_admin_user(request.user)

    def has_view_permission(self, request, obj=None):
        return is_admin_user(request.user)

    def has_add_permission(self, request):
        return is_admin_user(request.user)

    def has_change_permission(self, request, obj=None):
        return is_admin_user(request.user)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_admin_user(request.user):
            return qs
        bid = get_user_branch_id(request.user)
        if not bid:
            return qs.none()
        return qs.filter(branch_id=bid)


@admin.register(CashTransaction)
class CashTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "occurred_at",
        "history_bucket",
        "branch",
        "account",
        "direction",
        "txn_type",
        "amount",
        "reason",
        "actor",
        "note",
        "ref_type",
        "ref_id",
    )
    list_filter = ("branch", "account", "direction", "txn_type")
    search_fields = ("reason", "note", "ref_type", "ref_id", "account__name", "branch__name", "actor__username")
    date_hierarchy = "occurred_at"
    ordering = ("-occurred_at", "-created_at")
    autocomplete_fields = ("account", "branch", "actor")
    list_select_related = ("branch", "account", "actor")
    readonly_fields = ("created_at",)

    @admin.display(description="History group")
    def history_bucket(self, obj):
        return obj.history_bucket

    def has_module_permission(self, request):
        return is_admin_user(request.user)

    def has_view_permission(self, request, obj=None):
        return is_admin_user(request.user)

    def has_add_permission(self, request):
        return is_super_recovery_user(request.user)

    def has_change_permission(self, request, obj=None):
        if is_super_recovery_user(request.user):
            return True
        return request.method in {"GET", "HEAD", "OPTIONS"} and is_admin_user(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_super_recovery_user(request.user)

    def get_readonly_fields(self, request, obj=None):
        if is_super_recovery_user(request.user):
            return ("created_at",)
        return tuple(field.name for field in self.model._meta.fields)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_admin_user(request.user):
            return qs
        bid = get_user_branch_id(request.user)
        if not bid:
            return qs.none()
        return qs.filter(branch_id=bid)

    def save_model(self, request, obj, form, change):
        if not is_super_recovery_user(request.user):
            raise PermissionDenied(_("Cash transactionni qo'lda boshqarish faqat superuser uchun."))

        if obj.txn_type in NON_SALES_TXN_TYPES and not obj.actor_id:
            obj.actor = request.user

        if obj.txn_type in NON_SALES_TXN_TYPES and not str(obj.reason or "").strip():
            raise PermissionDenied(_("Manual cash correction uchun reason majburiy."))

        super().save_model(request, obj, form, change)
        messages.success(request, _("Cash transaction saqlandi."))

    def delete_queryset(self, request, queryset):
        if not is_super_recovery_user(request.user):
            raise PermissionDenied(_("Cash transactionni o'chirish faqat superuser uchun."))
        account_ids = list(queryset.values_list("account_id", flat=True))
        queryset.delete()
        recalculate_account_balances(account_ids)
