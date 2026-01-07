import uuid
from django.db import models
from django.core.validators import MinValueValidator
from core.models import Branch


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


class MoneyAccount(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="money_accounts")
    name = models.CharField(max_length=80)  # "Cash", "Card", ...
    kind = models.CharField(max_length=10, choices=AccountKind.choices, default=AccountKind.CASH)
    is_active = models.BooleanField(default=True)

    # tez ko‘rish uchun cache. Asosiy haqiqat: CashTransaction lar yig‘indisi
    balance_cache = models.BigIntegerField(default=0)  # so‘mda

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["branch", "name"], name="uniq_branch_account_name"),
        ]

    def __str__(self):
        return f"{self.branch.name} | {self.name}"


class CashTransaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="cash_txns")
    account = models.ForeignKey(MoneyAccount, on_delete=models.PROTECT, related_name="txns")

    direction = models.CharField(max_length=5, choices=Direction.choices)
    txn_type = models.CharField(max_length=12, choices=TxnType.choices)

    amount = models.BigIntegerField(validators=[MinValueValidator(1)])  # so‘mda
    occurred_at = models.DateTimeField()
    note = models.CharField(max_length=255, blank=True, null=True)

    # manba (qaysi hujjatdan kelganini yozib qo‘yamiz)
    ref_type = models.CharField(max_length=30, blank=True, null=True)  # "order_payment", "stock_import", "expense"
    ref_id = models.UUIDField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["branch", "occurred_at"]),
            models.Index(fields=["account", "occurred_at"]),
        ]

    def __str__(self):
        sign = "+" if self.direction == Direction.IN_ else "-"
        return f"{self.account} {sign}{self.amount}"
