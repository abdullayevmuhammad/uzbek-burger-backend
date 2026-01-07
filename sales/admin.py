# sales/admin.py
from django.contrib import admin, messages
from django.db import transaction
from django.utils import timezone

from .models import Order, OrderItem, OrderPayment
from .services import recalc_order_totals, apply_stock_for_order_if_needed
from finance.models import Direction, TxnType
from finance.services import record_cash_txn

from users.models import StaffRole

def _is_owner(user):
    prof = getattr(user, "profile", None)
    return bool(prof and prof.is_active and prof.role == StaffRole.OWNER)

def _staff_branch_id(user):
    prof = getattr(user, "profile", None)
    if not prof or not prof.is_active:
        return None
    return prof.branch_id


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 1
    autocomplete_fields = ("food",)
    fields = ("food", "qty", "unit_price", "line_total")
    readonly_fields = ("unit_price", "line_total")

    def has_add_permission(self, request, obj=None):
        if obj and obj.status != Order.Status.DRAFT:
            return False
        return super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj and obj.status != Order.Status.DRAFT:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status != Order.Status.DRAFT:
            return False
        return super().has_delete_permission(request, obj)


class OrderPaymentInline(admin.TabularInline):
    model = OrderPayment
    extra = 0
    autocomplete_fields = ("account",)
    fields = ("account", "amount", "cash_txn", "created_at")
    readonly_fields = ("cash_txn", "created_at")

    def has_add_permission(self, request, obj=None):
        if obj and obj.status != Order.Status.DRAFT:
            return False
        return super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj and obj.status != Order.Status.DRAFT:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status != Order.Status.DRAFT:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    inlines = (OrderItemInline, OrderPaymentInline)

    list_display = ("id_short", "branch", "status", "total_amount", "paid_amount", "created_at", "paid_at", "stock_applied")
    list_filter = ("branch", "status")
    search_fields = ("id", "note")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    readonly_fields = ("status", "total_amount", "paid_amount", "created_at", "paid_at", "stock_applied")
    fields = ("branch", "status", "note", "total_amount", "paid_amount", "created_at", "paid_at", "stock_applied")

    @admin.display(description="ID")
    def id_short(self, obj: Order):
        return str(obj.id)[:8]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if _is_owner(request.user):
            return qs
        bid = _staff_branch_id(request.user)
        return qs.filter(branch_id=bid)

    @transaction.atomic
    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        order = form.instance

        # 1) totals
        recalc_order_totals(order)
        order.refresh_from_db()

        # 2) cash_txn yo'q paymentlar uchun kassaga yozuv yarat
        created_cnt = 0
        payments = (
            order.payments
            .select_related("account")
            .select_for_update()
            .filter(cash_txn__isnull=True)
        )

        for p in payments:
            if p.account.branch_id != order.branch_id:
                raise ValueError("Payment account boshqa filialga tegishli. To'g'ri account tanlang.")

            tx = record_cash_txn(
                account=p.account,
                direction=Direction.IN_,
                txn_type=TxnType.SALE,
                amount=int(p.amount),
                note=f"Order {str(order.id)[:8]} payment",
                occurred_at=p.created_at or timezone.now(),
                ref_type="order_payment",
                ref_id=p.id,
            )
            p.cash_txn = tx
            p.save(update_fields=["cash_txn"])
            created_cnt += 1

        if created_cnt:
            self.message_user(request, f"{created_cnt} ta payment uchun cash_txn yaratildi.", level=messages.SUCCESS)

        # 3) totals/status
        recalc_order_totals(order)
        order.refresh_from_db()

        if order.total_amount > 0 and order.paid_amount >= order.total_amount:
            if order.status != Order.Status.PAID:
                order.status = Order.Status.PAID
                order.paid_at = order.paid_at or timezone.now()
                order.save(update_fields=["status", "paid_at"])

            # 4) stock apply (idempotent)
            apply_stock_for_order_if_needed(order)
        else:
            # PAID'ni qaytarish mumkin emas (cash+stock buziladi)
            if order.status == Order.Status.PAID:
                raise ValueError("PAID orderni qaytadan DRAFT qilish mumkin emas.")
