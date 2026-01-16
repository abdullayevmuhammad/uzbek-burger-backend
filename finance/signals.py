from django.db.models.signals import post_save
from django.dispatch import receiver

from core.models import Branch
from .models import MoneyAccount, AccountKind


@receiver(post_save, sender=Branch)
def create_default_cash_account(sender, instance: Branch, created: bool, **kwargs):
    """Branch yaratilganda default 'Kassa' (naqd) hisob yaratiladi."""
    if not created:
        return

    MoneyAccount.objects.get_or_create(
        branch=instance,
        name="Kassa",
        defaults={
            "kind": AccountKind.CASH,
            "is_active": True,
        },
    )


