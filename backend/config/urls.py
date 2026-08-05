"""Root URL configuration."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.core.urls")),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/admin/", include("apps.accounts.admin_urls")),
    path("api/", include("apps.accounts.profile_urls")),
    path("api/", include("apps.listings.urls")),
    path("api/", include("apps.templates.urls")),
    path("api/", include("apps.ai_content.urls")),
    # Domain apps are wired up here as they gain endpoints:
    # path("api/ai-content/", include("apps.ai_content.urls")),
    # path("api/compliance/", include("apps.compliance.urls")),
]

if settings.DEBUG:
    # Development only. `static()` is a convenience for serving MEDIA_ROOT
    # through the dev server and is a no-op when DEBUG is False — in
    # production the files are served by nginx, or straight from the object
    # store once STORAGES["default"] points at one.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
