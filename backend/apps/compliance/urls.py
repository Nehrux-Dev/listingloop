from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.compliance.views import (
    ComplianceEvaluationViewSet,
    ComplianceRuleViewSet,
    evaluate_now,
)

app_name = "compliance"

router = DefaultRouter()
router.register("compliance/rules", ComplianceRuleViewSet, basename="rule")
router.register(
    "compliance/evaluations", ComplianceEvaluationViewSet, basename="evaluation"
)

urlpatterns = router.urls + [
    path("compliance/evaluate/", evaluate_now, name="evaluate"),
]
