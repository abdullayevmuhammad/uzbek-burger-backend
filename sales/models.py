import uuid
from django.db import models
from django.core.validators import MinValueValidator
from core.models import Branch
from menu.models import Food
from finance.models import MoneyAccount, CashTransaction
from django.conf import settings


class Order(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PAID = "paid", "Paid"
        CANCELED = "canceled", "Canceled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    stock_applied = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="created_orders",
    )
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="paid_orders",
    )

    total_amount = models.BigIntegerField(default=0)  # snapshot
    paid_amount = models.BigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.branch.name} | {str(self.id)[:8]} | {self.status}"


class OrderItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    food = models.ForeignKey(Food, on_delete=models.PROTECT)

    qty = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.BigIntegerField()  # food.sell_price snapshot
    line_total = models.BigIntegerField()  # unit_price * qty

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order", "food"], name="uniq_order_food"),
        ]

    def save(self, *args, **kwargs):
        # food bo'lmasa saqlamaymiz
        if not self.food_id:
            raise ValueError("food is required")

        # agar yangi bo'lsa yoki food o'zgargan bo'lsa -> snapshot price
        if self.pk:
            old_food_id = type(self).objects.filter(pk=self.pk).values_list("food_id", flat=True).first()
            if old_food_id != self.food_id:
                self.unit_price = self.food.sell_price
        else:
            self.unit_price = self.food.sell_price

        # line_total doim snapshot unit_price bilan hisoblanadi
        self.line_total = int(self.unit_price) * int(self.qty)

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.food.name} x {self.qty}"


class OrderPayment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, related_name="payments", on_delete=models.CASCADE)

    account = models.ForeignKey(MoneyAccount, on_delete=models.PROTECT)
    amount = models.BigIntegerField(validators=[MinValueValidator(1)])

    created_at = models.DateTimeField(auto_now_add=True)

    # pul yozuvi bilan bog‘lash (double-apply bo‘lmasin)
    cash_txn = models.OneToOneField(CashTransaction, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.order_id} +{self.amount}"
