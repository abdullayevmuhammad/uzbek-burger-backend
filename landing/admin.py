from django.contrib import admin
from .models import LandingSettings, Post

@admin.register(LandingSettings)
class LandingSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        # bitta settings bo‘lsin
        return not LandingSettings.objects.exists()

@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("title", "is_published", "published_at", "created_at")
    list_filter = ("is_published",)
    search_fields = ("title", "excerpt", "content")
    prepopulated_fields = {"slug": ("title",)}
