"""Object-level permissions for generated content.

Follows the listing it belongs to: an agent's own listings, a brokerage admin's
brokerage, everything for a Nehrux Admin. Visibility comes from
``GeneratedContent.objects.for_user``; this governs review actions.
"""

from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.permissions import administers


def _may_act_on_listing(user, listing) -> bool:
    if user.is_nehrux_admin:
        return True
    if user.is_brokerage_admin:
        return administers(user, listing.agent.brokerage_id)
    return listing.agent.user_id == user.id


class GeneratedContentPermission(BasePermission):
    message = "You do not have permission to act on this generated content."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and user.is_active)

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return _may_act_on_listing(request.user, obj.listing)


class ContentVariantPermission(BasePermission):
    """A variant follows the listing behind its generation."""

    message = "You do not have permission to act on this content variant."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and user.is_active)

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return _may_act_on_listing(request.user, obj.generation.listing)
