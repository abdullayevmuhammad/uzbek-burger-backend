from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction

from core.models import Branch
from users.models import StaffProfile
from users.utils import is_super_recovery_user


User = get_user_model()


def ensure_branch_is_operational(branch: Branch | None) -> Branch:
    if branch is None:
        raise ValueError("Filial topilmadi.")
    branch = Branch.objects.get(pk=branch.pk)
    if not branch.is_active:
        raise ValueError("Filial arxivlangan yoki noaktiv. Operatsiya bajarilmadi.")
    return branch


@transaction.atomic
def archive_branch(*, branch: Branch, actor=None) -> Branch:
    branch = Branch.objects.select_for_update().get(pk=branch.pk)
    if not branch.is_active:
        return branch
    branch.is_active = False
    branch.save(update_fields=["is_active"])
    return branch


@transaction.atomic
def purge_branch(*, branch: Branch, actor) -> None:
    if not is_super_recovery_user(actor):
        raise PermissionError("Filialni to'liq purge qilish faqat superuser uchun.")

    branch = Branch.objects.select_for_update().get(pk=branch.pk)

    from finance.models import CashTransaction, MoneyAccount
    from finance.services import recalculate_account_balances
    from inventory.models import BranchProduct, StockImport, StockImportItem
    from menu.models import Food, FoodCategory, FoodItem, SetItem
    from sales.models import Order
    from sales.services import delete_orders_for_recovery

    account_ids: set[str] = set(
        MoneyAccount.objects.filter(branch=branch).values_list("id", flat=True)
    )

    delete_orders_for_recovery(
        queryset=Order.objects.filter(branch=branch),
        actor=actor,
    )

    import_txn_ids = list(
        StockImport.objects.filter(branch=branch, cash_txn__isnull=False).values_list("cash_txn_id", flat=True)
    )
    if import_txn_ids:
        CashTransaction.objects.filter(pk__in=import_txn_ids).delete()

    StockImportItem.objects.filter(stock_import__branch=branch).delete()
    StockImport.objects.filter(branch=branch).delete()

    SetItem.objects.filter(set_food__branch=branch).delete()
    SetItem.objects.filter(food__branch=branch).delete()
    FoodItem.objects.filter(food__branch=branch).delete()
    Food.objects.filter(branch=branch).delete()
    FoodCategory.objects.filter(branch=branch).delete()
    BranchProduct.objects.filter(branch=branch).delete()

    StaffProfile.objects.filter(branch=branch).update(branch=None, is_active=False)

    CashTransaction.objects.filter(branch=branch).delete()
    MoneyAccount.objects.filter(branch=branch).delete()

    if account_ids:
        recalculate_account_balances(account_ids)

    branch.delete()
