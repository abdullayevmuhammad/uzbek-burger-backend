from django.contrib import admin, messages
from django.db import transaction
from django.utils import timezone

from finance.models import Direction, TxnType
from finance.services import record_cash_txn
from users.utils import get_profile, get_user_branch_id, is_admin_user, is_cashier_role_value, is_super_recovery_user

from .models import Order, OrderItem, OrderPayment, KitchenTask
from .services import (
    apply_stock_for_order_if_needed,
    delete_order_for_recovery,
    delete_orders_for_recovery,
    recalc_order_totals,
)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 1
    autocomplete_fields = ("food",)
    fields = ("food", "qty", "unit_price", "line_total")
    readonly_fields = ("unit_price", "line_total")

    def has_add_permission(self, request, obj=None):
        if obj and (obj.is_locked or obj.status != Order.Status.DRAFT or getattr(obj, "is_delivered", False)):
            return False
        return super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj and (obj.is_locked or obj.status != Order.Status.DRAFT or getattr(obj, "is_delivered", False)):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and (obj.is_locked or obj.status != Order.Status.DRAFT or getattr(obj, "is_delivered", False)):
            return False
        return super().has_delete_permission(request, obj)


class OrderPaymentInline(admin.TabularInline):
    model = OrderPayment
    extra = 0
    autocomplete_fields = ("account",)
    fields = ("account", "amount", "cash_txn", "created_at")
    readonly_fields = ("cash_txn", "created_at")

    def has_add_permission(self, request, obj=None):
        if obj and (obj.is_locked or obj.status != Order.Status.DRAFT or getattr(obj, "is_delivered", False)):
            return False
        return super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj and (obj.is_locked or obj.status != Order.Status.DRAFT or getattr(obj, "is_delivered", False)):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and (obj.is_locked or obj.status != Order.Status.DRAFT or getattr(obj, "is_delivered", False)):
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    inlines = (OrderItemInline, OrderPaymentInline)
    list_display = ("id_short", "branch", "order_type", "status", "paid_amount", "created_at", "total_amount", "cogs_amount", "profit_amount")
    list_filter = ("branch", "status", "order_type", "is_delivered")
    search_fields = ("id", "note")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = ("status", "total_amount", "paid_amount", "created_at", "paid_at", "stock_applied", "is_locked", "locked_at", "locked_by")
    fields = ("branch", "order_type", "is_delivered", "status", "note", "total_amount", "paid_amount", "created_at", "paid_at", "stock_applied", "is_locked", "locked_at", "locked_by")

    def has_module_permission(self, request):
        return is_admin_user(request.user)

    def has_view_permission(self, request, obj=None):
        return is_admin_user(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_super_recovery_user(request.user)

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            ro += ["branch"]

        if obj is not None and getattr(obj, "is_locked", False):
            all_fields = [f.name for f in obj._meta.fields]
            ro += all_fields

        if obj is not None and getattr(obj, "is_delivered", False):
            ro += ["is_delivered"]

        return tuple(dict.fromkeys(ro))

    @admin.display(description="ID")
    def id_short(self, obj: Order):
        return str(obj.id)[:8]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_admin_user(request.user):
            return qs
        bid = get_user_branch_id(request.user)
        if not bid:
            return qs.none()
        return qs.filter(branch_id=bid)

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user

        prof = get_profile(request.user)
        if prof and getattr(prof, "is_active", False) and is_cashier_role_value(getattr(prof, "role", None)):
            obj.branch_id = prof.branch_id

        super().save_model(request, obj, form, change)

    @transaction.atomic
    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        order = form.instance

        if getattr(order, "is_locked", False):
            return

        recalc_order_totals(order)
        order.refresh_from_db()

        created_cnt = 0
        payments = (
            order.payments.select_related("account")
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
                actor=request.user,
                reason="Order payment",
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

        recalc_order_totals(order)
        order.refresh_from_db()

        if order.total_amount > 0 and order.paid_amount >= order.total_amount:
            if order.status != Order.Status.PAID:
                order.status = Order.Status.PAID
                order.paid_at = order.paid_at or timezone.now()
                order.paid_by = order.paid_by or request.user
                order.save(update_fields=["status", "paid_at", "paid_by"])

            if getattr(order, "is_delivered", False):
                apply_stock_for_order_if_needed(order)
        else:
            if order.status == Order.Status.PAID:
                raise ValueError("PAID orderni qaytadan DRAFT qilish mumkin emas.")

    def delete_model(self, request, obj):
        delete_order_for_recovery(obj, actor=request.user)
        self.message_user(request, "Buyurtma va unga bog'liq to'lov/cash yozuvlari o'chirildi.", level=messages.SUCCESS)

    def delete_queryset(self, request, queryset):
        deleted_count = delete_orders_for_recovery(queryset=queryset, actor=request.user)
        self.message_user(request, f"{deleted_count} ta buyurtma recovery tartibida o'chirildi.", level=messages.SUCCESS)


@admin.register(KitchenTask)
class KitchenTaskAdmin(admin.ModelAdmin):
    list_display = ("order", "branch", "status", "created_at", "updated_at")
    list_filter = ("branch", "status")
    search_fields = ("order__id", "items_snapshot", "note")
    readonly_fields = ("created_at", "updated_at", "items_snapshot")
    autocomplete_fields = ("order", "branch", "created_by", "updated_by")

    def has_module_permission(self, request):
        return is_admin_user(request.user)

    def has_view_permission(self, request, obj=None):
        return is_admin_user(request.user)

    def has_add_permission(self, request):
        return is_super_recovery_user(request.user)

    def has_change_permission(self, request, obj=None):
        return is_admin_user(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_super_recovery_user(request.user)
