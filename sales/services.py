from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.services import ensure_branch_is_operational
from finance.models import CashTransaction, Direction, TxnType
from finance.services import recalculate_account_balances, record_cash_txn
from finance.utils import parse_uzs_amount
from inventory.models import BranchProduct
from inventory.units import from_base, to_base
from menu.models import Food, FoodItem, FoodType, SetItem
from sales.models import Order, OrderItem, OrderPayment, KitchenTask
from users.utils import get_profile, is_cashier_role_value, is_super_recovery_user


class OrderValidationError(ValueError):
    def __init__(self, message: str, *, invalid_items: list[dict] | None = None):
        super().__init__(message)
        self.invalid_items = invalid_items or []


def validate_order_items(branch, raw_items):
    if not isinstance(raw_items, list):
        raise ValueError("Items payload xato.")

    valid = {}
    invalid_items: list[dict] = []
    for index, it in enumerate(raw_items, start=1):
        if not isinstance(it, dict):
            invalid_items.append({"index": index, "reason": "format"})
            continue

        food_id = str((it.get("food") or "")).strip()
        try:
            qty = int(it.get("qty") or 0)
        except Exception:
            invalid_items.append({"index": index, "food": food_id, "reason": "qty"})
            continue

        if not food_id or qty <= 0:
            invalid_items.append({"index": index, "food": food_id, "reason": "qty"})
            continue

        try:
            food = Food.objects.get(id=food_id, branch=branch, is_active=True)
        except (Food.DoesNotExist, ValidationError, ValueError):
            invalid_items.append({"index": index, "food": food_id, "reason": "food"})
            continue

        if food_id in valid:
            valid[food_id]["qty"] += qty
        else:
            valid[food_id] = {"food": food, "qty": qty}

    if invalid_items:
        details = []
        for item in invalid_items:
            reason = item["reason"]
            if reason == "qty":
                details.append(f"#{item['index']}: miqdor noto'g'ri")
            elif reason == "food":
                details.append(f"#{item['index']}: taom topilmadi yoki boshqa filialniki")
            else:
                details.append(f"#{item['index']}: format noto'g'ri")
        raise OrderValidationError(
            "Buyurtmada xato itemlar bor: " + "; ".join(details),
            invalid_items=invalid_items,
        )

    items = list(valid.values())
    if not items:
        raise OrderValidationError("Kamida bitta to'g'ri taom tanlang.")
    return items


@transaction.atomic
def create_order_with_items(*, branch, created_by, order_type, note, items: list[dict]) -> Order:
    ensure_branch_is_operational(branch)
    validated = validate_order_items(branch, items)

    order = Order.objects.create(
        branch=branch,
        order_type=order_type,
        note=note,
        created_by=created_by,
        status=Order.Status.DRAFT,
    )

    total = 0
    for it in validated:
        food = it["food"]
        qty = it["qty"]
        unit_price = int(food.sell_price)
        line_total = unit_price * qty
        total += line_total

        oi = OrderItem(
            order=order,
            food=food,
            qty=qty,
            unit_price=unit_price,
            line_total=line_total,
        )
        oi.full_clean()
        oi.save()

    order.total_amount = total
    order.paid_amount = 0
    order.save(update_fields=["total_amount", "paid_amount"])
    return order


@transaction.atomic
def recalc_order_totals(order: Order) -> None:
    o = Order.objects.select_for_update().get(pk=order.pk)

    agg = o.items.aggregate(s=Sum("line_total"))
    o.total_amount = int(agg["s"] or 0)

    paid = o.payments.aggregate(s=Sum("amount"))["s"] or 0
    o.paid_amount = int(paid)

    o.save(update_fields=["total_amount", "paid_amount"])


@transaction.atomic
def add_item(order: Order, *, food, qty: int) -> OrderItem:
    o = Order.objects.select_for_update().get(pk=order.pk)

    if o.is_locked:
        raise ValueError("Order yakunlangan. Endi item qo'shib bo'lmaydi")
    if o.is_delivered or o.stock_applied:
        raise ValueError("Topshirilgan orderni tahrirlab bo'lmaydi")
    if o.status == Order.Status.CANCELED:
        raise ValueError("Bekor qilingan orderni tahrirlab bo'lmaydi.")
    if o.status != Order.Status.DRAFT:
        raise ValueError("Only DRAFT orders can be edited")

    unit_price = int(food.sell_price)
    line_total = unit_price * int(qty)

    item, created = OrderItem.objects.get_or_create(
        order=o,
        food=food,
        defaults={"qty": qty, "unit_price": unit_price, "line_total": line_total},
    )
    if not created:
        item.qty += int(qty)
        item.line_total = int(item.unit_price) * int(item.qty)
        item.save(update_fields=["qty", "line_total"])

    recalc_order_totals(o)
    return item


def _consume_stock_for_order(order: Order) -> None:
    if order.stock_applied:
        return

    total_cogs = Decimal("0.00")

    def consume_food(food, qty_multiplier: int) -> Decimal:
        cogs = Decimal("0.00")
        recipe = FoodItem.objects.filter(food=food).select_related("product")

        for ri in recipe:
            need_qty_base = to_base(ri.qty, ri.product.count_type) * int(qty_multiplier)

            bp = (
                BranchProduct.objects.select_for_update()
                .filter(branch=order.branch, product=ri.product)
                .first()
            )
            if bp is None:
                raise ValueError(f"Stock topilmadi: {ri.product.name}. Avval import qiling.")

            stock_qty_base = to_base(bp.stock_qty, ri.product.count_type)
            if stock_qty_base < need_qty_base:
                raise ValueError(f"Stock yetarli emas: {ri.product.name} ({stock_qty_base} < {need_qty_base})")

            unit_cost = bp.avg_unit_cost or Decimal("0.00")
            cogs += unit_cost * need_qty_base

            new_stock_base = stock_qty_base - need_qty_base
            bp.stock_qty = from_base(new_stock_base, ri.product.count_type)
            bp.save(update_fields=["stock_qty"])

        return cogs

    items = order.items.select_related("food").all()

    for oi in items:
        f = oi.food

        if f.type in [FoodType.FASTFOOD, FoodType.DRINK]:
            total_cogs += consume_food(f, oi.qty)
            continue

        if f.type == FoodType.SET:
            set_components = SetItem.objects.filter(set_food=f).select_related("food")
            if not set_components.exists():
                raise ValueError(f"Set tarkibi bo'sh: {f.name}. Avval SetItem qo'shing.")

            for si in set_components:
                total_qty = int(oi.qty) * int(si.qty)
                total_cogs += consume_food(si.food, total_qty)
            continue

        raise ValueError(f"Food type not supported for stock consume: {f.type}")

    order.cogs_amount = total_cogs
    order.profit_amount = (order.total_amount or Decimal("0.00")) - total_cogs
    order.stock_applied = True
    order.save(update_fields=["cogs_amount", "profit_amount", "stock_applied"])


def _restore_stock_for_order(order: Order) -> None:
    items = order.items.select_related("food").all()

    def add_back(food, qty_multiplier: int):
        recipe = FoodItem.objects.filter(food=food).select_related("product")
        for ri in recipe:
            qty_base = to_base(ri.qty, ri.product.count_type) * int(qty_multiplier)
            bp, _ = BranchProduct.objects.select_for_update().get_or_create(
                branch=order.branch,
                product=ri.product,
                defaults={"stock_qty": from_base(Decimal("0"), ri.product.count_type), "avg_unit_cost": 0},
            )
            current_base = to_base(bp.stock_qty, ri.product.count_type)
            bp.stock_qty = from_base(current_base + qty_base, ri.product.count_type)
            bp.save(update_fields=["stock_qty"])

    for oi in items:
        f = oi.food
        if f.type in [FoodType.FASTFOOD, FoodType.DRINK]:
            add_back(f, oi.qty)
            continue
        if f.type == FoodType.SET:
            set_components = SetItem.objects.filter(set_food=f).select_related("food")
            for si in set_components:
                total_qty = int(oi.qty) * int(si.qty)
                add_back(si.food, total_qty)
            continue


@transaction.atomic
def apply_stock_for_order_if_needed(order: Order) -> None:
    o = Order.objects.select_for_update().select_related("branch").get(pk=order.pk)
    ensure_branch_is_operational(o.branch)

    if o.stock_applied:
        return

    if not o.is_delivered:
        raise ValueError("Stock faqat TOPSHIRILGAN (mijozga berilgan) order uchun yechiladi")

    _consume_stock_for_order(o)
    o.stock_applied = True
    o.save(update_fields=["stock_applied"])


@transaction.atomic
def mark_delivered(order: Order, *, by_user=None) -> Order:
    o = Order.objects.select_for_update().select_related("branch").get(pk=order.pk)
    ensure_branch_is_operational(o.branch)

    if o.is_delivered:
        apply_stock_for_order_if_needed(o)
        return o

    if o.is_locked:
        raise ValueError("Order yakunlangan. Topshirish mumkin emas.")
    if o.status == Order.Status.CANCELED:
        raise ValueError("Bekor qilingan orderni topshirib bo'lmaydi.")
    if not o.items.exists():
        raise ValueError("Bo'sh orderni topshirib bo'lmaydi.")

    o.is_delivered = True
    o.delivered_at = timezone.now()
    if by_user is not None:
        o.delivered_by = by_user
    o.save(update_fields=["is_delivered", "delivered_at", "delivered_by"])

    apply_stock_for_order_if_needed(o)

    if o.status == Order.Status.PAID and not o.is_locked:
        o.is_locked = True
        o.locked_at = timezone.now()
        if by_user is not None:
            o.locked_by = by_user
        o.save(update_fields=["is_locked", "locked_at", "locked_by"])
    return o


@transaction.atomic
def pay_order(order: Order, *, account, amount: int, note: str | None = None, by_user) -> OrderPayment:
    o = Order.objects.select_for_update().select_related("branch").get(pk=order.pk)
    ensure_branch_is_operational(o.branch)

    if o.is_locked:
        raise ValueError("Order yakunlangan. Endi to'lov qo'shib bo'lmaydi")
    if o.status == Order.Status.CANCELED:
        raise ValueError("Bekor qilingan order uchun to'lov qila olmaysiz.")

    prof = get_profile(by_user)
    if prof and getattr(prof, "is_active", False) and is_cashier_role_value(getattr(prof, "role", None)):
        if prof.branch_id != o.branch_id:
            raise ValueError("Forbidden: boshqa filial orderini pay qila olmaysiz.")

    if account.branch_id != o.branch_id:
        raise ValueError("Payment account boshqa filialga tegishli.")
    if not account.branch.is_active:
        raise ValueError("Arxivlangan filial uchun payment qabul qilib bo'lmaydi.")

    if o.status == Order.Status.PAID:
        raise ValueError("Order already PAID")

    recalc_order_totals(o)
    o.refresh_from_db(fields=["total_amount", "paid_amount", "status", "is_delivered", "is_locked"])
    due = o.total_amount - o.paid_amount
    amount_int = parse_uzs_amount(amount)
    if amount_int <= 0:
        raise ValueError("To'lov summasi > 0 bo'lishi kerak.")
    if amount_int > due:
        raise ValueError(f"To'lov summasi qoldiqdan katta: due={due}")

    p = OrderPayment.objects.create(order=o, account=account, amount=amount_int)

    tx = record_cash_txn(
        account=account,
        direction=Direction.IN_,
        txn_type=TxnType.SALE,
        amount=amount_int,
        actor=by_user,
        reason="Order payment",
        note=note or f"Order {str(o.id)[:8]} payment",
        occurred_at=timezone.now(),
        ref_type="order_payment",
        ref_id=p.id,
    )
    p.cash_txn = tx
    p.save(update_fields=["cash_txn"])

    recalc_order_totals(o)
    o.refresh_from_db(fields=["total_amount", "paid_amount", "status", "is_delivered", "is_locked"])

    if o.total_amount > 0 and o.paid_amount >= o.total_amount:
        if o.status != Order.Status.PAID:
            o.status = Order.Status.PAID
            o.paid_at = timezone.now()
            o.paid_by = by_user
            o.save(update_fields=["status", "paid_at", "paid_by"])

        if o.is_delivered and not o.is_locked:
            o.is_locked = True
            o.locked_at = timezone.now()
            o.locked_by = by_user
            o.save(update_fields=["is_locked", "locked_at", "locked_by"])

    return p


@transaction.atomic
def cancel_order(order: Order, *, by_user=None) -> Order:
    o = Order.objects.select_for_update().select_related("branch").get(pk=order.pk)
    ensure_branch_is_operational(o.branch)
    if o.is_locked or o.status == Order.Status.PAID:
        raise ValueError("Yakunlangan yoki to'langan orderni bekor qilib bo'lmaydi.")
    if o.is_delivered or o.stock_applied:
        raise ValueError("Topshirilgan orderni bekor qilib bo'lmaydi.")
    if o.paid_amount > 0:
        raise ValueError("To'lov qabul qilingan orderni bekor qilib bo'lmaydi.")

    o.status = Order.Status.CANCELED
    o.save(update_fields=["status"])
    return o


@transaction.atomic
def delete_order_for_recovery(order: Order, *, actor) -> None:
    if not is_super_recovery_user(actor):
        raise PermissionError("Orderni recovery delete qilish faqat superuser uchun.")

    o = Order.objects.select_for_update().get(pk=order.pk)
    if o.stock_applied:
        _restore_stock_for_order(o)

    payments = list(
        OrderPayment.objects.filter(order=o).select_related("cash_txn")
    )
    account_ids = [p.cash_txn.account_id for p in payments if p.cash_txn_id]
    cash_txn_ids = [p.cash_txn_id for p in payments if p.cash_txn_id]

    if cash_txn_ids:
        CashTransaction.objects.filter(pk__in=cash_txn_ids).delete()
    OrderPayment.objects.filter(order=o).delete()
    OrderItem.objects.filter(order=o).delete()
    o.delete()

    if account_ids:
        recalculate_account_balances(account_ids)


@transaction.atomic
def delete_orders_for_recovery(*, queryset, actor) -> int:
    if not is_super_recovery_user(actor):
        raise PermissionError("Orderlarni recovery delete qilish faqat superuser uchun.")

    order_ids = list(queryset.values_list("id", flat=True))
    if not order_ids:
        return 0

    payments = list(
        OrderPayment.objects.filter(order_id__in=order_ids).select_related("cash_txn")
    )
    account_ids = [p.cash_txn.account_id for p in payments if p.cash_txn_id]
    cash_txn_ids = [p.cash_txn_id for p in payments if p.cash_txn_id]

    if cash_txn_ids:
        CashTransaction.objects.filter(pk__in=cash_txn_ids).delete()
    OrderPayment.objects.filter(order_id__in=order_ids).delete()
    OrderItem.objects.filter(order_id__in=order_ids).delete()
    deleted_count, _ = Order.objects.filter(pk__in=order_ids).delete()

    if account_ids:
        recalculate_account_balances(account_ids)

    return deleted_count


def build_receipt_context(order: Order) -> dict:
    o = (
        Order.objects.select_related("branch", "created_by", "paid_by", "delivered_by")
        .prefetch_related("items__food", "payments__account")
        .get(pk=order.pk)
    )

    items = []
    for it in o.items.all():
        items.append(
            {
                "name": it.food.name,
                "qty": it.qty,
                "unit_price": int(it.unit_price),
                "line_total": int(it.line_total),
            }
        )

    payments = []
    for p in o.payments.all().order_by("created_at"):
        payments.append(
            {
                "amount": int(p.amount),
                "account": p.account.name,
                "created_at": p.created_at,
            }
        )

    due = max(0, int(o.total_amount) - int(o.paid_amount))

    return {
        "order": o,
        "branch": o.branch,
        "items": items,
        "payments": payments,
        "due": due,
        "paid_amount": int(o.paid_amount),
        "total_amount": int(o.total_amount),
        "paper_width": "58",
    }


@transaction.atomic
def ensure_kitchen_task(order: Order, *, actor=None) -> KitchenTask:
    o = Order.objects.select_related("branch").get(pk=order.pk)
    task, created = KitchenTask.objects.select_for_update().get_or_create(
        order=o,
        defaults={
            "branch": o.branch,
            "created_by": actor,
            "updated_by": actor,
        },
    )
    task.refresh_from_order()
    task.updated_by = actor
    task.save(update_fields=["items_snapshot", "updated_by", "updated_at"])
    return task
