from rest_framework.routers import DefaultRouter

from apps.ai_content.views import GeneratedContentViewSet

app_name = "ai_content"

router = DefaultRouter()
router.register("ai-content", GeneratedContentViewSet, basename="generatedcontent")

urlpatterns = router.urls
