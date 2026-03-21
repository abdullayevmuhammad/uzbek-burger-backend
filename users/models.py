# users/models.py
import uuid
from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from core.models import Branch


class StaffRole(models.TextChoices):
    ADMIN = "admin", "Admin"
    CASHIER = "cashier", "Cashier"


class StaffProfile(models.Model):
    """
    Har bir login user uchun (ixtiyoriy) profil.
    - ADMIN: branch=None bo'lishi mumkin (hammasini ko'radi)
    - CASHIER: branch majburiy (faqat o'z filialida ishlaydi)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    role = models.CharField(max_length=10, choices=StaffRole.choices, default=StaffRole.CASHIER)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True, related_name="staff_profiles")

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.role == StaffRole.CASHIER and not self.branch_id:
            raise ValidationError({"branch": "CASHIER uchun branch majburiy."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

        if self.user_id and not self.user.is_superuser:
            should_have_admin_access = self.is_active and self.role == StaffRole.ADMIN
            if self.user.is_staff != should_have_admin_access:
                self.user.is_staff = should_have_admin_access
                self.user.save(update_fields=["is_staff"])

    def delete(self, *args, **kwargs):
        user = self.user
        super().delete(*args, **kwargs)
        if user and not user.is_superuser and user.is_staff:
            user.is_staff = False
            user.save(update_fields=["is_staff"])

    def __str__(self):
        if self.role == StaffRole.ADMIN:
            return f"{self.user.username} (ADMIN)"
        return f"{self.user.username} ({self.branch})"
    class Meta:
        verbose_name = "Xodim"
        verbose_name_plural = "Xodimlar"
