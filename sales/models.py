import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum

from core.models import Branch
from finance.models import MoneyAccount, CashTransaction
from menu.models import Food


class Order(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Yangi"
        PAID = "paid", "To‘langan"
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

    total_amount = models.BigIntegerField(default=0)  # snapshot
    paid_amount = models.BigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(blank=True, null=True)

    is_locked = models.BooleanField(default=False)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    def clean(self):
        # Yakunlangan order o'zgartirilmaydi (model-level himoya).
        if self.pk and self.is_locked:
            raise ValidationError("Bu buyurtma yakunlangan. Endi tahrirlab bo‘lmaydi.")

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
    unit_price = models.BigIntegerField()  # snapshot
    line_total = models.BigIntegerField()  # unit_price * qty

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order", "food"], name="uniq_order_food"),
        ]

    def clean(self):
        if not self.order:
            return
        if self.order.is_locked:
            raise ValidationError("Buyurtma yakunlangan. Itemlarni o'zgartirib bo'lmaydi.")
        # Topshirilgan (stock yechilgan) orderda itemlar o'zgarsa - ombor buziladi
        if self.order.is_delivered or self.order.stock_applied:
            raise ValidationError("Topshirilgan orderda itemlarni o'zgartirib bo'lmaydi.")

    def save(self, *args, **kwargs):
        # Model-level himoya: admin yoki service'lardan kelgan editlarni ham ushlaymiz
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
        # delete ham model-level lockni hurmat qilsin
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

    # pul yozuvi bilan bog‘lash (double-apply bo‘lmasin)
    cash_txn = models.OneToOneField(CashTransaction, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.order_id} +{self.amount}"
