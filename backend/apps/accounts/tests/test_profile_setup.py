"""Registration and profile setup.

Registration asks for a name, an email and a password, and lands the agent in
the product rather than in a wizard. Everything else is optional and lives in
Settings, so a good deal of what is tested here is that the optional parts
really are optional: an account with an empty profile works, and the only
thing that ever insists is the export path.
"""

from __future__ import annotations

import shutil
import tempfile

from django.test import override_settings
from django.urls import reverse

from apps.accounts.completeness import (
    ProfileIncompleteError,
    assess_profile,
    require_marketing_ready,
)
from apps.accounts.models import AgentProfile, BrandKit, Brokerage, Role, User
from apps.accounts.tests.base import PASSWORD, AuthAPITestCase, make_image_file

MEDIA_ROOT = tempfile.mkdtemp(prefix="real-estate-profile-setup-media-")


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class ProfileSetupTestCase(AuthAPITestCase):
    completeness_url = reverse("profile_setup:completeness")
    directory_url = reverse("profile_setup:brokerage-directory")
    set_brokerage_url = reverse("profile_setup:set-brokerage")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def fully_complete(self, profile) -> None:
        """Fill everything a marketing asset needs."""
        brokerage = self.make_brokerage("Complete Realty")
        brokerage.logo = make_image_file("logo.png")
        brokerage.required_disclaimer = "All figures are a guide only."
        brokerage.save()

        profile.brokerage = brokerage
        profile.name = "Alex Agent"
        profile.phone = "+1 416 555 0100"
        profile.email = "alex@example.com"
        profile.job_title = "REALTOR®"
        profile.tagline = "Your Toronto home expert"
        profile.licence_number = "RECO-123456"
        profile.photo = make_image_file("headshot.png")
        profile.save()

        BrandKit.objects.update_or_create(agent=profile)
        profile.refresh_from_db()


class RegistrationTests(ProfileSetupTestCase):
    def test_registering_with_first_and_last_name(self):
        response = self.client.post(
            self.register_url,
            {
                "first_name": "John",
                "last_name": "Smith",
                "email": "john.smith@example.com",
                "password": PASSWORD,
                "password_confirm": PASSWORD,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        user = User.objects.get(email="john.smith@example.com")
        self.assertEqual(user.first_name, "John")
        self.assertEqual(user.last_name, "Smith")
        # Derived, so there is one source of truth rather than two fields to
        # keep in step.
        self.assertEqual(user.full_name, "John Smith")
        self.assertEqual(user.role, Role.AGENT)

    def test_the_role_is_always_agent(self):
        """Self-service registration must not be able to grant privilege."""
        response = self.client.post(
            self.register_url,
            {
                "first_name": "Sneaky",
                "last_name": "Person",
                "email": "sneaky@example.com",
                "password": PASSWORD,
                "password_confirm": PASSWORD,
                "role": Role.NEHRUX_ADMIN,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email="sneaky@example.com").exists())

    def test_a_name_is_required(self):
        response = self.client.post(
            self.register_url,
            {"email": "nameless@example.com", "password": PASSWORD, "password_confirm": PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("first_name", response.data)

    def test_full_name_alone_is_still_accepted(self):
        """The pre-existing shape keeps working."""
        response = self.client.post(
            self.register_url,
            {
                "full_name": "Legacy Caller",
                "email": "legacy@example.com",
                "password": PASSWORD,
                "password_confirm": PASSWORD,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)

    def test_the_password_is_hashed_and_the_confirmation_is_not_stored(self):
        self.client.post(
            self.register_url,
            {
                "first_name": "Jane", "last_name": "Doe",
                "email": "jane@example.com",
                "password": PASSWORD, "password_confirm": PASSWORD,
            },
            format="json",
        )
        user = User.objects.get(email="jane@example.com")

        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertFalse(hasattr(user, "password_confirm"))

    def test_registration_creates_the_agent_profile(self):
        """Empty, but present — so Settings has something to edit rather than
        the agent having to create their own profile before using one."""
        self.client.post(
            self.register_url,
            {
                "first_name": "New", "last_name": "Agent",
                "email": "new.agent@example.com",
                "password": PASSWORD, "password_confirm": PASSWORD,
            },
            format="json",
        )

        profile = AgentProfile.objects.get(user__email="new.agent@example.com")
        self.assertEqual(profile.name, "New Agent")

    def test_registration_returns_a_session(self):
        """A new agent lands in the dashboard, not on a sign-in form they just
        implicitly passed."""
        response = self.client.post(
            self.register_url,
            {
                "first_name": "Straight", "last_name": "Through",
                "email": "straight@example.com",
                "password": PASSWORD, "password_confirm": PASSWORD,
            },
            format="json",
        )

        self.assertTrue(response.data["access"])
        self.assertIn("refresh_token", response.cookies)


class BrokerageStepTests(ProfileSetupTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.agent = self.make_agent("agent@example.com")
        self.profile = self.agent.agent_profile
        self.authenticate_as(self.agent)

    def test_the_directory_finds_an_existing_brokerage(self):
        self.make_brokerage("Harbour & Co Realty")

        response = self.client.get(self.directory_url, {"search": "harbour"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["name"], "Harbour & Co Realty")

    def test_the_directory_is_empty_without_a_search_term(self):
        """A lookup tool, not a scrapeable list of every firm on the platform."""
        self.make_brokerage("Harbour & Co Realty")

        response = self.client.get(self.directory_url)

        self.assertEqual(response.data, [])

    def test_the_directory_exposes_only_public_facing_detail(self):
        brokerage = self.make_brokerage("Harbour & Co Realty")
        brokerage.required_disclaimer = "Internal-ish text"
        brokerage.save()

        response = self.client.get(self.directory_url, {"search": "harbour"})

        self.assertEqual(
            set(response.data[0]), {"id", "name", "logo_url", "agent_count"}
        )

    def test_an_agent_can_join_an_existing_brokerage(self):
        brokerage = self.make_brokerage("Harbour & Co Realty")

        response = self.client.post(
            self.set_brokerage_url, {"brokerage": brokerage.pk}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.brokerage, brokerage)
        # Joining is not administering.
        self.assertNotIn(self.agent, brokerage.admins.all())

    def test_an_agent_can_create_a_brokerage_during_onboarding(self):
        """Otherwise the first agent at a firm cannot finish onboarding."""
        response = self.client.post(
            self.set_brokerage_url,
            {
                "create": {
                    "name": "Brand New Realty",
                    "required_disclaimer": "A guide only.",
                    "licence_number": "BRK-9",
                }
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        brokerage = Brokerage.objects.get(name="Brand New Realty")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.brokerage, brokerage)
        # Whoever creates it administers it, or nobody can maintain it.
        self.assertIn(self.agent, brokerage.admins.all())

    def test_creating_a_duplicate_brokerage_is_refused(self):
        """Two rows for one firm would split its agents, logo and disclaimer."""
        self.make_brokerage("Harbour & Co Realty")

        response = self.client.post(
            self.set_brokerage_url,
            {"create": {"name": "  harbour & CO realty "}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Brokerage.objects.filter(name__icontains="harbour").count(), 1)

    def test_join_and_create_are_mutually_exclusive(self):
        brokerage = self.make_brokerage("Harbour & Co Realty")

        response = self.client.post(
            self.set_brokerage_url,
            {"brokerage": brokerage.pk, "create": {"name": "Another"}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_one_of_them_is_required(self):
        response = self.client.post(self.set_brokerage_url, {}, format="json")

        self.assertEqual(response.status_code, 400)

    def test_joining_requires_authentication(self):
        self.client.credentials()

        response = self.client.post(
            self.set_brokerage_url, {"brokerage": 1}, format="json"
        )

        self.assertEqual(response.status_code, 401)

    def test_creating_here_does_not_grant_the_general_create_permission(self):
        """The onboarding route is scoped; the admin endpoint is not opened up."""
        response = self.client.post(
            self.brokerages_url, {"name": "Back Door Realty"}, format="json"
        )

        self.assertEqual(response.status_code, 403)

    def create_own_brokerage(self, name: str = "Brand New Realty") -> Brokerage:
        self.client.post(
            self.set_brokerage_url, {"create": {"name": name}}, format="json"
        )
        return Brokerage.objects.get(name=name)

    def test_the_creator_can_supply_the_logo_their_own_exports_require(self):
        """The whole point of making them an admin.

        This was a real dead end: the creator was added to ``admins`` but kept
        the Agent *role*, and the permission checked the role, so onboarding
        finished by demanding a brokerage logo the agent was forbidden to
        upload.
        """
        brokerage = self.create_own_brokerage()

        response = self.client.patch(
            f"{self.brokerages_url}{brokerage.pk}/",
            {"logo": make_image_file("logo.png")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200, response.data)
        brokerage.refresh_from_db()
        self.assertTrue(brokerage.logo)

    def test_the_creator_can_set_the_disclaimer(self):
        brokerage = self.create_own_brokerage()

        response = self.client.patch(
            f"{self.brokerages_url}{brokerage.pk}/",
            {"required_disclaimer": "All figures are a guide only."},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)

    def test_the_creator_is_not_promoted_to_the_brokerage_admin_role(self):
        """Administering one firm is a fact about that firm, not a rank.

        Granting the role would have been the easy fix, and it would have handed
        out every brokerage-admin privilege platform-wide — including sight of
        other agents' listings at whichever firm they later joined.
        """
        self.create_own_brokerage()

        self.agent.refresh_from_db()
        self.assertEqual(self.agent.role, Role.AGENT)

    def test_administering_one_brokerage_grants_nothing_over_another(self):
        self.create_own_brokerage()
        someone_elses = self.make_brokerage("Harbour & Co Realty")

        response = self.client.patch(
            f"{self.brokerages_url}{someone_elses.pk}/",
            {"required_disclaimer": "Edited by an outsider"},
            format="json",
        )

        # 404: an agent cannot see a brokerage they neither belong to nor
        # administer, and saying "403" would confirm it exists.
        self.assertEqual(response.status_code, 404)
        someone_elses.refresh_from_db()
        self.assertNotEqual(
            someone_elses.required_disclaimer, "Edited by an outsider"
        )

    def test_merely_joining_a_brokerage_does_not_allow_editing_it(self):
        """Two agents at one firm must not be able to rewrite its disclaimer."""
        brokerage = self.make_brokerage("Harbour & Co Realty")
        self.client.post(
            self.set_brokerage_url, {"brokerage": brokerage.pk}, format="json"
        )

        response = self.client.patch(
            f"{self.brokerages_url}{brokerage.pk}/",
            {"required_disclaimer": "Edited by a member"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_a_member_can_still_read_their_brokerage(self):
        brokerage = self.make_brokerage("Harbour & Co Realty")
        self.client.post(
            self.set_brokerage_url, {"brokerage": brokerage.pk}, format="json"
        )

        response = self.client.get(f"{self.brokerages_url}{brokerage.pk}/")

        self.assertEqual(response.status_code, 200)

    def test_nobody_can_delete_a_brokerage_through_this_route(self):
        """Deleting one would orphan its agents, creator or not."""
        brokerage = self.create_own_brokerage()

        response = self.client.delete(f"{self.brokerages_url}{brokerage.pk}/")

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Brokerage.objects.filter(pk=brokerage.pk).exists())

    def test_the_creator_is_flagged_so_the_ui_can_show_them_the_screen(self):
        """The role says Agent, so the frontend needs telling another way.

        Without this the nav would hide the Brokerage screen from the one
        person able to fill in the logo their exports are blocked on.
        """
        self.assertFalse(self.client.get(self.me_url).data["administers_brokerage"])

        self.create_own_brokerage()

        self.assertTrue(self.client.get(self.me_url).data["administers_brokerage"])

    def test_joining_does_not_flag_the_agent(self):
        brokerage = self.make_brokerage("Harbour & Co Realty")
        self.client.post(
            self.set_brokerage_url, {"brokerage": brokerage.pk}, format="json"
        )

        self.assertFalse(self.client.get(self.me_url).data["administers_brokerage"])

    def test_creating_a_brokerage_still_cannot_be_done_at_the_general_endpoint(self):
        """Relaxing the object check must not relax the create check."""
        self.create_own_brokerage()

        response = self.client.post(
            self.brokerages_url, {"name": "Second Firm"}, format="json"
        )

        self.assertEqual(response.status_code, 403)


class CompletionTests(ProfileSetupTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.agent = self.make_agent("agent@example.com")
        self.profile = self.agent.agent_profile
        self.authenticate_as(self.agent)

    def test_a_bare_profile_is_not_ready(self):
        assessment = assess_profile(self.profile)

        self.assertLess(assessment["completion_percent"], 100)
        self.assertFalse(assessment["ready_for_marketing"])
        self.assertTrue(assessment["missing_required"])

    def test_a_complete_profile_is_ready(self):
        self.fully_complete(self.profile)

        assessment = assess_profile(self.profile)

        self.assertEqual(assessment["completion_percent"], 100)
        self.assertTrue(assessment["ready_for_marketing"])
        self.assertEqual(assessment["missing_required"], [])

    def test_optional_fields_lower_the_percentage_without_blocking(self):
        """80% and ready is a real state; the two answer different questions."""
        self.fully_complete(self.profile)
        self.profile.tagline = ""
        self.profile.licence_number = ""
        self.profile.save()

        assessment = assess_profile(self.profile)

        self.assertLess(assessment["completion_percent"], 100)
        self.assertTrue(assessment["ready_for_marketing"])

    def test_each_missing_field_names_the_screen_that_fixes_it(self):
        """"Something is missing" is not an actionable message."""
        assessment = assess_profile(self.profile)

        for row in assessment["missing_required"]:
            with self.subTest(field=row["key"]):
                self.assertIn(row["step"], {"profile", "brokerage", "brand"})
                self.assertTrue(row["label"])
                self.assertTrue(row["fix_path"].startswith("/"))

    def test_an_agent_with_no_brokerage_is_sent_somewhere_they_can_go(self):
        """/brokerage administers a brokerage you are already in.

        Pointing an agent who has none at that screen would bounce them off a
        route guard, so the link has to be the profile screen — which is where
        joining or creating one lives — until they have one.
        """
        rows = {row["key"]: row for row in assess_profile(self.profile)["fields"]}

        self.assertEqual(rows["brokerage"]["fix_path"], "/profile")

    def test_once_they_have_one_the_link_moves_to_the_brokerage_screen(self):
        self.fully_complete(self.profile)
        self.profile.brokerage.required_disclaimer = ""
        self.profile.brokerage.save()
        self.profile.refresh_from_db()

        rows = {row["key"]: row for row in assess_profile(self.profile)["fields"]}

        self.assertEqual(rows["brokerage_disclaimer"]["fix_path"], "/brokerage")

    def test_a_brokerage_brand_kit_counts_as_branding(self):
        """Matches how the renderer resolves branding, so completion cannot
        claim a brand is missing when the render would have found one."""
        self.fully_complete(self.profile)
        BrandKit.objects.filter(agent=self.profile).delete()
        BrandKit.objects.create(brokerage=self.profile.brokerage)
        self.profile.refresh_from_db()

        self.assertTrue(assess_profile(self.profile)["ready_for_marketing"])

    def test_no_profile_at_all_is_zero(self):
        assessment = assess_profile(None)

        self.assertEqual(assessment["completion_percent"], 0)
        self.assertFalse(assessment["ready_for_marketing"])

    def test_the_completeness_endpoint_reports_without_demanding(self):
        response = self.client.get(self.completeness_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data),
            {
                "completion_percent",
                "is_complete",
                "ready_for_marketing",
                "missing_required",
                "missing_optional",
                "by_step",
            },
        )
        self.assertEqual(set(response.data["by_step"]), {"profile", "brokerage", "brand"})

    def test_another_agents_progress_is_not_visible(self):
        other = self.make_agent("other@example.com")
        self.fully_complete(other.agent_profile)

        response = self.client.get(self.completeness_url)

        # Own profile only — bare, not the complete one belonging to someone else.
        self.assertFalse(response.data["ready_for_marketing"])

    def test_completeness_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.client.get(self.completeness_url).status_code, 401)


class NothingIsRequiredUpFrontTests(ProfileSetupTestCase):
    """The point of the refactor: an empty profile is a working account.

    An agent evaluating the product, or waiting on their brokerage to approve
    the spend, must be able to get value out of it before they have a licence
    number or a firm to name.
    """

    def setUp(self) -> None:
        super().setUp()
        self.agent = self.make_agent("agent@example.com")
        self.profile = self.agent.agent_profile
        self.authenticate_as(self.agent)

    def test_registration_asks_for_nothing_beyond_name_email_password(self):
        response = self.client.post(
            self.register_url,
            {
                "first_name": "Minimal", "last_name": "Signup",
                "email": "minimal@example.com",
                "password": PASSWORD, "password_confirm": PASSWORD,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        profile = AgentProfile.objects.get(user__email="minimal@example.com")
        self.assertIsNone(profile.brokerage)
        self.assertEqual(profile.licence_number, "")
        self.assertFalse(BrandKit.objects.filter(agent=profile).exists())

    def test_an_agent_with_no_brokerage_can_still_use_the_product(self):
        """No brokerage, no brand kit, no licence — and every screen works."""
        for url in (self.agent_me_url, self.brand_kit_mine_url, self.completeness_url):
            with self.subTest(url=url):
                self.assertIn(self.client.get(url).status_code, (200, 201))

    def test_the_brand_kit_is_created_on_demand_not_at_signup(self):
        self.assertFalse(BrandKit.objects.filter(agent=self.profile).exists())

        response = self.client.get(self.brand_kit_mine_url)

        self.assertIn(response.status_code, (200, 201))
        self.assertTrue(BrandKit.objects.filter(agent=self.profile).exists())

    def test_a_bare_profile_reports_gaps_without_erroring(self):
        """The prompt is advice. Nothing about it is a failure state."""
        response = self.client.get(self.completeness_url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["ready_for_marketing"])
        self.assertTrue(response.data["missing_required"])

    def test_the_wizard_endpoints_are_gone(self):
        """Nothing should be able to put an agent back into a forced sequence."""
        for path in ("/api/onboarding/status/", "/api/onboarding/complete/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


class MarketingGateTests(ProfileSetupTestCase):
    """The check that stops an asset rendering with a hole in it."""

    def setUp(self) -> None:
        super().setUp()
        self.agent = self.make_agent("agent@example.com")
        self.profile = self.agent.agent_profile

    def test_an_incomplete_profile_raises(self):
        with self.assertRaises(ProfileIncompleteError) as ctx:
            require_marketing_ready(self.profile)

        self.assertTrue(ctx.exception.missing)

    def test_the_error_names_the_fields_and_the_steps(self):
        try:
            require_marketing_ready(self.profile)
        except ProfileIncompleteError as exc:
            payload = exc.as_dict()

        self.assertIn("missing", payload)
        self.assertIn("steps", payload)
        self.assertTrue(payload["detail"])
        # The message lists the actual field names, not a generic apology.
        self.assertIn("Brokerage", payload["detail"])

    def test_a_complete_profile_passes(self):
        self.fully_complete(self.profile)

        require_marketing_ready(self.profile)  # does not raise

    def test_a_missing_logo_alone_blocks_it(self):
        """The specific case in the brief: 80% complete, still not publishable."""
        self.fully_complete(self.profile)
        self.profile.brokerage.logo = None
        self.profile.brokerage.save()
        self.profile.refresh_from_db()

        with self.assertRaises(ProfileIncompleteError) as ctx:
            require_marketing_ready(self.profile)

        self.assertEqual(
            [row["key"] for row in ctx.exception.missing], ["brokerage_logo"]
        )
