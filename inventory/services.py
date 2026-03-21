from decimal import Decimal, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from core.services import ensure_branch_is_operational
from finance.models import Direction, TxnType
from finance.services import record_cash_txn, recalculate_account_balances
from users.utils import get_profile, is_cashier_role_value

from .models import BranchProduct, StockImport, StockImportItem
from .units import from_base, to_base

Q0 = Decimal("0")
Q1 = Decimal("1")


def _money_div(total_cost: int, qty: Decimal) -> int:
    if qty <= Q0:
        raise ValueError("qty must be > 0")
    unit = (Decimal(total_cost) / qty).quantize(Q1, rounding=ROUND_HALF_UP)
    return int(unit)


@transaction.atomic
def post_stock_import(stock_import: StockImport, *, by_user=None) -> None:
    imp = StockImport.objects.select_for_update().select_related("branch", "paid_from_account").get(pk=stock_import.pk)
    ensure_branch_is_operational(imp.branch)

    if by_user is not None:
        prof = get_profile(by_user)
        if prof and getattr(prof, "is_active", False) and is_cashier_role_value(getattr(prof, "role", None)):
            if prof.branch_id != imp.branch_id:
                raise ValueError("Forbidden: boshqa filial importini POST qila olmaysiz.")

    if imp.status == StockImport.Status.POSTED:
        return

    items = imp.items.select_related("product").all()
    if not items:
        raise ValueError("Import itemlari yo'q. Avval item qo'shing.")

    total_cost = imp.items.aggregate(s=Sum("line_total_cost"))["s"] or 0
    if total_cost < 0:
        raise ValueError("total_cost noto'g'ri")

    if imp.paid_from_account_id:
        acc = imp.paid_from_account

        if acc.branch_id != imp.branch_id:
            raise ValueError("paid_from_account boshqa filialga tegishli. To'g'ri account tanlang.")
        if acc.balance_cache < int(total_cost):
            raise ValueError(f"Kassada pul yetarli emas. Balance={acc.balance_cache}, kerak={int(total_cost)}")

        if imp.cash_txn_id is None:
            tx = record_cash_txn(
                account=acc,
                direction=Direction.OUT,
                txn_type=TxnType.IMPORT,
                amount=int(total_cost),
                actor=by_user,
                reason="Stock import payment",
                note=f"Stock import {str(imp.id)[:8]}",
                ref_type="stock_import",
                ref_id=imp.id,
            )
            imp.cash_txn = tx
            imp.save(update_fields=["cash_txn"])

    for it in items:
        qty_base = to_base(it.qty, it.product.count_type)
        unit_cost = _money_div(it.line_total_cost, qty_base)

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

        old_qty_base = to_base(bp.stock_qty, bp.product.count_type)
        new_qty_base = old_qty_base + qty_base

        if old_qty_base <= Q0:
            new_avg = unit_cost
        else:
            numerator = (old_qty_base * Decimal(bp.avg_unit_cost)) + (qty_base * Decimal(unit_cost))
            new_avg_dec = (numerator / new_qty_base).quantize(Q1, rounding=ROUND_HALF_UP)
            new_avg = int(new_avg_dec)

        bp.stock_qty = from_base(new_qty_base, bp.product.count_type)
        bp.last_unit_cost = unit_cost
        bp.avg_unit_cost = new_avg
        bp.save(update_fields=["stock_qty", "last_unit_cost", "avg_unit_cost"])

    imp.status = StockImport.Status.POSTED
    imp.posted_by = by_user
    imp.posted_at = timezone.now()
    imp.save(update_fields=["status", "posted_by", "posted_at"])


@transaction.atomic
def reverse_stock_import(stock_import: StockImport, *, actor) -> None:
    from users.utils import is_super_recovery_user

    if not is_super_recovery_user(actor):
        raise PermissionError("Importni to'liq qaytarish faqat superuser uchun.")

    imp = StockImport.objects.select_for_update().select_related("branch", "paid_from_account").get(pk=stock_import.pk)
    if imp.status != StockImport.Status.POSTED:
        imp.delete()
        return

    items = list(imp.items.select_related("product"))
    if not items:
        imp.delete()
        return

    account_ids = []
    if imp.cash_txn_id:
        account_ids.append(imp.cash_txn.account_id)
        imp.cash_txn.delete()

    for it in items:
        qty_base = to_base(it.qty, it.product.count_type)
        unit_cost = _money_div(it.line_total_cost, qty_base)

        bp = (
            BranchProduct.objects.select_for_update()
            .filter(branch=imp.branch, product=it.product)
            .first()
        )
        if bp is None:
            raise ValueError(f"BranchProduct topilmadi, qaytarib bo'lmaydi: {it.product}")

        old_qty_base = to_base(bp.stock_qty, bp.product.count_type)
        if old_qty_base < qty_base:
            raise ValueError(f"Qaytarib bo'lmaydi, stock yetarli emas: {it.product.name}")

        new_qty_base = old_qty_base - qty_base
        prev_total_cost = Decimal(bp.avg_unit_cost) * old_qty_base
        new_total_cost = prev_total_cost - (Decimal(unit_cost) * qty_base)

        bp.stock_qty = from_base(new_qty_base, bp.product.count_type)
        if new_qty_base > 0:
            new_avg = (new_total_cost / new_qty_base).quantize(Q1, rounding=ROUND_HALF_UP)
            bp.avg_unit_cost = int(new_avg)
        else:
            bp.avg_unit_cost = 0
        bp.last_unit_cost = unit_cost
        bp.save(update_fields=["stock_qty", "avg_unit_cost", "last_unit_cost"])

    StockImportItem.objects.filter(stock_import=imp).delete()
    imp.delete()

    if account_ids:
        recalculate_account_balances(account_ids)
