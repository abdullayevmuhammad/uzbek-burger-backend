from __future__ import annotations

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from finance.models import Direction, TxnType
from finance.services import record_cash_txn
from finance.utils import parse_uzs_amount
from inventory.models import BranchProduct
from inventory.units import to_base, from_base
from menu.models import Food, FoodItem, FoodType, SetItem
from sales.models import Order, OrderItem, OrderPayment


class OrderValidationError(ValueError):
    def __init__(self, message: str, *, invalid_items: list[dict] | None = None):
        super().__init__(message)
        self.invalid_items = invalid_items or []


def validate_order_items(branch, raw_items):
    """
    Validate incoming items payload.
    - Ensures qty > 0
    - Filters out invalid/foreign foods
    - Coalesces duplicate foods
    """
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
        except Food.DoesNotExist:
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
    """Order total_amount va paid_amount ni qayta hisoblaydi (idempotent)."""
    o = Order.objects.select_for_update().get(pk=order.pk)

    agg = o.items.aggregate(s=Sum("line_total"))
    o.total_amount = int(agg["s"] or 0)

    paid = o.payments.aggregate(s=Sum("amount"))["s"] or 0
    o.paid_amount = int(paid)

    o.save(update_fields=["total_amount", "paid_amount"])


@transaction.atomic
def add_item(order: Order, *, food, qty: int) -> OrderItem:
    """DRAFT orderga item qo'shadi (bir xil food bo'lsa qty oshiradi)."""
    o = Order.objects.select_for_update().get(pk=order.pk)

    # Muhim qoida:
    #  - DRAFT bo'lmagan order edit qilinmaydi
    #  - TOPSHIRILGAN (stock_applied) orderda item o'zgartirish mumkin emas (stock buziladi)
    #  - YAKUNLANGAN (is_locked) orderda umuman edit yo'q
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


from decimal import Decimal

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

            # ✅ COGS snapshot: shu paytdagi avg_unit_cost bilan
            unit_cost = bp.avg_unit_cost or Decimal("0.00")
            cogs += (unit_cost * need_qty_base)

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

    # ✅ Orderga snapshot yozamiz
    order.cogs_amount = total_cogs
    order.profit_amount = (order.total_amount or Decimal("0.00")) - total_cogs
    order.stock_applied = True
    order.save(update_fields=["cogs_amount", "profit_amount", "stock_applied"])

@transaction.atomic
def apply_stock_for_order_if_needed(order: Order) -> None:
    """Order topshirilgan bo'lsa va stock hali yechilmagan bo'lsa, ingredientlarni yechadi."""
    o = Order.objects.select_for_update().get(pk=order.pk)

    if o.stock_applied:
        return

    if not o.is_delivered:
        raise ValueError("Stock faqat TOPSHIRILGAN (mijozga berilgan) order uchun yechiladi")

    _consume_stock_for_order(o)
    o.stock_applied = True
    o.save(update_fields=["stock_applied"])


@transaction.atomic
def mark_delivered(order: Order, *, by_user=None) -> Order:
    """Orderni 'topshirildi' deb belgilaydi va stockni (1 marta) yechadi."""
    o = Order.objects.select_for_update().get(pk=order.pk)

    if o.is_delivered:
        # baribir stock_applied bo'lmasa, idempotent tarzda yechamiz
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

    # Agar order allaqachon to'liq to'langan bo'lsa -> yakunlaymiz
    if o.status == Order.Status.PAID and not o.is_locked:
        o.is_locked = True
        o.locked_at = timezone.now()
        if by_user is not None:
            o.locked_by = by_user
        o.save(update_fields=["is_locked", "locked_at", "locked_by"])
    return o


@transaction.atomic
def pay_order(order: Order, *, account, amount: int, note: str | None = None, by_user) -> OrderPayment:
    """Orderga to'lov yozadi va kassaga (cash_txn) tushum yozadi."""
    o = Order.objects.select_for_update().get(pk=order.pk)

    if o.is_locked:
        raise ValueError("Order yakunlangan. Endi to'lov qo'shib bo'lmaydi")
    if o.status == Order.Status.CANCELED:
        raise ValueError("Bekor qilingan order uchun to'lov qila olmaysiz.")

    # STAFF faqat o'z filialidagi orderni pay qila oladi
    prof = getattr(by_user, "profile", None)
    if prof and prof.is_active and prof.role == "staff":
        if prof.branch_id != o.branch_id:
            raise ValueError("Forbidden: boshqa filial orderini pay qila olmaysiz.")

    # Account ham shu filialniki bo'lsin
    if account.branch_id != o.branch_id:
        raise ValueError("Payment account boshqa filialga tegishli.")

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

    # cash txn (IN)
    tx = record_cash_txn(
        account=account,
        direction=Direction.IN_,
        txn_type=TxnType.SALE,
        amount=amount_int,
        note=note or f"Order {str(o.id)[:8]} payment",
        occurred_at=timezone.now(),
        ref_type="order_payment",
        ref_id=p.id,
    )
    p.cash_txn = tx
    p.save(update_fields=["cash_txn"])

    # totals update
    recalc_order_totals(o)
    o.refresh_from_db(fields=["total_amount", "paid_amount", "status", "is_delivered", "is_locked"])

    # agar to‘liq yopildi -> PAID
    if o.total_amount > 0 and o.paid_amount >= o.total_amount:
        if o.status != Order.Status.PAID:
            o.status = Order.Status.PAID
            o.paid_at = timezone.now()
            o.paid_by = by_user
            o.save(update_fields=["status", "paid_at", "paid_by"])

        # Agar topshirilgan bo'lsa -> yakunlaymiz
        if o.is_delivered and not o.is_locked:
            o.is_locked = True
            o.locked_at = timezone.now()
            o.locked_by = by_user
            o.save(update_fields=["is_locked", "locked_at", "locked_by"])

    return p


@transaction.atomic
def cancel_order(order: Order, *, by_user=None) -> Order:
    """Safer option: cancel only while DRAFT and unpaid & undelivered."""
    o = Order.objects.select_for_update().get(pk=order.pk)
    if o.is_locked or o.status == Order.Status.PAID:
        raise ValueError("Yakunlangan yoki to'langan orderni bekor qilib bo'lmaydi.")
    if o.is_delivered or o.stock_applied:
        raise ValueError("Topshirilgan orderni bekor qilib bo'lmaydi.")
    if o.paid_amount > 0:
        raise ValueError("To'lov qabul qilingan orderni bekor qilib bo'lmaydi.")

    o.status = Order.Status.CANCELED
    o.save(update_fields=["status"])
    return o


def build_receipt_context(order: Order, *, paper_width: str = "80") -> dict:
    """Receipt uchun kerakli snapshot ma'lumotlarni qaytaradi."""
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
        "paper_width": "58" if str(paper_width) == "58" else "80",
    }
