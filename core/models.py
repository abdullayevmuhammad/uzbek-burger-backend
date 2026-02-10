# core/models.py
import uuid
from django.db import models

class Branch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, unique=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    public_phone = models.CharField(max_length=50, blank=True)
    public_address = models.CharField(max_length=255, blank=True)

    working_hours = models.CharField(max_length=120, blank=True)  # masalan: Har kuni 09:00–23:00

    # Iframe embed (Google/Yandex) — majburiy emas
    map_iframe = models.TextField(blank=True)

    # ixtiyoriy: koordinata (keyin map link qilish uchun)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)

    show_on_landing = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Filial"
        verbose_name_plural = "Filiallar"
