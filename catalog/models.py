# catalog/models.py
import uuid
from django.db import models

class CountType(models.TextChoices):
    PCS = "pcs", "pcs"
    KG  = "kg",  "kg"
    L   = "l",   "l"
    GR  = "gr",  "gr"
    ML  = "ml",  "ml"

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
