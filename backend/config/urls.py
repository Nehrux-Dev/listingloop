"""Root URL configuration."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.core.urls")),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/admin/", include("apps.accounts.admin_urls")),
    # Domain apps are wired up here as they gain endpoints:
    # path("api/listings/", include("apps.listings.urls")),
    # path("api/templates/", include("apps.templates.urls")),
    # path("api/ai-content/", include("apps.ai_content.urls")),
    # path("api/compliance/", include("apps.compliance.urls")),
]
