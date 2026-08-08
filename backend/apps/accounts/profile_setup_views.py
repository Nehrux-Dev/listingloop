"""Profile setup — the parts of Settings that the CRUD endpoints do not cover.

    GET  /api/profile/completeness/    what is filled in, what is missing, where
    GET  /api/profile/brokerages/      search the directory before creating
    POST /api/profile/brokerage/       join an existing one, or create one

Registration is ``/api/auth/register/`` and asks for a name, an email and a
password. Nothing here is a step in a sequence and nothing here is required:
an agent may use the product indefinitely without ever calling any of it. The
export path is the only thing that insists, and only for the specific fields
the design it is rendering actually shows.

These are thin: they orchestrate models and serializers that already existed
rather than introducing parallel ones. The only genuinely new capability is
letting an agent set up a brokerage at all, which the admin-only create rule
previously made impossible.
"""

from __future__ import annotations

import logging

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.completeness import assess_profile
from apps.accounts.models import AgentProfile, Brokerage
from apps.accounts.profile_serializers import (
    BrokerageDirectorySerializer,
    BrokerageOnboardingSerializer,
    BrokerageSerializer,
)

logger = logging.getLogger(__name__)


def _profile_for(user) -> AgentProfile | None:
    return AgentProfile.objects.filter(user=user).select_related("brokerage").first()


class BrokerageDirectoryView(ListAPIView):
    """Search brokerages by name, so an agent joins rather than duplicates.

    Deliberately searchable by any authenticated user: an agent cannot pick the
    right brokerage from a list they are not allowed to see, and the payload is
    only a name, a logo and a headcount — the things printed on a business card.
    """

    serializer_class = BrokerageDirectorySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        queryset = Brokerage.objects.all().order_by("name")
        search = self.request.query_params.get("search", "").strip()
        if search:
            return queryset.filter(name__icontains=search)[:20]
        # Without a search term, return nothing rather than the whole table:
        # the directory is a lookup tool, not a list of every firm on the
        # platform to be scraped.
        return queryset.none()


class JoinBrokerageSerializer(serializers.Serializer):
    """Either join an existing brokerage, or create one. Not both."""

    brokerage = serializers.PrimaryKeyRelatedField(
        queryset=Brokerage.objects.all(), required=False
    )
    create = BrokerageOnboardingSerializer(required=False)

    def validate(self, attrs: dict) -> dict:
        if bool(attrs.get("brokerage")) == bool(attrs.get("create")):
            raise serializers.ValidationError(
                "Send either 'brokerage' to join an existing one, or 'create' "
                "to add a new one — not both."
            )
        return attrs


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def set_brokerage(request: Request) -> Response:
    """Associate the agent with a brokerage — join an existing one, or add it.

    An agent may create a brokerage *here*, which the general Brokerage
    endpoint reserves for platform admins. The difference is scope: this only
    ever attaches the result to the caller's own profile, and refuses a
    duplicate name outright. Without it the first agent at a firm could never
    record who they work for, because there would be nobody to create it.
    """
    profile = _profile_for(request.user)
    if profile is None:
        return Response(
            {"detail": "Complete your agent profile first."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    serializer = JoinBrokerageSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    with transaction.atomic():
        brokerage = serializer.validated_data.get("brokerage")

        if brokerage is None:
            create_serializer = BrokerageOnboardingSerializer(
                data=serializer.validated_data["create"], context={"request": request}
            )
            create_serializer.is_valid(raise_exception=True)
            brokerage = create_serializer.save()
            # Whoever creates a brokerage administers it — otherwise the firm
            # exists with nobody able to maintain its logo or disclaimer.
            brokerage.admins.add(request.user)
            logger.info(
                "User %s created brokerage %s", request.user.pk, brokerage.pk
            )

        profile.brokerage = brokerage
        profile.save(update_fields=["brokerage", "updated_at"])

    return Response(
        BrokerageSerializer(brokerage, context={"request": request}).data,
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def profile_completeness(request: Request) -> Response:
    """What is filled in, what is missing, and where each gap is fixed.

    Feeds the dashboard prompt. Reporting only — an agent who ignores it
    forever keeps a working account; the export path is what insists, and only
    about the fields the design being exported actually shows.
    """
    assessment = assess_profile(_profile_for(request.user))
    return Response(
        {
            "completion_percent": assessment["completion_percent"],
            "is_complete": assessment["is_complete"],
            "ready_for_marketing": assessment["ready_for_marketing"],
            "missing_required": assessment["missing_required"],
            "missing_optional": assessment["missing_optional"],
            "by_step": assessment["by_step"],
        }
    )
