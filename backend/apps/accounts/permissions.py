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

from rest_framework.permissions import SAFE_METHODS, BasePermission

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


# ---------------------------------------------------------------------------
# Object-level access policies for profile resources
#
# Two layers, and both are needed:
#
#   * ``get_queryset()`` on each viewset controls VISIBILITY. Anything filtered
#     out there is a 404, which is the right answer for a record the caller
#     should not know exists.
#   * The permission classes below control MUTATION on a record that is already
#     visible, producing a 403.
#
# Relying on the queryset alone would let a Brokerage Admin edit an agent they
# can merely see; relying on the permission alone would leak the existence of
# other brokerages' records through list endpoints.
# ---------------------------------------------------------------------------


def administers(user, brokerage) -> bool:
    """True when ``user`` is an administrator of ``brokerage``."""
    if brokerage is None:
        return False
    brokerage_id = getattr(brokerage, "pk", brokerage)
    return user.administered_brokerages.filter(pk=brokerage_id).exists()


class BrokeragePermission(BasePermission):
    """Who may change a brokerage.

    * Nehrux Admin   — everything, including creating and deleting.
    * Brokerage Admin— may edit the brokerages they administer. Creating a new
      brokerage is deliberately not theirs: it is a platform-level action.
    * Agent          — read-only, and only their own brokerage (enforced by the
      viewset queryset).
    """

    message = "You do not have permission to modify this brokerage."

    def has_permission(self, request, view) -> bool:
        user = _active_user(request)
        if user is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        if view.action == "create":
            return user.is_nehrux_admin
        # Everything else is decided per object, by ``administers()`` below.
        #
        # Checking the *role* here too would be wrong, and subtly so: an agent
        # who sets up their own firm during onboarding administers it without
        # holding a platform-wide Brokerage Admin role. Gating on the role
        # locked them out of the logo and disclaimer their own exports require,
        # with no way to supply either. Administering a brokerage is a fact
        # about that brokerage, not a rank.
        return True

    def has_object_permission(self, request, view, obj) -> bool:
        user = _active_user(request)
        if user is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        if user.is_nehrux_admin:
            return True
        # Deleting a brokerage would orphan its agents — platform-level only.
        if request.method == "DELETE":
            return False
        return administers(user, obj)


class AgentProfilePermission(BasePermission):
    """Who may change an agent profile.

    * Nehrux Admin    — everything.
    * Brokerage Admin — agents in the brokerages they administer, including
      creating and removing them.
    * Agent           — their own profile only, and they cannot delete it or
      move themselves to a different brokerage (see the serializer).
    """

    message = "You do not have permission to modify this agent profile."

    def has_permission(self, request, view) -> bool:
        user = _active_user(request)
        if user is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        if view.action == "create":
            # An agent's own profile is created automatically on registration,
            # so agents never need to create one — and allowing it would let
            # them attach a profile to another user's account.
            return user.has_role_at_least(Role.BROKERAGE_ADMIN)
        return True

    def has_object_permission(self, request, view, obj) -> bool:
        user = _active_user(request)
        if user is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        if user.is_nehrux_admin:
            return True
        if user.is_brokerage_admin:
            return administers(user, obj.brokerage_id)
        # Agents: own profile, and never deletion.
        if request.method == "DELETE":
            return False
        return obj.user_id == user.id


class BrandKitPermission(BasePermission):
    """Who may change a brand kit.

    A kit belongs to exactly one owner, so permission follows the owner:

    * agent-owned     — the agent themselves, an admin of that agent's
      brokerage, or a Nehrux Admin.
    * brokerage-owned — an admin of that brokerage, or a Nehrux Admin. Agents
      can read their brokerage's kit but not change it.
    """

    message = "You do not have permission to modify this brand kit."

    def has_permission(self, request, view) -> bool:
        return _active_user(request) is not None

    def has_object_permission(self, request, view, obj) -> bool:
        user = _active_user(request)
        if user is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        if user.is_nehrux_admin:
            return True

        if obj.brokerage_id is not None:
            return administers(user, obj.brokerage_id)

        # Agent-owned kit.
        agent = obj.agent
        if agent is None:
            return False
        if user.is_brokerage_admin:
            return administers(user, agent.brokerage_id)
        return agent.user_id == user.id
