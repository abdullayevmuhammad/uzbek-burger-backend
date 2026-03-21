import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from core.models import Branch
from finance.models import CashTransaction, MoneyAccount
from menu.models import Food


class Order(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Yangi"
        PAID = "paid", "To'langan"
        CANCELED = "canceled", "Bekor qilingan"

    class OrderType(models.TextChoices):
        DINE_IN = "dine_in", "Shu yerda"
        TAKEAWAY = "takeaway", "Olib ketish"
        DELIVERY = "delivery", "Yetkazib berish"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="orders")
    order_type = models.CharField(max_length=12, choices=OrderType.choices, default=OrderType.DINE_IN)
    is_delivered = models.BooleanField(default=False)
    delivered_at = models.DateTimeField(blank=True, null=True)
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="delivered_orders",
    )

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    stock_applied = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_orders",
    )
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="paid_orders",
    )

    total_amount = models.BigIntegerField(default=0)
    paid_amount = models.BigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(blank=True, null=True)

    is_locked = models.BooleanField(default=False)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    cogs_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    profit_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    @property
    def profit(self):
        return (self.total_amount or Decimal("0.00")) - (self.cogs_amount or Decimal("0.00"))

    def clean(self):
        if self.branch_id and not self.branch.is_active:
            raise ValidationError({"branch": "Arxivlangan filial uchun order yaratib bo'lmaydi."})
        if self.pk and self.is_locked:
            raise ValidationError("Bu buyurtma yakunlangan. Endi tahrirlab bo'lmaydi.")

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["branch", "created_at"]),
            models.Index(fields=["branch", "status", "created_at"]),
            models.Index(fields=["branch", "is_delivered", "created_at"]),
        ]
        verbose_name = "Buyurtma"
        verbose_name_plural = "Buyurtmalar"

    @property
    def is_fully_paid(self):
        return self.paid_amount >= self.total_amount

    def __str__(self):
        return f"{self.branch.name} | {str(self.id)[:8]} | {self.status}"


class OrderItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    food = models.ForeignKey(Food, on_delete=models.PROTECT)

    qty = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.BigIntegerField()
    line_total = models.BigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order", "food"], name="uniq_order_food"),
        ]

    def clean(self):
        if not self.order:
            return
        if self.order.is_locked:
            raise ValidationError("Buyurtma yakunlangan. Itemlarni o'zgartirib bo'lmaydi.")
        if self.order.is_delivered or self.order.stock_applied:
            raise ValidationError("Topshirilgan orderda itemlarni o'zgartirib bo'lmaydi.")
        if self.food and self.order and self.food.branch_id != self.order.branch_id:
            raise ValidationError("Taom buyurtma bilan bir xil filialga tegishli bo'lishi kerak.")

    def save(self, *args, **kwargs):
        self.full_clean(exclude=None)
        if not self.food_id:
            raise ValueError("food is required")

        current_price = int(self.food.sell_price)
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).values("food_id").first()
            if old and (old["food_id"] != self.food_id):
                self.unit_price = current_price
        else:
            self.unit_price = current_price

        self.line_total = int(self.unit_price) * int(self.qty)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.full_clean(exclude=None)
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.food.name} x {self.qty}"


class OrderPayment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, related_name="payments", on_delete=models.CASCADE)
    account = models.ForeignKey(MoneyAccount, on_delete=models.PROTECT)
    amount = models.BigIntegerField(validators=[MinValueValidator(1)])
    created_at = models.DateTimeField(auto_now_add=True)
    cash_txn = models.OneToOneField(CashTransaction, on_delete=models.SET_NULL, null=True, blank=True)

    def clean(self):
        errors = {}

        if self.order_id and self.account_id and self.order.branch_id != self.account.branch_id:
            errors["account"] = "Payment account va order branch bir xil bo'lishi kerak."

        if self.cash_txn_id:
            if self.cash_txn.txn_type != "sale" or self.cash_txn.ref_type != "order_payment":
                errors["cash_txn"] = "Order payment faqat sale/order_payment cash transaction bilan bog'lanadi."
            if self.pk and self.cash_txn.ref_id != self.pk:
                errors["cash_txn"] = "Cash transaction ref_id shu paymentga teng bo'lishi kerak."
            if self.cash_txn.branch_id != self.order.branch_id:
                errors["cash_txn"] = "Cash transaction branch'i order bilan mos emas."
            if self.cash_txn.account_id != self.account_id:
                errors["cash_txn"] = "Cash transaction account'i payment bilan mos emas."
            if int(self.cash_txn.amount) != int(self.amount or 0):
                errors["cash_txn"] = "Cash transaction amount'i payment bilan mos emas."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order_id} +{self.amount}"


class KitchenTask(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        IN_PROGRESS = "in_progress", "In progress"
        READY = "ready", "Ready"
        DONE = "done", "Done"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="kitchen_task")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="kitchen_tasks")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    items_snapshot = models.TextField(blank=True)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_kitchen_tasks")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="updated_kitchen_tasks")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["branch", "status", "created_at"])]

    def __str__(self):
        return f"KitchenTask {str(self.order_id)[:8]} ({self.status})"

    def refresh_from_order(self):
        lines = []
        for it in self.order.items.select_related("food").all():
            lines.append(f"{it.qty} x {it.food.name}")
        text = "\n".join(lines)
        if self.order.note:
            text = (text + "\n\nIzoh: " + self.order.note).strip()
        self.items_snapshot = text
        return text
