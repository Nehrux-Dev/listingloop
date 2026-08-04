"""Object-level permissions for designs.

Same two-layer shape as the rest of the project: ``Design.objects.for_user``
decides visibility (out of scope is a 404 that does not confirm existence),
these classes decide mutation on something already visible (403).

Not to be confused with *element* permissions, which are a different thing
entirely — those govern what may be changed inside a design the caller already
owns, and live in ``overrides.py``.
"""

from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.permissions import administers


def _active_user(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.is_active:
        return None
    return user


class DesignPermission(BasePermission):
    message = "You do not have permission to modify this design."

    def has_permission(self, request, view) -> bool:
        return _active_user(request) is not None

    def has_object_permission(self, request, view, obj) -> bool:
        user = _active_user(request)
        if user is None:
            return False

        # Rendering is a write in every sense that matters: it consumes a
        # browser page and, for export, writes a file. Read-only access to a
        # design does not include the right to spend those.
        if request.method in SAFE_METHODS and view.action not in ("preview", "export"):
            return True

        if user.is_nehrux_admin:
            return True
        if user.is_brokerage_admin:
            return administers(user, obj.agent.brokerage_id)
        return obj.agent.user_id == user.id
