"""Public, unauthenticated listing pages and the enquiry form.

    GET  /api/public/listings/<slug>/           one verified listing
    POST /api/public/listings/<slug>/enquire/   send an enquiry

These are the only endpoints in the project that serve an anonymous request, so
they are the only ones that opt out of the project-wide ``IsAuthenticated``
default — explicitly, one at a time, rather than by loosening the default.

Everything goes through ``Listing.objects.publicly_visible()``. Writing the
filter a second time here is exactly how an unverified listing ends up online.
"""

from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle

from apps.listings.models import Enquiry, EnquiryStatus, Listing
from apps.listings.public_serializers import (
    PublicEnquirySerializer,
    PublicListingSerializer,
)
from apps.listings.spam import assess, client_ip

logger = logging.getLogger(__name__)


class PublicPageThrottle(AnonRateThrottle):
    """Read throttle, generous — this is a page anyone may look at."""

    scope = "public_page"


class EnquiryThrottle(SimpleRateThrottle):
    """Per-IP limit on enquiry submissions.

    NOT ``ScopedRateThrottle``: that reads its scope from ``view.throttle_scope``
    and ignores a class attribute, so on a function-based view it finds no
    scope, returns True, and silently applies no limit at all. A throttle that
    quietly does nothing is worse than none — it reads as covered.

    Keyed on IP for everyone rather than only anonymous users: a logged-in
    agent posting to a public form is exactly as capable of flooding it.
    """

    scope = "enquiry"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([PublicPageThrottle])
def public_listing(request: Request, slug: str) -> Response:
    """One listing, if it is verified and on the market.

    A listing that is not publicly visible returns 404, not 403: an anonymous
    visitor should not be able to tell the difference between "no such listing"
    and "a listing exists but has not been verified yet", which would leak both
    the existence of the record and its internal state.
    """
    listing = get_object_or_404(
        Listing.objects.publicly_visible()
        .select_related("agent", "agent__brokerage")
        .prefetch_related("photos"),
        public_slug=slug,
    )
    serializer = PublicListingSerializer(listing, context={"request": request})
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([EnquiryThrottle])
def submit_enquiry(request: Request, slug: str) -> Response:
    """Send an enquiry about a listing.

    Rate limited, honeypotted and timing-checked (see ``apps.listings.spam``).
    A submission that looks like spam is stored and flagged rather than
    discarded — a false positive that silently bins a real buyer's enquiry is
    the expensive failure, not a spam message reaching a folder.
    """
    listing = get_object_or_404(
        Listing.objects.publicly_visible().select_related("agent"), public_slug=slug
    )

    serializer = PublicEnquirySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    ip_address = client_ip(request)
    assessment = assess(
        name=data["name"],
        email=data.get("email", ""),
        phone=data.get("phone", ""),
        message=data["message"],
        honeypot=data.get("website"),
        form_token=data.get("form_token"),
        listing=listing,
        ip_address=ip_address,
    )

    if assessment.reject_outright:
        # The honeypot. No person can trip this, so there is nothing to store
        # and no genuine sender to apologise to. The response is deliberately
        # indistinguishable from success: telling a bot which check caught it
        # is free tuning advice.
        logger.info(
            "Rejected enquiry on %s from %s: %s",
            slug, ip_address, "; ".join(assessment.reasons),
        )
        return Response(
            {"detail": "Thank you — your enquiry has been sent."},
            status=status.HTTP_201_CREATED,
        )

    enquiry = Enquiry.objects.create(
        listing=listing,
        # Captured now rather than followed through the listing: if the listing
        # is reassigned later, the enquiry stays with whoever was contacted.
        agent=listing.agent,
        name=data["name"],
        email=data.get("email", ""),
        phone=data.get("phone", ""),
        message=data["message"],
        status=EnquiryStatus.SPAM if assessment.is_spam else EnquiryStatus.NEW,
        spam_reasons=assessment.reasons,
        ip_address=ip_address,
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:400],
    )

    if assessment.is_spam:
        logger.info(
            "Enquiry %s flagged as spam: %s", enquiry.pk, "; ".join(assessment.reasons)
        )

    # The sender is told the same thing either way. A flagged enquiry that
    # announces itself as flagged just teaches the sender what to change.
    return Response(
        {"detail": "Thank you — your enquiry has been sent."},
        status=status.HTTP_201_CREATED,
    )
