"""Create one local user per role, for development only."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Role

User = get_user_model()

DEFAULT_PASSWORD = "Passw0rd-Local-2026"

SEED_USERS = [
    ("agent@nehrux.test", Role.AGENT, "Test Agent"),
    ("broker@nehrux.test", Role.BROKERAGE_ADMIN, "Test Brokerage Admin"),
    ("admin@nehrux.test", Role.NEHRUX_ADMIN, "Test Nehrux Admin"),
]


class Command(BaseCommand):
    help = "Create a development user for each role (DEBUG only)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--password",
            default=DEFAULT_PASSWORD,
            help=f"Password for every seeded account (default: {DEFAULT_PASSWORD})",
        )

    def handle(self, *args, **options) -> None:
        # These are well-known credentials. Creating them on a real deployment
        # would be handing out accounts, so refuse outright.
        if not settings.DEBUG:
            raise CommandError("seed_dev_users refuses to run with DEBUG=False.")

        password = options["password"]

        for email, role, full_name in SEED_USERS:
            user, created = User.objects.get_or_create(
                email=email, defaults={"role": role, "full_name": full_name}
            )
            user.role = role
            user.full_name = full_name
            user.is_active = True
            user.set_password(password)
            user.save()

            verb = "created" if created else "updated"
            self.stdout.write(self.style.SUCCESS(f"{verb}: {email} ({role})"))

        self.stdout.write(f"\nPassword for all seeded accounts: {password}")
