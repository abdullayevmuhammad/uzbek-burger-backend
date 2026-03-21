import uuid

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Case, F, IntegerField, Sum, Value, When

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
    OPENING_BALANCE = "opening_balance", "Opening balance"
    CASH_ADJUSTMENT = "cash_adjustment", "Cash adjustment"
    CASH_IN = "cash_in", "Cash in"
    CASH_OUT = "cash_out", "Cash out"
    ADJUST = "adjust", "Legacy adjust"


NON_SALES_TXN_TYPES = {
    TxnType.OPENING_BALANCE,
    TxnType.CASH_ADJUSTMENT,
    TxnType.CASH_IN,
    TxnType.CASH_OUT,
}

FIXED_DIRECTION_BY_TXN_TYPE = {
    TxnType.OPENING_BALANCE: Direction.IN_,
    TxnType.CASH_IN: Direction.IN_,
    TxnType.CASH_OUT: Direction.OUT,
}


def recalculate_balance_cache(account_id) -> None:
    agg = CashTransaction.objects.filter(account_id=account_id).aggregate(
        bal=Sum(
            Case(
                When(direction=Direction.IN_, then=F("amount")),
                When(direction=Direction.OUT, then=Value(0) - F("amount")),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
    )
    MoneyAccount.objects.filter(pk=account_id).update(balance_cache=agg["bal"] or 0)


class MoneyAccount(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="money_accounts",
    )
    name = models.CharField(max_length=80)
    kind = models.CharField(
        max_length=10,
        choices=AccountKind.choices,
        default=AccountKind.CASH,
    )
    is_active = models.BooleanField(default=True)
    balance_cache = models.BigIntegerField(default=0)

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

    def clean(self):
        if self.branch_id and not self.branch.is_active:
            raise ValidationError({"branch": "Arxivlangan filial uchun yangi kassa yaratib bo'lmaydi."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CashTransactionQuerySet(models.QuerySet):
    def order_payments(self):
        return self.filter(txn_type=TxnType.SALE, ref_type="order_payment")

    def non_sales(self):
        return self.exclude(txn_type=TxnType.SALE, ref_type="order_payment")

    def adjustments(self):
        return self.filter(txn_type__in=NON_SALES_TXN_TYPES)


class CashTransaction(models.Model):
    objects = CashTransactionQuerySet.as_manager()

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
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cash_transactions",
        null=True,
        blank=True,
    )

    direction = models.CharField(
        max_length=5,
        choices=Direction.choices,
    )
    txn_type = models.CharField(
        max_length=20,
        choices=TxnType.choices,
    )

    amount = models.BigIntegerField(validators=[MinValueValidator(1)])
    occurred_at = models.DateTimeField()
    reason = models.CharField(max_length=120, blank=True)
    note = models.TextField(blank=True, null=True)

    ref_type = models.CharField(max_length=30, blank=True, null=True)
    ref_id = models.UUIDField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["branch", "occurred_at"]),
            models.Index(fields=["account", "occurred_at"]),
            models.Index(fields=["txn_type", "occurred_at"]),
        ]
        verbose_name = "Pul o'tkazmasi"
        verbose_name_plural = "Pul o'tkazmalari"

    def __str__(self):
        sign = "+" if self.direction == Direction.IN_ else "-"
        return f"{self.account} {sign}{self.amount}"

    @property
    def is_order_payment(self) -> bool:
        return self.txn_type == TxnType.SALE and self.ref_type == "order_payment"

    @property
    def history_bucket(self) -> str:
        return "sales" if self.is_order_payment else "non_sales"

    def clean(self):
        errors = {}

        if self.account_id and self.branch_id and self.account.branch_id != self.branch_id:
            errors["account"] = "Account va branch bir xil filialga tegishli bo'lishi kerak."

        fixed_direction = FIXED_DIRECTION_BY_TXN_TYPE.get(self.txn_type)
        if fixed_direction and self.direction != fixed_direction:
            errors["direction"] = f"{self.txn_type} uchun direction {fixed_direction} bo'lishi kerak."

        if self.txn_type in NON_SALES_TXN_TYPES:
            if not self.actor_id:
                errors["actor"] = "Manual cash correction uchun actor majburiy."
            if not str(self.reason or "").strip():
                errors["reason"] = "Manual cash correction uchun reason majburiy."
            if not str(self.note or "").strip():
                errors["note"] = "Manual cash correction uchun note majburiy."

        if self.txn_type == TxnType.SALE:
            if self.ref_type != "order_payment" or not self.ref_id:
                errors["ref_type"] = "Sale transaction faqat real order payment bilan bog'lanadi."
            else:
                OrderPayment = apps.get_model("sales", "OrderPayment")
                payment = OrderPayment.objects.filter(pk=self.ref_id).select_related("order", "account").first()
                if payment is None:
                    errors["ref_id"] = "Bog'langan order payment topilmadi."
                else:
                    if payment.order.branch_id != self.branch_id:
                        errors["branch"] = "Sale transaction branch'i order payment bilan mos emas."
                    if payment.account_id != self.account_id:
                        errors["account"] = "Sale transaction account'i order payment bilan mos emas."
                    if int(payment.amount) != int(self.amount or 0):
                        errors["amount"] = "Sale transaction amount'i order payment bilan mos emas."
                    duplicate_exists = CashTransaction.objects.exclude(pk=self.pk).filter(
                        txn_type=TxnType.SALE,
                        ref_type="order_payment",
                        ref_id=self.ref_id,
                    ).exists()
                    if duplicate_exists:
                        errors["ref_id"] = "Bu order payment uchun cash transaction allaqachon mavjud."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        account_id = self.account_id
        with transaction.atomic():
            self.full_clean()
            super().save(*args, **kwargs)
            recalculate_balance_cache(account_id)

    def delete(self, *args, **kwargs):
        account_id = self.account_id
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            recalculate_balance_cache(account_id)
            return result
