"""Onboarding endpoints — steps 2 to 4 of agent registration.

    GET  /api/onboarding/status/             what is done, what is missing
    GET  /api/onboarding/brokerages/         search the directory before creating
    POST /api/onboarding/brokerage/          join an existing one, or create one
    POST /api/onboarding/complete/           finish and report readiness

Step 1 (the account itself) is ``/api/auth/register/``, which already existed —
onboarding does not create a second way to make an account.

These are thin: they orchestrate the models and serializers built in earlier
steps rather than introducing parallel ones. The only genuinely new capability
is letting an agent set up a brokerage at all, which the admin-only create rule
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

from apps.accounts.models import AgentProfile, BrandKit, Brokerage, Role
from apps.accounts.onboarding import assess_profile
from apps.accounts.profile_serializers import (
    AgentProfileSerializer,
    BrandKitSerializer,
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


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def onboarding_status(request: Request) -> Response:
    """Where the agent is up to, and what is still missing.

    Drives both the onboarding wizard and the dashboard's completion badge —
    one source of truth, so the two cannot disagree about whether the profile
    is finished.
    """
    profile = _profile_for(request.user)
    assessment = assess_profile(profile)

    return Response(
        {
            "role": request.user.role,
            "has_profile": profile is not None,
            "profile": AgentProfileSerializer(
                profile, context={"request": request}
            ).data
            if profile
            else None,
            "brokerage": BrokerageSerializer(
                profile.brokerage, context={"request": request}
            ).data
            if profile and profile.brokerage
            else None,
            "brand_kit": BrandKitSerializer(
                getattr(profile, "brand_kit", None), context={"request": request}
            ).data
            if profile and getattr(profile, "brand_kit", None)
            else None,
            **assessment,
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def set_brokerage(request: Request) -> Response:
    """Step 3 — associate the agent with a brokerage.

    An agent may create a brokerage *here*, which the general Brokerage
    endpoint reserves for platform admins. The difference is scope: this only
    ever attaches the result to the caller's own profile, and refuses a
    duplicate name outright. Without it a new agent could not finish onboarding
    at all, because there would be nobody to create their firm.
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
                "User %s created brokerage %s during onboarding",
                request.user.pk, brokerage.pk,
            )

        profile.brokerage = brokerage
        profile.save(update_fields=["brokerage", "updated_at"])

    return Response(
        BrokerageSerializer(brokerage, context={"request": request}).data,
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def complete_onboarding(request: Request) -> Response:
    """Step 5 — finish.

    Does not *enforce* completeness: an agent is allowed to finish onboarding
    with gaps and fill them in later from the settings pages. What it does is
    report exactly what is still missing, so the dashboard can say so and the
    export gate is never the first time they hear about it.
    """
    profile = _profile_for(request.user)
    if profile is None:
        return Response(
            {"detail": "No agent profile found for this account."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # A brand kit is created on demand with the model defaults, so an agent who
    # skipped step 4 still has a branded (if unremarkable) starting point
    # rather than a null the renderer has to guess around.
    BrandKit.objects.get_or_create(agent=profile)

    assessment = assess_profile(profile)
    logger.info(
        "User %s completed onboarding at %s%% (ready=%s)",
        request.user.pk, assessment["completion_percent"], assessment["ready_for_marketing"],
    )
    return Response(assessment)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def profile_completion(request: Request) -> Response:
    """Just the numbers, for the dashboard badge."""
    assessment = assess_profile(_profile_for(request.user))
    return Response(
        {
            "completion_percent": assessment["completion_percent"],
            "is_complete": assessment["is_complete"],
            "ready_for_marketing": assessment["ready_for_marketing"],
            "missing_required": assessment["missing_required"],
            "by_step": assessment["by_step"],
        }
    )
