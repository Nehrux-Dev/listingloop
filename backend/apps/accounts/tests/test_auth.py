"""Tests for the authentication flow: login, refresh, logout, register, me."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model

from apps.accounts.models import Role
from apps.accounts.tests.base import PASSWORD, AuthAPITestCase

User = get_user_model()


class LoginTests(AuthAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.agent = self.make_agent()

    def test_successful_login_returns_access_token_and_user(self):
        response = self.login(self.agent.email)

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertTrue(response.data["access"])
        self.assertEqual(response.data["user"]["email"], self.agent.email)
        self.assertEqual(response.data["user"]["role"], Role.AGENT)

    def test_successful_login_sets_httponly_refresh_cookie(self):
        """The security contract: refresh token in an httpOnly cookie only."""
        response = self.login(self.agent.email)

        cookie = response.cookies[settings.AUTH_COOKIE_NAME]
        self.assertTrue(cookie.value)
        # httpOnly is what keeps the token out of reach of JavaScript.
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], settings.AUTH_COOKIE_SAMESITE)
        self.assertEqual(cookie["path"], settings.AUTH_COOKIE_PATH)
        self.assertEqual(bool(cookie["secure"]), settings.AUTH_COOKIE_SECURE)

    def test_refresh_token_is_never_in_the_response_body(self):
        """If it leaked into the body, JavaScript could read and store it."""
        response = self.login(self.agent.email)

        self.assertNotIn("refresh", response.data)
        self.assertNotIn(
            response.cookies[settings.AUTH_COOKIE_NAME].value,
            response.content.decode(),
        )

    def test_login_updates_last_login(self):
        self.assertIsNone(self.agent.last_login)

        self.login(self.agent.email)

        self.agent.refresh_from_db()
        self.assertIsNotNone(self.agent.last_login)

    def test_email_login_is_case_insensitive(self):
        response = self.login("AGENT@Example.COM")

        self.assertEqual(response.status_code, 200)

    def test_failed_login_with_wrong_password(self):
        response = self.client.post(
            self.login_url,
            {"email": self.agent.email, "password": "not-the-password"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("access", response.data)
        # No cookie is issued for a rejected login.
        self.assertNotIn(settings.AUTH_COOKIE_NAME, response.cookies)

    def test_failed_login_with_unknown_email(self):
        response = self.client.post(
            self.login_url,
            {"email": "nobody@example.com", "password": PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_failed_login_does_not_reveal_whether_the_account_exists(self):
        """Wrong password and unknown e-mail must be indistinguishable."""
        wrong_password = self.client.post(
            self.login_url,
            {"email": self.agent.email, "password": "not-the-password"},
            format="json",
        )
        unknown_email = self.client.post(
            self.login_url,
            {"email": "nobody@example.com", "password": PASSWORD},
            format="json",
        )

        self.assertEqual(wrong_password.data, unknown_email.data)
        self.assertEqual(str(wrong_password.data["detail"][0]), "Invalid email or password.")

    def test_inactive_user_cannot_log_in(self):
        self.agent.is_active = False
        self.agent.save()

        response = self.login(self.agent.email)

        self.assertEqual(response.status_code, 400)


class TokenRefreshTests(AuthAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.agent = self.make_agent()

    def test_refresh_issues_a_new_access_token_from_the_cookie(self):
        """The body is empty — the browser supplies the cookie automatically."""
        self.login(self.agent.email)
        original_cookie = self.refresh_cookie()

        response = self.client.post(self.refresh_url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["access"])
        self.assertEqual(response.data["user"]["email"], self.agent.email)
        # Rotation: the cookie is replaced with a brand new refresh token.
        self.assertNotEqual(self.refresh_cookie(), original_cookie)

    def test_new_access_token_works_against_a_protected_endpoint(self):
        self.login(self.agent.email)

        access = self.client.post(self.refresh_url).data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["email"], self.agent.email)

    def test_rotated_refresh_token_cannot_be_reused(self):
        """A captured refresh token is single-use: replay must fail."""
        self.login(self.agent.email)
        stolen = self.refresh_cookie()

        self.client.post(self.refresh_url)  # rotates and blacklists `stolen`

        self.client.cookies[settings.AUTH_COOKIE_NAME] = stolen
        replay = self.client.post(self.refresh_url)

        self.assertEqual(replay.status_code, 401)

    def test_refresh_without_a_cookie_is_rejected(self):
        response = self.client.post(self.refresh_url)

        self.assertEqual(response.status_code, 401)
        self.assertIn("detail", response.data)

    def test_refresh_with_a_garbage_cookie_is_rejected(self):
        self.client.cookies[settings.AUTH_COOKIE_NAME] = "not-a-jwt"

        response = self.client.post(self.refresh_url)

        self.assertEqual(response.status_code, 401)

    def test_refresh_token_in_the_body_is_ignored(self):
        """Only the cookie counts — otherwise httpOnly would buy us nothing."""
        self.login(self.agent.email)
        token = self.refresh_cookie()
        self.client.cookies.clear()

        response = self.client.post(
            self.refresh_url, {"refresh": token}, format="json"
        )

        self.assertEqual(response.status_code, 401)

    def test_refresh_fails_after_the_user_is_deactivated(self):
        self.login(self.agent.email)
        self.agent.is_active = False
        self.agent.save()

        response = self.client.post(self.refresh_url)

        self.assertEqual(response.status_code, 401)


class LogoutTests(AuthAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.agent = self.make_agent()

    def test_logout_clears_the_cookie(self):
        self.login(self.agent.email)

        response = self.client.post(self.logout_url)

        self.assertEqual(response.status_code, 205)
        self.assertEqual(response.cookies[settings.AUTH_COOKIE_NAME].value, "")

    def test_logout_blacklists_the_refresh_token(self):
        self.login(self.agent.email)
        token = self.refresh_cookie()

        self.client.post(self.logout_url)

        # Even a copy taken before logout is dead.
        self.client.cookies[settings.AUTH_COOKIE_NAME] = token
        response = self.client.post(self.refresh_url)
        self.assertEqual(response.status_code, 401)

    def test_logout_without_a_session_is_not_an_error(self):
        response = self.client.post(self.logout_url)

        self.assertEqual(response.status_code, 205)


class RegisterTests(AuthAPITestCase):
    def test_register_creates_an_agent_and_logs_them_in(self):
        response = self.client.post(
            self.register_url,
            {
                "email": "new.agent@example.com",
                "full_name": "New Agent",
                "password": PASSWORD,
                "password_confirm": PASSWORD,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["access"])
        self.assertTrue(response.cookies[settings.AUTH_COOKIE_NAME]["httponly"])

        user = User.objects.get(email="new.agent@example.com")
        self.assertEqual(user.role, Role.AGENT)
        self.assertTrue(user.check_password(PASSWORD))

    def test_cannot_self_register_as_a_privileged_role(self):
        """Otherwise anyone could sign up as a Nehrux Admin."""
        response = self.client.post(
            self.register_url,
            {
                "email": "sneaky@example.com",
                "password": PASSWORD,
                "password_confirm": PASSWORD,
                "role": Role.NEHRUX_ADMIN,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("role", response.data)
        self.assertFalse(User.objects.filter(email="sneaky@example.com").exists())

    def test_duplicate_email_is_rejected(self):
        self.make_agent("taken@example.com")

        response = self.client.post(
            self.register_url,
            {
                "email": "taken@example.com",
                "password": PASSWORD,
                "password_confirm": PASSWORD,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)

    def test_mismatched_passwords_are_rejected(self):
        response = self.client.post(
            self.register_url,
            {
                "email": "mismatch@example.com",
                "password": PASSWORD,
                "password_confirm": "something-else-entirely",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("password_confirm", response.data)

    def test_weak_password_is_rejected(self):
        response = self.client.post(
            self.register_url,
            {
                "email": "weak@example.com",
                "password": "password",
                "password_confirm": "password",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.data)


class CurrentUserTests(AuthAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.agent = self.make_agent()

    def test_me_returns_the_authenticated_user(self):
        self.authenticate_as(self.agent)

        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["email"], self.agent.email)
        self.assertEqual(response.data["role"], Role.AGENT)
        self.assertEqual(response.data["role_display"], "Agent")

    def test_me_never_exposes_the_password_hash(self):
        self.authenticate_as(self.agent)

        response = self.client.get(self.me_url)

        self.assertNotIn("password", response.data)

    def test_me_without_a_token_is_rejected(self):
        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, 401)

    def test_me_with_a_malformed_token_is_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")

        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, 401)

    def test_the_refresh_cookie_alone_does_not_authenticate_api_calls(self):
        """Only the Authorization header authenticates ordinary requests."""
        self.login(self.agent.email)  # sets the cookie, no header

        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, 401)
