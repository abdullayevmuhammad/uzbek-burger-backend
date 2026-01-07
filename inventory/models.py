# inventory/models.py
import uuid
from django.conf import settings
from django.db import models
from core.models import Branch
from catalog.models import Product


class BranchProduct(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="branch_products")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="branch_products")

    stock_qty = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    avg_unit_cost = models.BigIntegerField(default=0)   # so'm
    last_unit_cost = models.BigIntegerField(default=0)  # so'm

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["branch", "product"], name="uniq_branch_product"),
        ]

    def __str__(self):
        return f"{self.branch} - {self.product}"


class StockImport(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        POSTED = "POSTED"

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="stock_imports")
    note = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="created_stock_imports",
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="posted_stock_imports",
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    paid_from_account = models.ForeignKey(
        "finance.MoneyAccount",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="imports_paid",
    )

    cash_txn = models.OneToOneField(
        "finance.CashTransaction",
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )

    def __str__(self):
        return f"{self.branch.name} | {str(self.id)[:8]}"


class StockImportItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stock_import = models.ForeignKey(StockImport, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)

    qty = models.DecimalField(max_digits=14, decimal_places=3)
    line_total_cost = models.BigIntegerField()  # so'mda (umumiy)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["stock_import", "product"], name="uniq_import_product")
        ]
    def __str__(self):
        return f"{self.product.name} x {self.qty}"
