# users/models.py
import uuid
from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from core.models import Branch


class StaffRole(models.TextChoices):
    OWNER = "owner", "Owner"
    STAFF = "staff", "Staff"


class StaffProfile(models.Model):
    """
    Har bir login user uchun (ixtiyoriy) profil.
    - OWNER: branch=None bo'lishi mumkin (hammasini ko'radi)
    - STAFF: branch majburiy (faqat o'z filialida ishlaydi)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    role = models.CharField(max_length=10, choices=StaffRole.choices, default=StaffRole.STAFF)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True, related_name="staff_profiles")

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.role == StaffRole.STAFF and not self.branch_id:
            raise ValidationError({"branch": "STAFF uchun branch majburiy."})

    def __str__(self):
        if self.role == StaffRole.OWNER:
            return f"{self.user.username} (OWNER)"
        return f"{self.user.username} ({self.branch})"
