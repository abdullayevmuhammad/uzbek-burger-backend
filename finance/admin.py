# finance/admin.py
from django.contrib import admin
from .models import MoneyAccount, CashTransaction


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
