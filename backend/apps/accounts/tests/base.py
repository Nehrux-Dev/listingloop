"""Shared helpers for the accounts test suite."""

from __future__ import annotations

import io

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework.test import APITestCase

from apps.accounts.models import Brokerage, Role

User = get_user_model()

PASSWORD = "correct-horse-battery"


def make_image_file(
    name: str = "photo.png",
    image_format: str = "PNG",
    size: tuple[int, int] = (32, 32),
    color: str = "#2563EB",
) -> SimpleUploadedFile:
    """A genuine, decodable image in memory."""
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=image_format)
    buffer.seek(0)
    content_type = f"image/{image_format.lower()}"
    return SimpleUploadedFile(name, buffer.read(), content_type=content_type)


class AuthAPITestCase(APITestCase):
    """Base class with user factories and URL shortcuts."""

    login_url = reverse("accounts:login")
    logout_url = reverse("accounts:logout")
    refresh_url = reverse("accounts:refresh")
    register_url = reverse("accounts:register")
    me_url = reverse("accounts:me")
    platform_url = reverse("accounts_admin:platform-overview")
    brokerage_url = reverse("accounts_admin:brokerage-overview")

    brokerages_url = reverse("profiles:brokerage-list")
    agents_url = reverse("profiles:agent-list")
    agent_me_url = reverse("profiles:agent-me")
    brand_kits_url = reverse("profiles:brandkit-list")
    brand_kit_mine_url = reverse("profiles:brandkit-mine")

    @staticmethod
    def brokerage_detail_url(brokerage) -> str:
        return reverse("profiles:brokerage-detail", args=[brokerage.pk])

    @staticmethod
    def agent_detail_url(profile) -> str:
        return reverse("profiles:agent-detail", args=[profile.pk])

    @staticmethod
    def brand_kit_detail_url(brand_kit) -> str:
        return reverse("profiles:brandkit-detail", args=[brand_kit.pk])

    def setUp(self) -> None:
        super().setUp()
        # The auth endpoints are rate-limited, and DRF keeps throttle counters
        # in the cache keyed by client IP — which is identical for every test.
        # Clearing keeps tests independent of execution order.
        cache.clear()

    # -- factories ----------------------------------------------------------

    @staticmethod
    def make_user(email: str, role: str = Role.AGENT, **kwargs):
        return User.objects.create_user(
            email=email, password=PASSWORD, role=role, **kwargs
        )

    def make_agent(self, email: str = "agent@example.com"):
        return self.make_user(email, Role.AGENT)

    def make_brokerage_admin(self, email: str = "brokerage@example.com"):
        return self.make_user(email, Role.BROKERAGE_ADMIN)

    def make_nehrux_admin(self, email: str = "nehrux@example.com"):
        return self.make_user(email, Role.NEHRUX_ADMIN)

    @staticmethod
    def make_brokerage(name: str = "Acme Realty", *admins) -> Brokerage:
        brokerage = Brokerage.objects.create(name=name)
        if admins:
            brokerage.admins.set(admins)
        return brokerage

    def make_agent_in(self, brokerage, email: str = "agent@example.com"):
        """Create an agent user and attach their auto-created profile."""
        user = self.make_agent(email)
        # The profile is created by a post_save signal on the user.
        profile = user.agent_profile
        profile.brokerage = brokerage
        profile.save()
        return user, profile

    # -- helpers ------------------------------------------------------------

    def login(self, email: str, password: str = PASSWORD):
        """POST to the login endpoint. The test client keeps the cookie."""
        return self.client.post(
            self.login_url, {"email": email, "password": password}, format="json"
        )

    def authenticate_as(self, user) -> str:
        """Log ``user`` in and set the Authorization header. Returns the token."""
        response = self.login(user.email)
        assert response.status_code == 200, response.data
        access = response.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        return access

    def refresh_cookie(self) -> str | None:
        """Current value of the refresh cookie held by the test client."""
        morsel = self.client.cookies.get(settings.AUTH_COOKIE_NAME)
        return morsel.value if morsel else None
