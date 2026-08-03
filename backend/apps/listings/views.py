"""Listing and photo endpoints.

    /api/listings/                 CRUD, scoped by role
    /api/listings/{id}/verify/     explicit human confirmation
    /api/listings/{id}/unverify/   withdraw confirmation
    /api/listings/import-url/      one-off fetch of a public listing page
    /api/listing-photos/           CRUD for photos
"""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.models import AgentProfile
from apps.listings.fetching import FetchError, UnsafeUrlError
from apps.listings.importing import import_listing_from_url
from apps.listings.models import Listing, ListingPhoto, VerificationStatus
from apps.listings.permissions import ListingPermission, ListingPhotoPermission
from apps.listings.serializers import (
    ListingImportResultSerializer,
    ListingImportSerializer,
    ListingPhotoSerializer,
    ListingSerializer,
    ListingStatusSummarySerializer,
    ListingVerifySerializer,
)

logger = logging.getLogger(__name__)


class ListingViewSet(viewsets.ModelViewSet):
    """Listings.

    Scoping lives in ``Listing.objects.for_user`` rather than here, so the
    same rule applies to every caller of the model — viewsets, management
    commands, and the services later features will use.
    """

    serializer_class = ListingSerializer
    permission_classes = [IsAuthenticated, ListingPermission]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_queryset(self) -> QuerySet[Listing]:
        queryset = (
            Listing.objects.for_user(self.request.user)
            .select_related("agent", "agent__user", "agent__brokerage")
            .prefetch_related("photos")
        )

        # Simple filters, useful to the UI and to later features that only
        # ever want verified data.
        params = self.request.query_params
        verification = params.get("verification_status")
        if verification in VerificationStatus.values:
            queryset = queryset.filter(verification_status=verification)
        listing_status = params.get("status")
        if listing_status:
            queryset = queryset.filter(status=listing_status)

        return queryset

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request: Request) -> Response:
        """Counts for the caller's own scope."""
        data = ListingStatusSummarySerializer.from_queryset(
            Listing.objects.for_user(request.user)
        )
        return Response(ListingStatusSummarySerializer(data).data)

    @action(detail=True, methods=["post"], url_path="verify")
    def verify(self, request: Request, pk=None) -> Response:
        """``POST /api/listings/{id}/verify/`` — the review step.

        This is the only way a listing becomes verified. It is a separate,
        explicit action rather than a writable field precisely so it cannot
        happen as a side effect of saving the form: the agent has to look at
        the data and say yes.

        Fails with 400 when required fields are still blank — "verified" must
        mean someone confirmed real values.
        """
        listing = self.get_object()

        serializer = ListingVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            listing.mark_verified(request.user)
        except DjangoValidationError as exc:
            # Surfaces as {"address": ["This field is required before..."]}.
            raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)

        return Response(self.get_serializer(listing).data)

    @action(detail=True, methods=["post"], url_path="unverify")
    def unverify(self, request: Request, pk=None) -> Response:
        """Withdraw verification, e.g. when something turns out to be wrong."""
        listing = self.get_object()
        listing.mark_unverified()
        return Response(self.get_serializer(listing).data)

    @action(
        detail=False,
        methods=["post"],
        url_path="import-url",
        throttle_classes=[ScopedRateThrottle],
    )
    def import_url(self, request: Request) -> Response:
        """``POST /api/listings/import-url/`` — one-off import from a URL.

        Makes the server fetch a user-supplied URL, so it is throttled and the
        fetch itself is heavily restricted (see ``apps.listings.fetching``).

        Returns 201 with a DRAFT, UNVERIFIED listing plus a list of what was
        extracted and what was not. Fields that could not be read are left
        blank — never filled with a guess.
        """
        input_serializer = ListingImportSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        profile = AgentProfile.objects.filter(user=request.user).first()
        if profile is None:
            raise ValidationError(
                {"detail": "You need an agent profile before importing listings."}
            )

        try:
            outcome = import_listing_from_url(input_serializer.validated_data["url"], profile)
        except UnsafeUrlError as exc:
            # A refused destination, not a transient failure.
            return Response(
                {"detail": str(exc), "warnings": []},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except FetchError as exc:
            # Graceful failure: the page could not be read, so no half-built
            # listing is left behind.
            return Response(
                {
                    "detail": f"That page could not be imported: {exc}",
                    "warnings": [
                        "Nothing was created. You can still add the listing manually."
                    ],
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        payload = ListingImportResultSerializer(
            {
                "listing": outcome.listing,
                "extracted_fields": outcome.extracted_fields,
                "warnings": outcome.warnings,
                "photo_count": outcome.photo_count,
            },
            context=self.get_serializer_context(),
        ).data
        return Response(payload, status=status.HTTP_201_CREATED)

    import_url.throttle_scope = "listing_import"


class ListingPhotoViewSet(viewsets.ModelViewSet):
    """Photos, scoped through the listing they belong to."""

    serializer_class = ListingPhotoSerializer
    permission_classes = [IsAuthenticated, ListingPhotoPermission]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_queryset(self) -> QuerySet[ListingPhoto]:
        listings = Listing.objects.for_user(self.request.user)
        queryset = ListingPhoto.objects.filter(listing__in=listings).select_related(
            "listing", "listing__agent"
        )

        listing_id = self.request.query_params.get("listing")
        if listing_id and listing_id.isdigit():
            queryset = queryset.filter(listing_id=int(listing_id))
        return queryset

    def perform_create(self, serializer):
        """Block uploads to a listing the caller cannot manage.

        ``validate_listing`` already checks visibility; this checks *write*
        access, so a colleague's visible listing still cannot be edited.
        """
        listing = serializer.validated_data["listing"]
        self.check_object_permissions(self.request, _PhotoTarget(listing))
        serializer.save()


class _PhotoTarget:
    """Adapter so ``ListingPhotoPermission`` can vet a not-yet-created photo."""

    def __init__(self, listing: Listing) -> None:
        self.listing = listing
