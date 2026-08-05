"""Object-level permissions for listings and their photos.

Same two-layer approach as the accounts app: ``Listing.objects.for_user``
controls visibility (out of scope is a 404 that does not confirm the record
exists), and these classes control mutation on a record that is already
visible (403).
"""

from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.permissions import administers


def _active_user(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.is_active:
        return None
    return user


def can_manage_listing(user, listing) -> bool:
    """True when ``user`` may modify ``listing``."""
    if user.is_nehrux_admin:
        return True
    if user.is_brokerage_admin:
        return administers(user, listing.agent.brokerage_id)
    # Agents: their own listings only.
    return listing.agent.user_id == user.id


class ListingPermission(BasePermission):
    """Agents manage their own listings; Brokerage Admins their brokerage's."""

    message = "You do not have permission to modify this listing."

    def has_permission(self, request, view) -> bool:
        return _active_user(request) is not None

    def has_object_permission(self, request, view, obj) -> bool:
        user = _active_user(request)
        if user is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        return can_manage_listing(user, obj)


class EnquiryPermission(BasePermission):
    """An enquiry belongs to the agent it was addressed to.

    Follows ``enquiry.agent`` rather than ``enquiry.listing.agent``: if a
    listing is reassigned, the messages a member of the public sent to the
    original agent stay with that agent.
    """

    message = "You do not have permission to act on this enquiry."

    def has_permission(self, request, view) -> bool:
        return _active_user(request) is not None

    def has_object_permission(self, request, view, obj) -> bool:
        user = _active_user(request)
        if user is None:
            return False
        if user.is_nehrux_admin:
            return True
        if user.is_brokerage_admin:
            return administers(user, obj.agent.brokerage_id)
        return obj.agent.user_id == user.id


class ListingPhotoPermission(BasePermission):
    """Photo access follows the listing it belongs to."""

    message = "You do not have permission to modify this photo."

    def has_permission(self, request, view) -> bool:
        return _active_user(request) is not None

    def has_object_permission(self, request, view, obj) -> bool:
        user = _active_user(request)
        if user is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        return can_manage_listing(user, obj.listing)
