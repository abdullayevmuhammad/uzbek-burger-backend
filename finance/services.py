# finance/services.py
from django.db import transaction
from django.utils import timezone
from .models import CashTransaction, MoneyAccount

@transaction.atomic
def record_cash_txn(*, account: MoneyAccount, direction: str, txn_type: str, amount: int,
                    note: str | None = None, occurred_at=None, ref_type=None, ref_id=None) -> CashTransaction:
    if occurred_at is None:
        occurred_at = timezone.now()

    acc = MoneyAccount.objects.select_for_update().get(pk=account.pk)

    tx = CashTransaction.objects.create(
        branch=acc.branch,
        account=acc,
        direction=direction,      # "in" / "out"
        txn_type=txn_type,        # "sale" / "import" / ...
        amount=amount,
        occurred_at=occurred_at,
        note=note,
        ref_type=ref_type,
        ref_id=ref_id,
    )

    # cache update
    if direction == "in":
        acc.balance_cache += amount
    else:
        acc.balance_cache -= amount
    acc.save(update_fields=["balance_cache"])

    return tx
