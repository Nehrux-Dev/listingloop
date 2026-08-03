"""Role-based DRF permission classes.

Two flavours:

  * Exact-role   — ``IsAgent`` allows *only* Agents.
  * Or-above     — ``IsBrokerageAdminOrAbove`` allows Brokerage Admins and
                   Nehrux Admins, following ``ROLE_LEVELS``.

Prefer the "or above" classes for anything hierarchical, and the exact classes
only when a higher role genuinely should *not* have access.

Every class here fails closed: an unauthenticated request, an inactive user or
an unrecognised role value all return False.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from apps.accounts.models import ROLE_LEVELS, Role


def _active_user(request):
    """Return the authenticated, active user on the request, else None."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.is_active:
        return None
    return user


class HasAnyRole(BasePermission):
    """Base class: allows the request when the user holds one of ``roles``.

    Subclass and set ``roles``, or build one inline with :func:`role_required`.
    """

    roles: tuple[str, ...] = ()
    message = "Your role does not grant access to this resource."

    def has_permission(self, request, view) -> bool:
        user = _active_user(request)
        if user is None:
            return False
        return user.role in self.roles


class HasRoleAtLeast(BasePermission):
    """Allows the request when the user's role is ``minimum_role`` or higher."""

    minimum_role: str = Role.NEHRUX_ADMIN
    message = "Your role does not grant access to this resource."

    def has_permission(self, request, view) -> bool:
        user = _active_user(request)
        if user is None:
            return False
        return user.role_level >= ROLE_LEVELS.get(self.minimum_role, 0)


def role_required(*roles: str) -> type[HasAnyRole]:
    """Build an exact-role permission class on the fly.

        permission_classes = [role_required(Role.AGENT, Role.NEHRUX_ADMIN)]
    """
    names = ", ".join(str(role) for role in roles)
    return type(
        "RoleRequired",
        (HasAnyRole,),
        {
            "roles": roles,
            "message": f"This resource requires one of these roles: {names}.",
        },
    )


# -- Exact-role classes -----------------------------------------------------


class IsAgent(HasAnyRole):
    """Agents only. Brokerage and Nehrux Admins are *not* allowed."""

    roles = (Role.AGENT,)
    message = "This resource is restricted to Agents."


class IsBrokerageAdmin(HasAnyRole):
    """Brokerage Admins only."""

    roles = (Role.BROKERAGE_ADMIN,)
    message = "This resource is restricted to Brokerage Admins."


class IsNehruxAdmin(HasAnyRole):
    """Nehrux (platform) Admins only — the highest role.

    Exact and "or above" are equivalent at the top of the hierarchy.
    """

    roles = (Role.NEHRUX_ADMIN,)
    message = "This resource is restricted to Nehrux Admins."


# -- Hierarchical classes ---------------------------------------------------


class IsAgentOrAbove(HasRoleAtLeast):
    """Any recognised role. Effectively "authenticated with a valid role"."""

    minimum_role = Role.AGENT


class IsBrokerageAdminOrAbove(HasRoleAtLeast):
    """Brokerage Admins and Nehrux Admins."""

    minimum_role = Role.BROKERAGE_ADMIN
    message = "This resource requires Brokerage Admin access or higher."
