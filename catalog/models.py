# catalog/models.py
import uuid
from decimal import Decimal

from django.db import models, transaction
from django.db.models import Sum

from inventory.units import to_base


class CountType(models.TextChoices):
    PCS = "pcs", "Dona"
    KG = "kg", "Kg"
    L = "l", "L"
    GR = "gr", "Gr"
    ML = "ml", "Ml"


class ProductSkuSequence(models.Model):
    """
    SKU ketma-ketligini saqlaydi (P000001, P000002, ...)
    """

    name = models.CharField(max_length=32, unique=True)
    last = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.name}:{self.last}"


def _next_product_sku() -> str:
    seq, _ = ProductSkuSequence.objects.select_for_update().get_or_create(name="product")
    seq.last += 1
    seq.save(update_fields=["last"])
    return f"P{seq.last:06d}"


class Product(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    count_type = models.CharField(max_length=10, choices=CountType.choices)
    sku = models.CharField(max_length=64, blank=True, null=True, unique=True)
    barcode = models.CharField(max_length=64, blank=True, null=True, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.sku:
            with transaction.atomic():
                self.sku = _next_product_sku()

                if kwargs.get("update_fields") is not None:
                    update_fields = set(kwargs["update_fields"])
                    update_fields.add("sku")
                    kwargs["update_fields"] = list(update_fields)

                return super().save(*args, **kwargs)

        return super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Mahsulot"
        verbose_name_plural = "Mahsulotlar"

    @property
    def total_stock_qty(self):
        """Barcha filiallar bo'yicha jami qoldiq."""
        return self.branch_products.aggregate(s=Sum("stock_qty")).get("s") or 0

    @property
    def weighted_avg_unit_cost(self):
        """Barcha filiallar bo'yicha bazaviy birlikdagi og'irlikli o'rtacha tannarx."""
        total_qty_base = Decimal("0")
        total_cost = Decimal("0")

        for branch_product in self.branch_products.select_related("product").all():
            qty_base = to_base(branch_product.stock_qty, self.count_type)
            total_qty_base += qty_base
            total_cost += Decimal(branch_product.avg_unit_cost) * qty_base

        if not total_qty_base:
            return 0
        return float(total_cost / total_qty_base)
