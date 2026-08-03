"""Role-gated example endpoints, mounted under ``/api/admin/``.

Separate from ``urls.py`` because these are ordinary (if privileged) API
resources, not part of the authentication flow.
"""

from django.urls import path

from apps.accounts import views

app_name = "accounts_admin"

urlpatterns = [
    path(
        "platform-overview/",
        views.PlatformOverviewView.as_view(),
        name="platform-overview",
    ),
    path(
        "brokerage-overview/",
        views.BrokerageOverviewView.as_view(),
        name="brokerage-overview",
    ),
]
