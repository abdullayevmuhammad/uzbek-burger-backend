from django.contrib import admin
from .models import Branch


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "address", 'id')
    list_filter = ("is_active",)
    search_fields = ("name", "address")
    list_editable = ("is_active",)
    ordering = ("name",)
