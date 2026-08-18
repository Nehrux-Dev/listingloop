"""Create (or reset) the sign-in for one of the staff dashboards.

WHY A COMMAND AND NOT A MIGRATION OR A SIGN-UP FORM
------------------------------------------------------------------------------
Registration only ever hands out the ``agent`` role — ``SELF_ASSIGNABLE_ROLES``
sees to that — because anyone who could pick their own role could pick the one
that publishes templates into every agency's gallery. And a migration that
creates a privileged account runs on every environment that applies it,
including ones nobody meant to give that account to. So elevated accounts are
made by somebody deciding to run this, on a server they already have access to.

The password comes from ``--password`` or the environment, never from this
file, so the credential does not live in the repository alongside the code that
uses it.

Re-runnable: an existing account is updated rather than duplicated, which makes
this the way to reset a password as well as the way to create one.

    manage.py create_dashboard_login --dashboard platform --password '...'
    manage.py create_dashboard_login --dashboard agency  --password '...'
"""

from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import AgentProfile, Brokerage, Role, User

#: The two staff dashboards, and what an account needs to sign in to each.
#:
#: The e-mail's local part is the username: ``LoginSerializer`` resolves a bare
#: name to the single address that starts with it, so "agency" reaches
#: ``agency@nehrux.com``. Two accounts sharing a local part would make the name
#: ambiguous and neither would resolve — which is why these defaults are on one
#: domain rather than borrowing the seed data's ``@nehrux.test``.
DASHBOARDS = {
    "platform": {
        "email": "nehrux@nehrux.com",
        "role": Role.NEHRUX_ADMIN,
        "first_name": "Nehrux",
        "last_name": "Admin",
        "env": "NEHRUX_ADMIN_PASSWORD",
        "lands_on": "/platform",
    },
    "agency": {
        "email": "agency@nehrux.com",
        "role": Role.BROKERAGE_ADMIN,
        "first_name": "Agency",
        "last_name": "Admin",
        "env": "AGENCY_ADMIN_PASSWORD",
        "lands_on": "/admin",
    },
}

#: A brokerage admin with no brokerage can reach their dashboard and find
#: nothing on it — every panel there is scoped to the firm they administer. So
#: the agency login is attached to one, created if it does not exist.
DEFAULT_BROKERAGE = "Demo Agency"


class Command(BaseCommand):
    help = "Create or reset the login for the agency or platform dashboard."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--dashboard", choices=sorted(DASHBOARDS), required=True)
        parser.add_argument(
            "--email",
            default=None,
            help="Overrides the default address for that dashboard.",
        )
        parser.add_argument(
            "--password",
            default=None,
            help="Falls back to the dashboard's password environment variable.",
        )
        parser.add_argument(
            "--brokerage",
            default=DEFAULT_BROKERAGE,
            help=f"Agency dashboard only. Default: {DEFAULT_BROKERAGE!r}.",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        spec = DASHBOARDS[options["dashboard"]]
        email = str(options["email"] or spec["email"]).strip().lower()
        password = options["password"] or os.environ.get(spec["env"])

        user = User.objects.filter(email__iexact=email).first()
        if user is None and not password:
            raise CommandError(
                f"No such account yet, so a password is required: pass "
                f"--password or set ${spec['env']}."
            )

        created = user is None
        if created:
            user = User.objects.create_user(
                email=email,
                password=password,
                role=spec["role"],
                first_name=spec["first_name"],
                last_name=spec["last_name"],
                is_staff=spec["role"] == Role.NEHRUX_ADMIN,
                is_superuser=spec["role"] == Role.NEHRUX_ADMIN,
            )
        else:
            # Re-asserted rather than left alone: the whole reason to run this
            # is to be certain this account can reach that dashboard.
            user.role = spec["role"]
            user.is_active = True
            if spec["role"] == Role.NEHRUX_ADMIN:
                user.is_staff = True
                user.is_superuser = True
            if password:
                user.set_password(password)
            user.save()

        # Both dashboards touch endpoints that hang off a profile — uploads are
        # owned by one, and the brand kit is keyed to one. The signal that
        # creates a profile fires only for the agent role, so staff accounts
        # need theirs made here or those endpoints answer 403.
        AgentProfile.objects.get_or_create(
            user=user,
            defaults={"name": f"{spec['first_name']} {spec['last_name']}"},
        )

        if spec["role"] == Role.BROKERAGE_ADMIN:
            brokerage, _ = Brokerage.objects.get_or_create(name=options["brokerage"])
            brokerage.admins.add(user)
            # Their own profile joins the firm too, so the agency dashboard's
            # counts describe a real brokerage rather than an empty one.
            profile = AgentProfile.objects.filter(user=user).first()
            if profile and profile.brokerage_id is None:
                profile.brokerage = brokerage
                profile.save(update_fields=["brokerage", "updated_at"])
            self.stdout.write(f"Administers: {brokerage.name}")

        username = email.split("@", 1)[0]
        self.stdout.write(
            self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} {options['dashboard']} login: "
                f"{username} ({email}), role={user.role}, lands on {spec['lands_on']}."
            )
        )
        if not password:
            self.stdout.write("Password left unchanged.")
