"""Tests for role-based access control.

Covers the two axes that matter: *no* credentials (401) and the *wrong* role
(403).
"""

from __future__ import annotations

from apps.accounts.models import ROLE_LEVELS, Role
from apps.accounts.tests.base import AuthAPITestCase


class NehruxAdminOnlyEndpointTests(AuthAPITestCase):
    """``/api/admin/platform-overview/`` is restricted to Nehrux Admins."""

    def test_nehrux_admin_is_allowed(self):
        self.authenticate_as(self.make_nehrux_admin())

        response = self.client.get(self.platform_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["scope"], "platform")

    def test_agent_is_denied(self):
        self.authenticate_as(self.make_agent())

        response = self.client.get(self.platform_url)

        self.assertEqual(response.status_code, 403)

    def test_brokerage_admin_is_denied(self):
        """An exact-role gate: even the second-highest role is refused."""
        self.authenticate_as(self.make_brokerage_admin())

        response = self.client.get(self.platform_url)

        self.assertEqual(response.status_code, 403)

    def test_request_without_a_token_is_rejected_as_unauthenticated(self):
        response = self.client.get(self.platform_url)

        self.assertEqual(response.status_code, 401)

    def test_deactivated_user_is_denied_even_with_a_valid_token(self):
        """The token is still signed and unexpired — the user is not."""
        admin = self.make_nehrux_admin()
        self.authenticate_as(admin)

        admin.is_active = False
        admin.save()

        response = self.client.get(self.platform_url)

        self.assertIn(response.status_code, (401, 403))


class HierarchicalPermissionTests(AuthAPITestCase):
    """``/api/admin/brokerage-overview/`` allows Brokerage Admin *and above*."""

    def test_brokerage_admin_is_allowed(self):
        self.authenticate_as(self.make_brokerage_admin())

        response = self.client.get(self.brokerage_url)

        self.assertEqual(response.status_code, 200)

    def test_nehrux_admin_inherits_access(self):
        self.authenticate_as(self.make_nehrux_admin())

        response = self.client.get(self.brokerage_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["role"], Role.NEHRUX_ADMIN)

    def test_agent_is_denied(self):
        self.authenticate_as(self.make_agent())

        response = self.client.get(self.brokerage_url)

        self.assertEqual(response.status_code, 403)

    def test_no_token_is_rejected(self):
        response = self.client.get(self.brokerage_url)

        self.assertEqual(response.status_code, 401)


class RoleEscalationTests(AuthAPITestCase):
    def test_role_change_takes_effect_on_the_next_refresh(self):
        """Role lives in the database, not just in the token's claims."""
        user = self.make_agent()
        self.authenticate_as(user)
        self.assertEqual(self.client.get(self.brokerage_url).status_code, 403)

        user.role = Role.BROKERAGE_ADMIN
        user.save()

        # The old access token carries role=agent as a claim, but permissions
        # read request.user.role from the database, so access is granted now.
        response = self.client.get(self.brokerage_url)
        self.assertEqual(response.status_code, 200)

    def test_demotion_revokes_access_immediately(self):
        user = self.make_nehrux_admin()
        self.authenticate_as(user)
        self.assertEqual(self.client.get(self.platform_url).status_code, 200)

        user.role = Role.AGENT
        user.save()

        self.assertEqual(self.client.get(self.platform_url).status_code, 403)


class RoleModelTests(AuthAPITestCase):
    def test_role_hierarchy_ordering(self):
        self.assertLess(ROLE_LEVELS[Role.AGENT], ROLE_LEVELS[Role.BROKERAGE_ADMIN])
        self.assertLess(
            ROLE_LEVELS[Role.BROKERAGE_ADMIN], ROLE_LEVELS[Role.NEHRUX_ADMIN]
        )

    def test_has_role_at_least(self):
        agent = self.make_agent()
        nehrux = self.make_nehrux_admin()

        self.assertTrue(agent.has_role_at_least(Role.AGENT))
        self.assertFalse(agent.has_role_at_least(Role.BROKERAGE_ADMIN))
        self.assertTrue(nehrux.has_role_at_least(Role.BROKERAGE_ADMIN))

    def test_unknown_role_has_no_privilege(self):
        """Fail closed: a role value we do not recognise grants nothing."""
        user = self.make_agent()
        user.role = "some_future_role"

        self.assertEqual(user.role_level, 0)
        self.assertFalse(user.has_role_at_least(Role.AGENT))

    def test_default_role_is_agent(self):
        user = self.make_user("plain@example.com")

        self.assertEqual(user.role, Role.AGENT)
        self.assertFalse(user.is_staff)

    def test_superuser_is_a_nehrux_admin(self):
        from django.contrib.auth import get_user_model

        superuser = get_user_model().objects.create_superuser(
            email="root@example.com", password="a-long-enough-password"
        )

        self.assertEqual(superuser.role, Role.NEHRUX_ADMIN)
        self.assertTrue(superuser.is_staff)
        self.assertTrue(superuser.is_superuser)
