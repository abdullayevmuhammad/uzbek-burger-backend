from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# Admin branding (Uzbek)
admin.site.site_header = "UzbekBurger — Boshqaruv paneli"
admin.site.site_title = "UzbekBurger Admin"
admin.site.index_title = "Boshqaruv"

urlpatterns = [
    path("admin/", admin.site.urls),

    # Auth
    path("accounts/", include("django.contrib.auth.urls")),

    # Core (home router + branch select)
    path("", include("core.urls")),

    # POS (Sales UI)
    path("pos/", include("sales.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
