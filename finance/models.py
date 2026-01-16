import uuid
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Sum, Case, When, IntegerField, F, Value

from core.models import Branch


# =====================
# ENUMS
# =====================
class AccountKind(models.TextChoices):
    CASH = "cash", "Cash"
    CARD = "card", "Card"
    BANK = "bank", "Bank"
    OTHER = "other", "Other"


class Direction(models.TextChoices):
    IN_ = "in", "IN"
    OUT = "out", "OUT"


class TxnType(models.TextChoices):
    SALE = "sale", "Sale"
    IMPORT = "import", "Import"
    EXPENSE = "expense", "Expense"
    TRANSFER = "transfer", "Transfer"
    ADJUST = "adjust", "Adjust"


# =====================
# MONEY ACCOUNT (KASSA)
# =====================
class MoneyAccount(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="money_accounts",
    )
    name = models.CharField(max_length=80)  # Cash, Card, Terminal
    kind = models.CharField(
        max_length=10,
        choices=AccountKind.choices,
        default=AccountKind.CASH,
    )
    is_active = models.BooleanField(default=True)

    # Cache (asosiy haqiqat — CashTransaction lar)
    balance_cache = models.BigIntegerField(default=0)  # so'm

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "name"],
                name="uniq_branch_account_name",
            )
        ]
        verbose_name = "Kassa"
        verbose_name_plural = "Kassalar"

    def __str__(self):
        return f"{self.branch.name} | {self.name}"


# =====================
# CASH TRANSACTION
# =====================
class CashTransaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="cash_txns",
    )
    account = models.ForeignKey(
        MoneyAccount,
        on_delete=models.PROTECT,
        related_name="txns",
    )

    direction = models.CharField(
        max_length=5,
        choices=Direction.choices,
    )
    txn_type = models.CharField(
        max_length=12,
        choices=TxnType.choices,
    )

    amount = models.BigIntegerField(
        validators=[MinValueValidator(1)]
    )  # so'm

    occurred_at = models.DateTimeField()
    note = models.CharField(max_length=255, blank=True, null=True)

    # Audit / link (admin kiritmaydi)
    ref_type = models.CharField(max_length=30, blank=True, null=True)
    ref_id = models.UUIDField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["branch", "occurred_at"]),
            models.Index(fields=["account", "occurred_at"]),
        ]
        verbose_name = "Pul o'tkazmasi"
        verbose_name_plural = "Pul o'tkazmalari"

    def __str__(self):
        sign = "+" if self.direction == Direction.IN_ else "-"
        return f"{self.account} {sign}{self.amount}"

    # =====================
    # BALANCE RECALC
    # =====================
    def _recalc_balance(self):
        agg = CashTransaction.objects.filter(
            account_id=self.account_id
        ).aggregate(
            bal=Sum(
                Case(
                    When(
                        direction=Direction.IN_,
                        then=F("amount"),
                    ),
                    When(
                        direction=Direction.OUT,
                        then=Value(0) - F("amount"),
                    ),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            )
        )

        self.account.balance_cache = agg["bal"] or 0
        self.account.save(update_fields=["balance_cache"])

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            transaction.on_commit(self._recalc_balance)
