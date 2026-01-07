from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from sales.models import Order, OrderItem, OrderPayment
from menu.models import FoodItem
from inventory.models import BranchProduct
from finance.models import Direction, TxnType
from finance.services import record_cash_txn


@transaction.atomic
def recalc_order_totals(order: Order) -> None:
    o = Order.objects.select_for_update().get(pk=order.pk)
    agg = o.items.aggregate(s=Sum("line_total"))
    o.total_amount = int(agg["s"] or 0)
    paid = o.payments.aggregate(s=Sum("amount"))["s"] or 0
    o.paid_amount = int(paid)
    o.save(update_fields=["total_amount", "paid_amount"])


@transaction.atomic
def add_item(order: Order, food, qty: int) -> OrderItem:
    o = Order.objects.select_for_update().get(pk=order.pk)
    if o.status != Order.Status.DRAFT:
        raise ValueError("Only DRAFT orders can be edited")

    unit_price = int(food.sell_price)
    line_total = unit_price * int(qty)

    item, created = OrderItem.objects.get_or_create(
        order=o, food=food,
        defaults={"qty": qty, "unit_price": unit_price, "line_total": line_total},
    )
    if not created:
        item.qty += int(qty)
        item.line_total = item.unit_price * item.qty
        item.save(update_fields=["qty", "line_total"])

    recalc_order_totals(o)
    return item


def _consume_stock_for_paid_order(order: Order) -> None:
    # har bir order item -> food recipe -> branch stockdan yechamiz
    items = order.items.select_related("food").all()
    for oi in items:
        recipe = FoodItem.objects.filter(food=oi.food).select_related("product")
        for ri in recipe:
            need_qty = ri.qty * oi.qty  # Decimal * int = Decimal
            bp = (BranchProduct.objects
                  .select_for_update()
                  .get(branch=order.branch, product=ri.product))

            # Strict: minusga tushirmaymiz
            if bp.stock_qty < need_qty:
                raise ValueError(f"Stock yetarli emas: {ri.product.name} ({bp.stock_qty} < {need_qty})")

            bp.stock_qty = bp.stock_qty - need_qty
            bp.save(update_fields=["stock_qty"])


@transaction.atomic
def pay_order(order: Order, *, account, amount: int, note: str | None = None, by_user) -> OrderPayment:
    o = Order.objects.select_for_update().get(pk=order.pk)
    if o.status == Order.Status.CANCELED:
        raise ValueError("Canceled order cannot be paid")
    if o.status == Order.Status.PAID:
        raise ValueError("Order already PAID")

    recalc_order_totals(o)
    due = o.total_amount - o.paid_amount
    if amount <= 0:
        raise ValueError("amount must be > 0")
    if amount > due:
        raise ValueError(f"amount katta: due={due}")

    p = OrderPayment.objects.create(order=o, account=account, amount=amount)

    # cash txn (IN)
    tx = record_cash_txn(
        account=account,
        direction=Direction.IN_,
        txn_type=TxnType.SALE,
        amount=amount,
        note=note or f"Order {str(o.id)[:8]} payment",
        occurred_at=timezone.now(),
        ref_type="order_payment",
        ref_id=p.id,
    )
    p.cash_txn = tx
    p.save(update_fields=["cash_txn"])

    # totals update
    recalc_order_totals(o)

    # agar to‘liq yopildi -> PAID + stock yechish
    if o.total_amount > 0 and o.paid_amount >= o.total_amount:
        o.status = Order.Status.PAID
        o.paid_at = timezone.now()
        o.paid_by = by_user
        o.save(update_fields=["status", "paid_at", "paid_by"])

    return p


@transaction.atomic
def apply_stock_for_order_if_needed(order: Order) -> None:
    o = Order.objects.select_for_update().get(pk=order.pk)

    if o.stock_applied:
        return  # allaqachon yechilgan

    if o.status != Order.Status.PAID:
        raise ValueError("Stock faqat PAID order uchun yechiladi")

    _consume_stock_for_paid_order(o)
    o.stock_applied = True
    o.save(update_fields=["stock_applied"])
