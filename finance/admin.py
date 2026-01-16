# finance/admin.py
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _

from .models import MoneyAccount, CashTransaction
from users.models import StaffRole

def _is_owner(user):
    # NOTE: Django superuser/admin paneli uchun profil bo'lmasligi mumkin.
    # Bunday holatda ham superuser hamma narsani ko'rishi kerak.
    if getattr(user, "is_superuser", False):
        return True
    prof = getattr(user, "profile", None)
    return bool(prof and prof.is_active and prof.role == StaffRole.OWNER)

def _staff_branch_id(user):
    prof = getattr(user, "profile", None)
    if not prof or not prof.is_active:
        return None
    return prof.branch_id


class CashTransactionInline(admin.TabularInline):
    """
    MoneyAccount sahifasida shu account'ga tegishli pul harakatlarini ko'rsatadi.
    Transactionlar faqat service orqali yaratilishi kerak, admin'dan qo'lda emas.
    """
    model = CashTransaction
    extra = 0
    can_delete = False
    show_change_link = True
    # classes = ("collapse",)  # xohlasangiz olib tashlang (doim ochiq bo'lsin desangiz)

    fields = (
        "occurred_at",
        "direction",
        "txn_type",
        "amount",
        "note",
        "ref_type",
        "ref_id",
        "created_at",
    )
    readonly_fields = fields
    ordering = ("-occurred_at",)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        # Inline ichida edit bo'lmasin (audit buzilmasin)
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

    # balance_cache qo'lda o'zgarmasin (ledger bilan farq chiqib ketadi)
    readonly_fields = ("balance_cache",)

    # (ixtiyoriy) formada qaysi fieldlar ko'rinsin:
    fields = ("branch", "name", "kind", "is_active", "balance_cache")

    # (ixtiyoriy) kind sizga kerak bo'lmasa, shuni yoqing:
    # fields = ("branch", "name", "is_active", "balance_cache")

    def has_add_permission(self, request):
        if _is_owner(request.user):
            return True
        # Branch biriktirilmagan (yoki inactive) staff kassani qo'sha olmasin,
        # aks holda "Added successfully" bo'lib, listda 0 ko'rinib qoladi.
        return bool(_staff_branch_id(request.user))

    def get_fields(self, request, obj=None):
        # Owner/superuser uchun hammasi ko'rinsin.
        if _is_owner(request.user):
            return super().get_fields(request, obj)
        # Staff uchun branchni edit qilmasin (avto staff branch).
        base = ["name", "kind", "is_active", "balance_cache"]
        return base

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if _is_owner(request.user):
            return form
        bid = _staff_branch_id(request.user)
        # Non-owner staff uchun branch field bo'lmasa ham, ehtiyotkorlik uchun:
        if bid and "branch" in form.base_fields:
            form.base_fields["branch"].queryset = form.base_fields["branch"].queryset.filter(id=bid)
            form.base_fields["branch"].initial = bid
            form.base_fields["branch"].disabled = True
        return form

    def save_model(self, request, obj, form, change):
        if not _is_owner(request.user):
            bid = _staff_branch_id(request.user)
            if not bid:
                raise PermissionDenied(_("Sizga filial biriktirilmagan. Admin'da kassani yaratish uchun profil.branch kerak."))
            obj.branch_id = bid
        super().save_model(request, obj, form, change)
        if not _is_owner(request.user):
            messages.info(request, _("Kassa sizning filialingizga avtomatik biriktirildi."))
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if _is_owner(request.user):
            return qs
        bid = _staff_branch_id(request.user)
        if not bid:
            return qs.none()
        return qs.filter(branch_id=bid)


@admin.register(CashTransaction)
class CashTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "occurred_at",
        "branch",
        "account",
        "direction",
        "txn_type",
        "amount",
        "note",
        "ref_type",
        "ref_id",
    )
    list_filter = ("branch", "account", "direction", "txn_type")
    search_fields = ("note", "ref_type", "ref_id", "account__name", "branch__name")
    date_hierarchy = "occurred_at"
    ordering = ("-occurred_at",)

    autocomplete_fields = ("account", "branch")
    list_select_related = ("branch", "account")

    # audit: transactionni admin'dan edit qilish tavsiya qilinmaydi
    readonly_fields = ("created_at",)

    # (xohlasangiz) transactionni umuman o'zgartirishni bloklash:
    # def has_change_permission(self, request, obj=None):
    #     return False

    # def has_delete_permission(self, request, obj=None):
    #     return False
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if _is_owner(request.user):
            return qs
        bid = _staff_branch_id(request.user)
        if not bid:
            return qs.none()
        return qs.filter(branch_id=bid)
