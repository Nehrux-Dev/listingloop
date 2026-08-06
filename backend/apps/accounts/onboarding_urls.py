"""Onboarding routes, mounted at /api/onboarding/."""

from django.urls import path

from apps.accounts import onboarding_views

app_name = "onboarding"

urlpatterns = [
    path("status/", onboarding_views.onboarding_status, name="status"),
    path("completion/", onboarding_views.profile_completion, name="completion"),
    path(
        "brokerages/",
        onboarding_views.BrokerageDirectoryView.as_view(),
        name="brokerage-directory",
    ),
    path("brokerage/", onboarding_views.set_brokerage, name="set-brokerage"),
    path("complete/", onboarding_views.complete_onboarding, name="complete"),
]
