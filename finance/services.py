# finance/services.py
from django.db import transaction
from django.utils import timezone
from .models import CashTransaction, MoneyAccount
from .utils import parse_uzs_amount

@transaction.atomic
def record_cash_txn(*, account: MoneyAccount, direction: str, txn_type: str, amount: int,
                    note: str | None = None, occurred_at=None, ref_type=None, ref_id=None) -> CashTransaction:
    if occurred_at is None:
        occurred_at = timezone.now()

    # Strong consistency: lock account and rely on ledger as single source of truth.
    acc = MoneyAccount.objects.select_for_update().get(pk=account.pk)

    amount_int = parse_uzs_amount(amount)

    tx = CashTransaction.objects.create(
        branch=acc.branch,
        account=acc,
        direction=direction,      # "in" / "out"
        txn_type=txn_type,        # "sale" / "import" / ...
        amount=amount_int,
        occurred_at=occurred_at,
        note=note,
        ref_type=ref_type,
        ref_id=ref_id,
    )

    return tx
