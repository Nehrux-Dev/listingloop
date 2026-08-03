"""CRUD endpoints for brokerages, agent profiles and brand kits.

    /api/brokerages/       list, create, retrieve, update, delete
    /api/agents/           ditto, plus /api/agents/me/
    /api/brand-kits/       ditto, plus /api/brand-kits/mine/

VISIBILITY vs MUTATION
----------------------
``get_queryset`` decides what a caller can *see*; the permission classes in
``apps.accounts.permissions`` decide what they can *change*. Filtering in the
queryset means a record outside the caller's scope returns 404 rather than
403 — it does not confirm that the record exists.

Every list endpoint is scoped. There is no "all agents" view for a Brokerage
Admin, by construction rather than by remembering to add a filter.
"""

from __future__ import annotations

from django.db.models import Q, QuerySet
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.models import AgentProfile, BrandKit, Brokerage
from apps.accounts.permissions import (
    AgentProfilePermission,
    BrandKitPermission,
    BrokeragePermission,
)
from apps.accounts.profile_serializers import (
    AgentProfileSerializer,
    BrandKitSerializer,
    BrokerageSerializer,
)


class BrokerageViewSet(viewsets.ModelViewSet):
    """Brokerages.

    Visible to: Nehrux Admins (all), Brokerage Admins (those they administer),
    Agents (the one they belong to).
    """

    serializer_class = BrokerageSerializer
    permission_classes = [IsAuthenticated, BrokeragePermission]
    # MultiPartParser is what makes the logo upload work; JSON still handles
    # every other field.
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_queryset(self) -> QuerySet[Brokerage]:
        user = self.request.user
        queryset = Brokerage.objects.all()

        if user.is_nehrux_admin:
            return queryset
        if user.is_brokerage_admin:
            return queryset.filter(admins=user).distinct()

        # Agents see only their own brokerage.
        return queryset.filter(agents__user=user).distinct()


class AgentProfileViewSet(viewsets.ModelViewSet):
    """Agent profiles.

    Visible to: Nehrux Admins (all), Brokerage Admins (agents of the
    brokerages they administer), Agents (colleagues in their own brokerage,
    plus themselves).
    """

    serializer_class = AgentProfileSerializer
    permission_classes = [IsAuthenticated, AgentProfilePermission]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_queryset(self) -> QuerySet[AgentProfile]:
        user = self.request.user
        queryset = AgentProfile.objects.select_related("user", "brokerage")

        if user.is_nehrux_admin:
            return queryset
        if user.is_brokerage_admin:
            return queryset.filter(brokerage__admins=user).distinct()

        # An agent sees themselves and anyone in the same brokerage. The
        # `user=user` clause matters for an agent with no brokerage yet:
        # without it they could not even read their own profile.
        return queryset.filter(
            Q(user=user) | Q(brokerage__agents__user=user)
        ).distinct()

    @action(
        detail=False,
        methods=["get", "patch", "put"],
        url_path="me",
        permission_classes=[IsAuthenticated],
    )
    def me(self, request: Request) -> Response:
        """``/api/agents/me/`` — the caller's own profile.

        Saves the frontend from having to know its own profile id, and makes
        "edit my profile" impossible to point at anyone else: the object is
        looked up from ``request.user``, never from a client-supplied id.
        """
        profile = AgentProfile.objects.filter(user=request.user).first()
        if profile is None:
            raise NotFound(
                "You do not have an agent profile. Ask an administrator to "
                "create one."
            )

        if request.method == "GET":
            serializer = self.get_serializer(profile)
            return Response(serializer.data)

        serializer = self.get_serializer(
            profile, data=request.data, partial=request.method == "PATCH"
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class BrandKitViewSet(viewsets.ModelViewSet):
    """Brand kits, owned by exactly one agent or one brokerage."""

    serializer_class = BrandKitSerializer
    permission_classes = [IsAuthenticated, BrandKitPermission]

    def get_queryset(self) -> QuerySet[BrandKit]:
        user = self.request.user
        queryset = BrandKit.objects.select_related(
            "agent", "agent__user", "brokerage"
        )

        if user.is_nehrux_admin:
            return queryset
        if user.is_brokerage_admin:
            return queryset.filter(
                Q(brokerage__admins=user) | Q(agent__brokerage__admins=user)
            ).distinct()

        # An agent sees their own kit and their brokerage's kit (they need the
        # latter to render brokerage-branded material), but may only edit their
        # own — enforced by BrandKitPermission.
        return queryset.filter(
            Q(agent__user=user) | Q(brokerage__agents__user=user)
        ).distinct()

    @action(detail=False, methods=["get"], url_path="mine")
    def mine(self, request: Request) -> Response:
        """``/api/brand-kits/mine/`` — the caller's own kit, created on demand.

        Idempotent: the first call creates an empty kit with the model
        defaults so the edit form always has something to bind to.
        """
        profile = AgentProfile.objects.filter(user=request.user).first()
        if profile is None:
            raise NotFound("You do not have an agent profile.")

        brand_kit, created = BrandKit.objects.get_or_create(agent=profile)
        serializer = self.get_serializer(brand_kit)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
