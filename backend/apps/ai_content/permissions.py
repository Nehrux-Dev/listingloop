"""Object-level permissions for generated content.

Follows the listing it belongs to: an agent's own listings, a brokerage admin's
brokerage, everything for a Nehrux Admin. Visibility comes from
``GeneratedContent.objects.for_user``; this governs review actions.
"""

from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.permissions import administers


class GeneratedContentPermission(BasePermission):
    message = "You do not have permission to act on this generated content."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and user.is_active)

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if request.method in SAFE_METHODS:
            return True
        if user.is_nehrux_admin:
            return True
        if user.is_brokerage_admin:
            return administers(user, obj.listing.agent.brokerage_id)
        return obj.listing.agent.user_id == user.id
