"""Custom user model and role definitions.

The project uses a custom user model from day one (swapping it later is
painful) with e-mail as the login identifier instead of a username.

Profile models (Brokerage, AgentProfile, BrandKit) live in ``profiles.py`` and
are re-exported at the bottom of this module so ``from apps.accounts.models
import ...`` works for every model in the app.
"""

from __future__ import annotations

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Role(models.TextChoices):
    """The three roles the platform recognises.

    Stored as short stable strings — never as integers, so a reordering can
    never silently re-map existing users to a different role.
    """

    AGENT = "agent", _("Agent")
    BROKERAGE_ADMIN = "brokerage_admin", _("Brokerage Admin")
    NEHRUX_ADMIN = "nehrux_admin", _("Nehrux Admin")


#: Privilege ordering. Higher number == more privilege. Used by the
#: "or above" permission classes so a Nehrux Admin automatically satisfies
#: anything a Brokerage Admin can do, and so on.
ROLE_LEVELS: dict[str, int] = {
    Role.AGENT: 10,
    Role.BROKERAGE_ADMIN: 20,
    Role.NEHRUX_ADMIN: 30,
}

#: Roles a user may pick for themselves at registration. Elevated roles must be
#: granted by an existing admin — otherwise anyone could sign up as a Nehrux
#: Admin.
SELF_ASSIGNABLE_ROLES: tuple[str, ...] = (Role.AGENT,)


class UserManager(BaseUserManager):
    """Manager for the e-mail-based user model."""

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        # set_password hashes with the configured PASSWORD_HASHERS; the raw
        # password is never stored.
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("role", Role.AGENT)
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("role", Role.NEHRUX_ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Platform user.

    ``role`` drives API authorisation (see ``apps.accounts.permissions``).
    ``is_staff``/``is_superuser`` are kept because the Django admin and
    permission framework depend on them, but they are deliberately *not* what
    the REST API authorises against — the API only looks at ``role``.
    """

    email = models.EmailField(_("email address"), unique=True)
    full_name = models.CharField(_("full name"), max_length=255, blank=True)
    role = models.CharField(
        _("role"),
        max_length=32,
        choices=Role.choices,
        default=Role.AGENT,
        db_index=True,
    )

    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_("Unset this instead of deleting an account to revoke access."),
    )
    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Whether the user can log into the Django admin site."),
    )
    date_joined = models.DateTimeField(_("date joined"), default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    # Prompted for by `createsuperuser`, in addition to email + password.
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ("email",)

    def __str__(self) -> str:
        return self.email

    def save(self, *args, **kwargs):
        # Keep e-mails canonical so logins are effectively case-insensitive.
        self.email = self.__class__.objects.normalize_email(self.email).lower()
        return super().save(*args, **kwargs)

    # -- Role helpers -------------------------------------------------------

    @property
    def role_level(self) -> int:
        """Numeric privilege level; unknown roles get 0 (no privilege)."""
        return ROLE_LEVELS.get(self.role, 0)

    def has_role(self, *roles: str) -> bool:
        """True when the user holds one of ``roles`` exactly."""
        return self.role in roles

    def has_role_at_least(self, role: str) -> bool:
        """True when the user's role is ``role`` or more privileged."""
        return self.role_level >= ROLE_LEVELS.get(role, 0)

    @property
    def is_agent(self) -> bool:
        return self.role == Role.AGENT

    @property
    def is_brokerage_admin(self) -> bool:
        return self.role == Role.BROKERAGE_ADMIN

    @property
    def is_nehrux_admin(self) -> bool:
        return self.role == Role.NEHRUX_ADMIN


# Imported here (rather than the other way round) so Django's app registry
# picks these models up when it loads apps.accounts.models. Placed at the end
# to avoid a circular import at module load.
from apps.accounts.profiles import (  # noqa: E402
    AgentProfile,
    BrandKit,
    Brokerage,
    DesignStyle,
)

__all__ = [
    "AgentProfile",
    "BrandKit",
    "Brokerage",
    "DesignStyle",
    "ROLE_LEVELS",
    "Role",
    "SELF_ASSIGNABLE_ROLES",
    "User",
    "UserManager",
]
