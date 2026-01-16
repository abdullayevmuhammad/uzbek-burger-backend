from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "finance"
    verbose_name = "Moliya"

    def ready(self):
        # signals
        from . import signals  # noqa: F401
