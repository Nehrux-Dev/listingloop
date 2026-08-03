"""Listing services shared with the rest of the project.

The important export here is :func:`get_listing_for_content`. Later steps
(templates, AI content) must not reach for ``Listing.objects.get(...)``
themselves — they should come through this function, so the "verified only"
rule is written down once and cannot be forgotten in a new feature.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from apps.listings.models import Listing


class ListingNotVerifiedError(ValidationError):
    """A listing exists and is visible, but has not been confirmed by a human."""

    default_detail = _(
        "This listing has not been verified yet. Review and confirm its details "
        "before using it."
    )


def get_listing_for_content(user, listing_id: int) -> Listing:
    """Return a listing that ``user`` may use to generate content.

    Two separate gates, and both matter:

      * ``for_user`` — scoping. A listing the caller cannot see raises
        ``PermissionDenied`` rather than revealing that the id exists.
      * verification — a visible but unverified listing raises
        ``ListingNotVerifiedError``, which is a 400 with an actionable message.
    """
    listing = Listing.objects.for_user(user).filter(pk=listing_id).first()
    if listing is None:
        raise PermissionDenied("No listing with that id is available to you.")

    if not listing.is_usable_for_content:
        raise ListingNotVerifiedError()

    return listing
