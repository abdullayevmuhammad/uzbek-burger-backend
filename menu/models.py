import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from catalog.models import Product
from core.models import Branch


class Food(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="foods", null=True)  # null=False
    name = models.CharField(max_length=255)  # endi global unique emas
    sell_price = models.BigIntegerField(default=0)  # so‘mda
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["branch", "name"], name="uniq_branch_food_name")
        ]

    def __str__(self):
        return f"{self.name} - {self.sell_price} so'm"

class FoodItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    food = models.ForeignKey(Food, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)  # ingredient
    qty = models.DecimalField(max_digits=14, decimal_places=3)  # product.count_type birlikda

    class Meta:
        unique_together = ("food", "product")

    def clean(self):
        if self.qty is None or self.qty <= Decimal("0"):
            raise ValidationError({"qty": "Qty 0 dan katta bo‘lishi kerak."})
        if self.product and not self.product.is_active:
            raise ValidationError({"product": "Bu product noaktiv. Aktiv qiling yoki boshqasini tanlang."})
