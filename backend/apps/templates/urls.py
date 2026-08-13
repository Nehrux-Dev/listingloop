from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.templates.views import (
    CalendarEventViewSet,
    DesignExportViewSet,
    DesignViewSet,
    TemplateViewSet,
    element_kinds,
    render_dimensions,
)

app_name = "templates"

router = DefaultRouter()
router.register("templates", TemplateViewSet, basename="template")
router.register("designs", DesignViewSet, basename="design")
router.register("design-exports", DesignExportViewSet, basename="designexport")
router.register("calendar-events", CalendarEventViewSet, basename="calendarevent")

urlpatterns = router.urls + [
    path("render-dimensions/", render_dimensions, name="render-dimensions"),
    path("design-element-kinds/", element_kinds, name="design-element-kinds"),
]
