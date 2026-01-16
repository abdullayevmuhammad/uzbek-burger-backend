# inventory/services.py
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction, IntegrityError
from django.db.models import Sum

from .models import StockImport, BranchProduct
from finance.models import Direction, TxnType
from finance.services import record_cash_txn
from django.utils import timezone
Q0 = Decimal("0")
Q1 = Decimal("1")

def _money_div(total_cost: int, qty: Decimal) -> int:
    # unit cost (so'm) = line_total_cost / qty, rounded to int
    if qty <= Q0:
        raise ValueError("qty must be > 0")
    unit = (Decimal(total_cost) / qty).quantize(Q1, rounding=ROUND_HALF_UP)
    return int(unit)

@transaction.atomic
def post_stock_import(stock_import: StockImport, *, by_user=None) -> None:
    """
    POST = real apply:
      - BranchProduct.stock_qty oshadi
      - avg_unit_cost / last_unit_cost yangilanadi
      - agar paid_from_account bo'lsa: pul yetarliligini tekshiradi va OUT cash_txn yozadi
      - status POSTED bo'ladi
    Idempotent: qayta chaqirilsa 2 marta qo'shmaydi.
    """
    imp = StockImport.objects.select_for_update().get(pk=stock_import.pk)
    # STAFF faqat o'z filialidagi importni post qila oladi
    if by_user is not None:
        prof = getattr(by_user, "profile", None)
        if prof and prof.is_active and prof.role == "staff":
            if prof.branch_id != imp.branch_id:
                raise ValueError("Forbidden: boshqa filial importini POST qila olmaysiz.")


    if imp.status == StockImport.Status.POSTED:
        return  # idempotent

    items = imp.items.select_related("product").all()
    if not items:
        raise ValueError("Import itemlari yo'q. Avval item qo'shing.")

    total_cost = imp.items.aggregate(s=Sum("line_total_cost"))["s"] or 0
    if total_cost < 0:
        raise ValueError("total_cost noto'g'ri")

    # 1) Agar to'lov ko'rsatilgan bo'lsa, pul yetarliligini tekshiramiz va OUT yozamiz
    if imp.paid_from_account_id:
        acc = imp.paid_from_account

        # Branch safety: account shu filialniki bo‘lsin
        if acc.branch_id != imp.branch_id:
            raise ValueError("paid_from_account boshqa filialga tegishli. To'g'ri account tanlang.")

        # Pul yetarlimi?
        if acc.balance_cache < int(total_cost):
            raise ValueError(f"Kassada pul yetarli emas. Balance={acc.balance_cache}, kerak={int(total_cost)}")

        # OUT txn: faqat bir marta yozilishi kerak
        if imp.cash_txn_id is None:
            tx = record_cash_txn(
                account=acc,
                direction=Direction.OUT,
                txn_type=TxnType.IMPORT,
                amount=int(total_cost),
                note=f"Stock import {str(imp.id)[:8]}",
                ref_type="stock_import",
                ref_id=imp.id,
            )
            imp.cash_txn = tx
            imp.save(update_fields=["cash_txn"])

    # 2) Stock + cost apply
    for it in items:
        unit_cost = _money_div(it.line_total_cost, it.qty)

        bp = (
            BranchProduct.objects.select_for_update()
            .filter(branch=imp.branch, product=it.product)
            .first()
        )

        if bp is None:
            try:
                bp = BranchProduct.objects.create(branch=imp.branch, product=it.product)
            except IntegrityError:
                bp = BranchProduct.objects.select_for_update().get(branch=imp.branch, product=it.product)

        old_qty = bp.stock_qty
        new_qty = old_qty + it.qty

        if old_qty <= Q0:
            new_avg = unit_cost
        else:
            numerator = (old_qty * Decimal(bp.avg_unit_cost)) + (it.qty * Decimal(unit_cost))
            new_avg_dec = (numerator / new_qty).quantize(Q1, rounding=ROUND_HALF_UP)
            new_avg = int(new_avg_dec)

        bp.stock_qty = new_qty
        bp.last_unit_cost = unit_cost
        bp.avg_unit_cost = new_avg
        bp.save(update_fields=["stock_qty", "last_unit_cost", "avg_unit_cost"])

    # 3) Status POSTED
    imp.status = StockImport.Status.POSTED
    imp.posted_by = by_user
    imp.posted_at = timezone.now()
    imp.save(update_fields=["status", "posted_by", "posted_at"])
