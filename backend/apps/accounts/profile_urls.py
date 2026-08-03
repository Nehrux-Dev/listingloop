"""Router for the profile resources, mounted at /api/."""

from rest_framework.routers import DefaultRouter

from apps.accounts.profile_views import (
    AgentProfileViewSet,
    BrandKitViewSet,
    BrokerageViewSet,
)

app_name = "profiles"

router = DefaultRouter()
router.register("brokerages", BrokerageViewSet, basename="brokerage")
router.register("agents", AgentProfileViewSet, basename="agent")
router.register("brand-kits", BrandKitViewSet, basename="brandkit")

urlpatterns = router.urls
