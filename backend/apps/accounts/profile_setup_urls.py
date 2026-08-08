"""Profile setup routes, mounted at /api/profile/."""

from django.urls import path

from apps.accounts import profile_setup_views

app_name = "profile_setup"

urlpatterns = [
    path(
        "completeness/",
        profile_setup_views.profile_completeness,
        name="completeness",
    ),
    path(
        "brokerages/",
        profile_setup_views.BrokerageDirectoryView.as_view(),
        name="brokerage-directory",
    ),
    path("brokerage/", profile_setup_views.set_brokerage, name="set-brokerage"),
]
