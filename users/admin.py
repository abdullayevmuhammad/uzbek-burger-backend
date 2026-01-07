# users/admin.py
from django.contrib import admin
from .models import StaffProfile


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "branch", "is_active", "created_at")
    list_filter = ("role", "branch", "is_active")
    search_fields = ("user__username", "user__email", "branch__name")
    autocomplete_fields = ("user", "branch")
