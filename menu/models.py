# menu/models.py
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from catalog.models import Product
from core.models import Branch


class FoodType(models.TextChoices):
    FASTFOOD = "FASTFOOD", "Fastfood"
    DRINK = "DRINK", "Ichimlik"
    SET = "SET", "Set"


class FoodCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="food_categories")
    type = models.CharField(max_length=20, choices=FoodType.choices, default=FoodType.FASTFOOD)
    name = models.CharField(max_length=80)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["branch", "type", "name"], name="uniq_branch_foodcategory_typename")
        ]
        ordering = ("sort_order", "name")
        verbose_name = "Taom turi"
        verbose_name_plural = "Taom turlari"

    def __str__(self):
        return f"{self.name} ({self.type})"


class Food(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="foods", null=True)

    type = models.CharField(max_length=20, choices=FoodType.choices, default=FoodType.FASTFOOD)
    category = models.ForeignKey(FoodCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="foods")

    name = models.CharField(max_length=255)
    image = models.ImageField(upload_to="foods/", null=True, blank=True)

    # Variantlar ishlatilmaydi: har bir narxli konfiguratsiya alohida Food sifatida qo'shiladi.
    sell_price = models.BigIntegerField(default=0)  # so‘mda
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["branch", "name"], name="uniq_branch_food_name")
        ]
        ordering = ("sort_order", "name")
        verbose_name = "Taom"
        verbose_name_plural = "Taomlar"

    def __str__(self):
        return f"{self.name}"


class FoodItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    food = models.ForeignKey(Food, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    qty = models.DecimalField(max_digits=14, decimal_places=3)

    class Meta:
        unique_together = ("food", "product")
        verbose_name = "Taom mahsuloti"
        verbose_name_plural = "Taom mahsulotlari"

    def clean(self):
        # ✅ SET uchun ingredient (product) yozilmaydi.
        # SET tarkibi SetItem orqali Food'lar bilan tuziladi.
        if self.food and self.food.type == FoodType.SET:
            raise ValidationError({
                "food": "SET uchun FoodItem (ingredient) kiritilmaydi. SET tarkibini SetItem orqali tuzing."
            })

        if self.qty is None or self.qty <= Decimal("0"):
            raise ValidationError({"qty": "Qty 0 dan katta bo‘lishi kerak."})
        if self.product and not self.product.is_active:
            raise ValidationError({"product": "Bu product noaktiv. Aktiv qiling yoki boshqasini tanlang."})


class SetItem(models.Model):
    """SET tarkibi: SET Food ichida boshqa Food'lar (fastfood/drink) bo'ladi."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    set_food = models.ForeignKey(
        Food,
        related_name="set_items",
        on_delete=models.CASCADE,
        limit_choices_to={"type": FoodType.SET},
    )
    food = models.ForeignKey(
        Food,
        related_name="as_set_component",
        on_delete=models.PROTECT,
        limit_choices_to={"type__in": [FoodType.FASTFOOD, FoodType.DRINK]},
    )
    qty = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ("set_food", "food")
        verbose_name = "Set elementi"
        verbose_name_plural = "Set elementlari"

    def clean(self):
        if self.qty is None or int(self.qty) <= 0:
            raise ValidationError({"qty": "Qty 0 dan katta bo‘lishi kerak."})
        if self.set_food and self.set_food.type != FoodType.SET:
            raise ValidationError({"set_food": "set_food type=SET bo‘lishi shart."})
        if self.food and self.food.type == FoodType.SET:
            raise ValidationError({"food": "SET ichida yana SET bo‘lishi hozircha taqiqlangan."})

        # ✅ filial aralashib ketmasin
        if self.set_food and self.food and self.set_food.branch_id != self.food.branch_id:
            raise ValidationError({"food": "Set ichidagi food set_food bilan bir xil filialniki bo‘lishi kerak."})