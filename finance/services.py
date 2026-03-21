from django.db import transaction
from django.utils import timezone

from .models import (
    CashTransaction,
    Direction,
    MoneyAccount,
    NON_SALES_TXN_TYPES,
    TxnType,
    recalculate_balance_cache,
)
from .utils import parse_uzs_amount
from users.utils import is_super_recovery_user


def recalculate_account_balances(account_ids) -> None:
    for account_id in set(account_ids):
        recalculate_balance_cache(account_id)


@transaction.atomic
def record_cash_txn(
    *,
    account: MoneyAccount,
    direction: str,
    txn_type: str,
    amount: int,
    actor=None,
    reason: str | None = None,
    note: str | None = None,
    occurred_at=None,
    ref_type=None,
    ref_id=None,
) -> CashTransaction:
    if occurred_at is None:
        occurred_at = timezone.now()

    acc = MoneyAccount.objects.select_for_update().select_related("branch").get(pk=account.pk)
    if not acc.branch.is_active:
        raise ValueError("Arxivlangan filial uchun cash transaction yozib bo'lmaydi.")

    amount_int = parse_uzs_amount(amount)

    tx = CashTransaction.objects.create(
        branch=acc.branch,
        account=acc,
        actor=actor,
        direction=direction,
        txn_type=txn_type,
        amount=amount_int,
        occurred_at=occurred_at,
        reason=reason or "",
        note=note,
        ref_type=ref_type,
        ref_id=ref_id,
    )

    return tx


@transaction.atomic
def create_cash_adjustment(
    *,
    account: MoneyAccount,
    txn_type: str,
    amount: int,
    reason: str,
    note: str,
    actor,
    occurred_at=None,
    direction: str | None = None,
) -> CashTransaction:
    if txn_type not in NON_SALES_TXN_TYPES:
        raise ValueError("Manual cash correction uchun noto'g'ri txn_type.")
    if not is_super_recovery_user(actor):
        raise PermissionError("Manual cash correction faqat superuser uchun.")

    if txn_type == TxnType.OPENING_BALANCE:
        direction = Direction.IN_
    elif txn_type == TxnType.CASH_IN:
        direction = Direction.IN_
    elif txn_type == TxnType.CASH_OUT:
        direction = Direction.OUT
    elif direction not in {Direction.IN_, Direction.OUT}:
        raise ValueError("cash_adjustment uchun direction tanlanishi kerak.")

    return record_cash_txn(
        account=account,
        direction=direction,
        txn_type=txn_type,
        amount=amount,
        actor=actor,
        reason=reason,
        note=note,
        occurred_at=occurred_at,
    )


def get_branch_cash_history(branch):
    qs = CashTransaction.objects.filter(branch=branch).select_related("account", "actor").order_by("-occurred_at", "-created_at")
    return {
        "sales": qs.order_payments(),
        "non_sales": qs.non_sales(),
        "adjustments": qs.adjustments(),
    }
