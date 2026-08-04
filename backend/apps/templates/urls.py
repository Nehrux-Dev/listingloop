from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.templates.views import (
    DesignExportViewSet,
    DesignViewSet,
    TemplateViewSet,
    render_dimensions,
)

app_name = "templates"

router = DefaultRouter()
router.register("templates", TemplateViewSet, basename="template")
router.register("designs", DesignViewSet, basename="design")
router.register("design-exports", DesignExportViewSet, basename="designexport")

urlpatterns = router.urls + [
    path("render-dimensions/", render_dimensions, name="render-dimensions"),
]
