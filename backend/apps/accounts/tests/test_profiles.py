"""CRUD and permission-boundary tests for brokerages, agents and brand kits.

The boundary cases are the point of this file: an agent must not be able to
reach another agent's profile, another brokerage's records, or promote
themselves by editing a field they should not control.

Note the two failure modes, which are both correct and mean different things:

  * 404 — the record is outside the caller's queryset. The API does not
    confirm that it exists.
  * 403 — the record is visible (a colleague, say) but the caller may not
    change it.
"""

from __future__ import annotations

from apps.accounts.models import AgentProfile, BrandKit, Brokerage, DesignStyle
from apps.accounts.tests.base import AuthAPITestCase


class BrokerageCrudTests(AuthAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.nehrux = self.make_nehrux_admin()
        self.broker_admin = self.make_brokerage_admin("admin.acme@example.com")
        self.acme = self.make_brokerage("Acme Realty", self.broker_admin)

    # -- create -------------------------------------------------------------

    def test_nehrux_admin_can_create_a_brokerage(self):
        self.authenticate_as(self.nehrux)

        response = self.client.post(
            self.brokerages_url,
            {"name": "New Horizons", "required_disclaimer": "Licensed in NSW."},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Brokerage.objects.filter(name="New Horizons").exists())

    def test_brokerage_admin_cannot_create_a_brokerage(self):
        """Creating an organisation is a platform-level action."""
        self.authenticate_as(self.broker_admin)

        response = self.client.post(
            self.brokerages_url, {"name": "Self Serve Realty"}, format="json"
        )

        self.assertEqual(response.status_code, 403)

    def test_agent_cannot_create_a_brokerage(self):
        agent, _ = self.make_agent_in(self.acme)
        self.authenticate_as(agent)

        response = self.client.post(
            self.brokerages_url, {"name": "Agent Realty"}, format="json"
        )

        self.assertEqual(response.status_code, 403)

    # -- read ---------------------------------------------------------------

    def test_nehrux_admin_sees_every_brokerage(self):
        self.make_brokerage("Other Realty")
        self.authenticate_as(self.nehrux)

        response = self.client.get(self.brokerages_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)

    def test_brokerage_admin_sees_only_brokerages_they_administer(self):
        self.make_brokerage("Other Realty")
        self.authenticate_as(self.broker_admin)

        response = self.client.get(self.brokerages_url)

        names = [row["name"] for row in response.data["results"]]
        self.assertEqual(names, ["Acme Realty"])

    def test_agent_sees_only_their_own_brokerage(self):
        other = self.make_brokerage("Other Realty")
        agent, _ = self.make_agent_in(self.acme)
        self.authenticate_as(agent)

        response = self.client.get(self.brokerages_url)
        self.assertEqual([row["name"] for row in response.data["results"]], ["Acme Realty"])

        # And cannot reach the other one directly.
        self.assertEqual(
            self.client.get(self.brokerage_detail_url(other)).status_code, 404
        )

    # -- update -------------------------------------------------------------

    def test_brokerage_admin_can_edit_their_own_brokerage(self):
        self.authenticate_as(self.broker_admin)

        response = self.client.patch(
            self.brokerage_detail_url(self.acme),
            {"required_disclaimer": "All figures are estimates."},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.acme.refresh_from_db()
        self.assertEqual(self.acme.required_disclaimer, "All figures are estimates.")

    def test_brokerage_admin_cannot_edit_a_different_brokerage(self):
        """The core cross-tenant boundary."""
        other = self.make_brokerage("Other Realty")
        self.authenticate_as(self.broker_admin)

        response = self.client.patch(
            self.brokerage_detail_url(other), {"name": "Hijacked"}, format="json"
        )

        # 404: the other brokerage is not in this admin's queryset at all.
        self.assertEqual(response.status_code, 404)
        other.refresh_from_db()
        self.assertEqual(other.name, "Other Realty")

    def test_agent_cannot_edit_their_brokerage(self):
        agent, _ = self.make_agent_in(self.acme)
        self.authenticate_as(agent)

        response = self.client.patch(
            self.brokerage_detail_url(self.acme),
            {"required_disclaimer": "Rewritten by an agent."},
            format="json",
        )

        # Visible to them, but read-only: 403 rather than 404.
        self.assertEqual(response.status_code, 403)

    # -- delete -------------------------------------------------------------

    def test_only_nehrux_admin_can_delete_a_brokerage(self):
        self.authenticate_as(self.broker_admin)
        self.assertEqual(
            self.client.delete(self.brokerage_detail_url(self.acme)).status_code, 403
        )

        self.authenticate_as(self.nehrux)
        self.assertEqual(
            self.client.delete(self.brokerage_detail_url(self.acme)).status_code, 204
        )
        self.assertFalse(Brokerage.objects.filter(pk=self.acme.pk).exists())

    def test_deleting_a_brokerage_keeps_its_agents(self):
        """SET_NULL, not CASCADE: losing an employer is not losing a profile."""
        _, profile = self.make_agent_in(self.acme)
        self.authenticate_as(self.nehrux)

        self.client.delete(self.brokerage_detail_url(self.acme))

        profile.refresh_from_db()
        self.assertIsNone(profile.brokerage)

    def test_unauthenticated_access_is_rejected(self):
        self.assertEqual(self.client.get(self.brokerages_url).status_code, 401)


class AgentProfileCrudTests(AuthAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.nehrux = self.make_nehrux_admin()
        self.broker_admin = self.make_brokerage_admin("admin.acme@example.com")
        self.acme = self.make_brokerage("Acme Realty", self.broker_admin)
        self.rival = self.make_brokerage("Rival Realty")

        self.agent, self.agent_profile = self.make_agent_in(self.acme, "a1@example.com")
        self.colleague, self.colleague_profile = self.make_agent_in(
            self.acme, "a2@example.com"
        )
        self.outsider, self.outsider_profile = self.make_agent_in(
            self.rival, "rival@example.com"
        )

    # -- auto-provisioning --------------------------------------------------

    def test_registering_an_agent_creates_their_profile(self):
        response = self.client.post(
            self.register_url,
            {
                "email": "brand.new@example.com",
                "full_name": "Brand New",
                "password": "correct-horse-battery",
                "password_confirm": "correct-horse-battery",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)

        profile = AgentProfile.objects.get(user__email="brand.new@example.com")
        # Defaults are copied from the user so the form is not blank.
        self.assertEqual(profile.name, "Brand New")
        self.assertEqual(profile.email, "brand.new@example.com")

    def test_brokerage_admin_does_not_get_an_agent_profile(self):
        self.assertFalse(
            AgentProfile.objects.filter(user=self.broker_admin).exists()
        )

    # -- /me/ ---------------------------------------------------------------

    def test_agent_can_read_their_own_profile_via_me(self):
        self.authenticate_as(self.agent)

        response = self.client.get(self.agent_me_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], self.agent_profile.pk)
        self.assertEqual(response.data["brokerage_detail"]["name"], "Acme Realty")

    def test_agent_can_edit_their_own_profile(self):
        self.authenticate_as(self.agent)

        response = self.client.patch(
            self.agent_me_url,
            {
                "name": "Alex Agent",
                "job_title": "Senior Sales Agent",
                "tagline": "Local expertise, global reach",
                "phone": "+61 400 000 000",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.agent_profile.refresh_from_db()
        self.assertEqual(self.agent_profile.name, "Alex Agent")
        self.assertEqual(self.agent_profile.job_title, "Senior Sales Agent")

    def test_agent_cannot_move_themselves_to_another_brokerage(self):
        """Otherwise 'edit your profile' would mean 'join any brokerage'."""
        self.authenticate_as(self.agent)

        response = self.client.patch(
            self.agent_me_url, {"brokerage": self.rival.pk}, format="json"
        )

        self.assertEqual(response.status_code, 200)  # other fields would apply
        self.agent_profile.refresh_from_db()
        self.assertEqual(self.agent_profile.brokerage, self.acme)  # unchanged

    def test_agent_cannot_reassign_their_profile_to_another_user(self):
        self.authenticate_as(self.agent)

        self.client.patch(
            self.agent_me_url, {"user": self.colleague.pk}, format="json"
        )

        self.agent_profile.refresh_from_db()
        self.assertEqual(self.agent_profile.user, self.agent)

    def test_me_requires_authentication(self):
        self.assertEqual(self.client.get(self.agent_me_url).status_code, 401)

    def test_me_returns_404_for_a_user_without_a_profile(self):
        self.authenticate_as(self.broker_admin)

        self.assertEqual(self.client.get(self.agent_me_url).status_code, 404)

    # -- cross-agent boundaries --------------------------------------------

    def test_agent_cannot_edit_a_colleague_in_the_same_brokerage(self):
        """Visible in the directory, but not editable: 403."""
        self.authenticate_as(self.agent)

        response = self.client.patch(
            self.agent_detail_url(self.colleague_profile),
            {"tagline": "Edited by someone else"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.colleague_profile.refresh_from_db()
        self.assertEqual(self.colleague_profile.tagline, "")

    def test_agent_cannot_see_or_edit_an_agent_at_another_brokerage(self):
        self.authenticate_as(self.agent)

        detail_url = self.agent_detail_url(self.outsider_profile)
        self.assertEqual(self.client.get(detail_url).status_code, 404)
        self.assertEqual(
            self.client.patch(detail_url, {"tagline": "x"}, format="json").status_code,
            404,
        )

    def test_agent_list_is_scoped_to_their_own_brokerage(self):
        self.authenticate_as(self.agent)

        response = self.client.get(self.agents_url)

        emails = {row["user_email"] for row in response.data["results"]}
        self.assertEqual(emails, {"a1@example.com", "a2@example.com"})

    def test_agent_cannot_create_a_profile_for_someone_else(self):
        new_user = self.make_user("unclaimed@example.com")
        self.authenticate_as(self.agent)

        response = self.client.post(
            self.agents_url, {"user": new_user.pk, "name": "Puppet"}, format="json"
        )

        self.assertEqual(response.status_code, 403)

    def test_agent_cannot_delete_their_own_profile(self):
        self.authenticate_as(self.agent)

        response = self.client.delete(self.agent_detail_url(self.agent_profile))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(AgentProfile.objects.filter(pk=self.agent_profile.pk).exists())

    # -- brokerage admin ----------------------------------------------------

    def test_brokerage_admin_can_edit_their_own_agents(self):
        self.authenticate_as(self.broker_admin)

        response = self.client.patch(
            self.agent_detail_url(self.agent_profile),
            {"job_title": "Team Lead"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.agent_profile.refresh_from_db()
        self.assertEqual(self.agent_profile.job_title, "Team Lead")

    def test_brokerage_admin_cannot_touch_agents_at_another_brokerage(self):
        self.authenticate_as(self.broker_admin)

        detail_url = self.agent_detail_url(self.outsider_profile)
        self.assertEqual(self.client.get(detail_url).status_code, 404)
        self.assertEqual(
            self.client.patch(detail_url, {"job_title": "x"}, format="json").status_code,
            404,
        )

    def test_brokerage_admin_can_create_an_agent_profile_in_their_brokerage(self):
        new_user = self.make_user("hire@example.com")
        AgentProfile.objects.filter(user=new_user).delete()
        self.authenticate_as(self.broker_admin)

        response = self.client.post(
            self.agents_url,
            {"user": new_user.pk, "brokerage": self.acme.pk, "name": "New Hire"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(AgentProfile.objects.get(user=new_user).brokerage, self.acme)

    def test_brokerage_admin_cannot_place_an_agent_in_another_brokerage(self):
        new_user = self.make_user("hire2@example.com")
        AgentProfile.objects.filter(user=new_user).delete()
        self.authenticate_as(self.broker_admin)

        response = self.client.post(
            self.agents_url,
            {"user": new_user.pk, "brokerage": self.rival.pk, "name": "Plant"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("brokerage", response.data)

    def test_duplicate_profile_for_the_same_user_is_rejected(self):
        self.authenticate_as(self.broker_admin)

        response = self.client.post(
            self.agents_url,
            {"user": self.agent.pk, "brokerage": self.acme.pk, "name": "Clone"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("user", response.data)

    def test_brokerage_admin_can_remove_one_of_their_agents(self):
        self.authenticate_as(self.broker_admin)

        response = self.client.delete(self.agent_detail_url(self.colleague_profile))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            AgentProfile.objects.filter(pk=self.colleague_profile.pk).exists()
        )

    # -- nehrux admin -------------------------------------------------------

    def test_nehrux_admin_sees_and_edits_every_profile(self):
        self.authenticate_as(self.nehrux)

        self.assertEqual(self.client.get(self.agents_url).data["count"], 3)

        response = self.client.patch(
            self.agent_detail_url(self.outsider_profile),
            {"brokerage": self.acme.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.outsider_profile.refresh_from_db()
        self.assertEqual(self.outsider_profile.brokerage, self.acme)


class BrandKitCrudTests(AuthAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.nehrux = self.make_nehrux_admin()
        self.broker_admin = self.make_brokerage_admin("admin.acme@example.com")
        self.acme = self.make_brokerage("Acme Realty", self.broker_admin)
        self.rival = self.make_brokerage("Rival Realty")

        self.agent, self.agent_profile = self.make_agent_in(self.acme, "a1@example.com")
        self.outsider, self.outsider_profile = self.make_agent_in(
            self.rival, "rival@example.com"
        )

    def test_mine_creates_a_kit_on_first_call_and_reuses_it_after(self):
        self.authenticate_as(self.agent)

        first = self.client.get(self.brand_kit_mine_url)
        second = self.client.get(self.brand_kit_mine_url)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(first.data["owner_type"], "agent")
        self.assertEqual(BrandKit.objects.filter(agent=self.agent_profile).count(), 1)

    def test_agent_can_update_their_own_kit(self):
        self.authenticate_as(self.agent)
        kit_id = self.client.get(self.brand_kit_mine_url).data["id"]

        response = self.client.patch(
            self.brand_kit_detail_url(BrandKit.objects.get(pk=kit_id)),
            {
                "primary_color": "#0F172A",
                "heading_font": "Playfair Display",
                "design_style": DesignStyle.LUXURY,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        kit = BrandKit.objects.get(pk=kit_id)
        self.assertEqual(kit.primary_color, "#0F172A")
        self.assertEqual(kit.design_style, DesignStyle.LUXURY)

    def test_invalid_hex_colour_is_rejected(self):
        self.authenticate_as(self.agent)
        kit_id = self.client.get(self.brand_kit_mine_url).data["id"]

        response = self.client.patch(
            self.brand_kit_detail_url(BrandKit.objects.get(pk=kit_id)),
            {"primary_color": "not-a-colour"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("primary_color", response.data)

    def test_kit_must_have_exactly_one_owner(self):
        self.authenticate_as(self.nehrux)

        neither = self.client.post(self.brand_kits_url, {}, format="json")
        both = self.client.post(
            self.brand_kits_url,
            {"agent": self.agent_profile.pk, "brokerage": self.acme.pk},
            format="json",
        )

        self.assertEqual(neither.status_code, 400)
        self.assertEqual(both.status_code, 400)

    def test_agent_cannot_create_a_kit_for_another_agent(self):
        self.authenticate_as(self.agent)

        response = self.client.post(
            self.brand_kits_url, {"agent": self.outsider_profile.pk}, format="json"
        )

        self.assertEqual(response.status_code, 400)

    def test_agent_can_read_but_not_edit_their_brokerage_kit(self):
        kit = BrandKit.objects.create(brokerage=self.acme, primary_color="#111111")
        self.authenticate_as(self.agent)

        detail_url = self.brand_kit_detail_url(kit)
        self.assertEqual(self.client.get(detail_url).status_code, 200)

        response = self.client.patch(
            detail_url, {"primary_color": "#FFFFFF"}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        kit.refresh_from_db()
        self.assertEqual(kit.primary_color, "#111111")

    def test_agent_cannot_see_another_brokerages_kit(self):
        kit = BrandKit.objects.create(brokerage=self.rival)
        self.authenticate_as(self.agent)

        self.assertEqual(self.client.get(self.brand_kit_detail_url(kit)).status_code, 404)

    def test_brokerage_admin_can_edit_their_brokerage_kit(self):
        kit = BrandKit.objects.create(brokerage=self.acme)
        self.authenticate_as(self.broker_admin)

        response = self.client.patch(
            self.brand_kit_detail_url(kit), {"body_font": "Source Serif"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        kit.refresh_from_db()
        self.assertEqual(kit.body_font, "Source Serif")

    def test_brokerage_admin_can_edit_their_agents_kits(self):
        kit = BrandKit.objects.create(agent=self.agent_profile)
        self.authenticate_as(self.broker_admin)

        response = self.client.patch(
            self.brand_kit_detail_url(kit), {"accent_color": "#DC2626"}, format="json"
        )

        self.assertEqual(response.status_code, 200)

    def test_brokerage_admin_cannot_edit_a_rival_kit(self):
        kit = BrandKit.objects.create(brokerage=self.rival)
        self.authenticate_as(self.broker_admin)

        response = self.client.patch(
            self.brand_kit_detail_url(kit), {"accent_color": "#DC2626"}, format="json"
        )

        self.assertEqual(response.status_code, 404)

    def test_owner_cannot_be_reassigned_after_creation(self):
        """Reassigning the owner would be a write to a record you don't own."""
        kit = BrandKit.objects.create(agent=self.agent_profile)
        self.authenticate_as(self.agent)

        self.client.patch(
            self.brand_kit_detail_url(kit),
            {"agent": self.outsider_profile.pk},
            format="json",
        )

        kit.refresh_from_db()
        self.assertEqual(kit.agent, self.agent_profile)

    def test_deleting_an_agent_removes_their_kit(self):
        BrandKit.objects.create(agent=self.agent_profile)
        self.authenticate_as(self.nehrux)

        self.client.delete(self.agent_detail_url(self.agent_profile))

        self.assertFalse(BrandKit.objects.filter(agent_id=self.agent_profile.pk).exists())

    def test_unauthenticated_access_is_rejected(self):
        self.assertEqual(self.client.get(self.brand_kits_url).status_code, 401)
