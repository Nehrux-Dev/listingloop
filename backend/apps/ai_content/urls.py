from rest_framework.routers import DefaultRouter

from apps.ai_content.views import ContentVariantViewSet, GeneratedContentViewSet

app_name = "ai_content"

router = DefaultRouter()
router.register("ai-content", GeneratedContentViewSet, basename="generatedcontent")
router.register("ai-content-variants", ContentVariantViewSet, basename="contentvariant")

urlpatterns = router.urls
