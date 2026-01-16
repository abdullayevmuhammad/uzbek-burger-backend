# catalog/models.py
import uuid
from django.db import models, transaction
from django.db.models import Sum

class CountType(models.TextChoices):
    PCS = "pcs", "Dona"
    KG  = "kg",  "Kg"
    L   = "l",   "L"
    GR  = "gr",  "Gr"
    ML  = "ml",  "Ml"


class ProductSkuSequence(models.Model):
    """
    SKU ketma-ketligini saqlaydi (P000001, P000002, ...)
    """
    name = models.CharField(max_length=32, unique=True)
    last = models.PositiveIntegerField(default=0)


    @property
    def total_stock_qty(self):
        """Barcha filiallar bo'yicha umumiy qoldiq (hisob-kitob)."""
        return self.branch_products.aggregate(s=Sum("stock_qty")).get("s") or 0

    @property
    def weighted_avg_unit_cost(self):
        """Barcha filiallar bo'yicha og'irlikli o'rtacha tannarx (hisob-kitob)."""
        qs = self.branch_products.all()
        total_qty = qs.aggregate(s=Sum("stock_qty")).get("s") or 0
        if not total_qty:
            return 0
        # Sum(avg_unit_cost * stock_qty)
        total_cost = 0
        for bp in qs:
            total_cost += float(bp.avg_unit_cost) * float(bp.stock_qty)
        return total_cost / float(total_qty)

    def __str__(self):
        return f"{self.name}:{self.last}"


def _next_product_sku() -> str:
    seq, _ = ProductSkuSequence.objects.select_for_update().get_or_create(name="product")
    seq.last += 1
    seq.save(update_fields=["last"])
    return f"P{seq.last:06d}"  # P000001

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
        # SKU bo'sh bo'lsa avtomatik beramiz
        if not self.sku:
            with transaction.atomic():
                self.sku = _next_product_sku()

                # Agar kimdir update_fields bilan saqlasa ham sku yozilib ketsin
                if kwargs.get("update_fields") is not None:
                    uf = set(kwargs["update_fields"])
                    uf.add("sku")
                    kwargs["update_fields"] = list(uf)

                return super().save(*args, **kwargs)

        return super().save(*args, **kwargs)
    class Meta:
        verbose_name = "Mahsulot"
        verbose_name_plural = "Mahsulotlar"
    @property
    def total_stock_qty(self):
        """
        Barcha filiallar bo‘yicha jami qoldiq (BranchProduct.stock_qty yig'indisi)
        """
        return (
            self.branch_products.aggregate(s=Sum("stock_qty")).get("s") or 0
        )