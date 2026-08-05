"""Compliance endpoints.

    GET  /api/compliance/rules/        the active rule set (read-only)
    POST /api/compliance/evaluate/     check something now, without storing
    GET  /api/compliance/evaluations/  stored results, scoped to the caller
"""

from __future__ import annotations

import logging

from django.db.models import QuerySet
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.compliance import subjects
from apps.compliance.engine import evaluate
from apps.compliance.models import ComplianceEvaluation, ComplianceRule, LegalStatus
from apps.compliance.serializers import (
    ComplianceEvaluationSerializer,
    ComplianceRuleSerializer,
    EvaluateRequestSerializer,
)

logger = logging.getLogger(__name__)


class ComplianceRuleViewSet(viewsets.ReadOnlyModelViewSet):
    """The rule set an agent is being held to.

    Read-only on purpose. Rules are owned by whoever is accountable for them
    and edited in the Django admin; exposing writes here would put an agent in
    charge of the rules they are checked against.
    """

    serializer_class = ComplianceRuleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[ComplianceRule]:
        queryset = ComplianceRule.objects.all()
        if self.request.query_params.get("include_inactive") != "true":
            queryset = queryset.active()

        applies_to = self.request.query_params.get("applies_to")
        if applies_to:
            queryset = queryset.for_subject(applies_to)
        return queryset.order_by("order", "rule_id")

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request: Request) -> Response:
        """Counts, including how much of the set is still unapproved.

        Surfaced in the API rather than buried in the admin so the frontend can
        say plainly that these checks are provisional.
        """
        active = ComplianceRule.objects.active()
        return Response(
            {
                "total": ComplianceRule.objects.count(),
                "active": active.count(),
                "pending_legal_review": active.filter(
                    legal_status=LegalStatus.PENDING_REVIEW
                ).count(),
                "approved": active.filter(legal_status=LegalStatus.APPROVED).count(),
                "blocking": active.filter(severity="error").count(),
            }
        )


class ComplianceEvaluationViewSet(viewsets.ReadOnlyModelViewSet):
    """Stored evaluation results — the audit trail."""

    serializer_class = ComplianceEvaluationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[ComplianceEvaluation]:
        from apps.ai_content.models import GeneratedContent
        from apps.templates.models import Design

        user = self.request.user
        # Scoped through whatever each evaluation points at, so an agent sees
        # results for their own work and nobody else's.
        queryset = ComplianceEvaluation.objects.filter(
            design__in=Design.objects.for_user(user)
        ) | ComplianceEvaluation.objects.filter(
            generated_content__in=GeneratedContent.objects.for_user(user)
        ) | ComplianceEvaluation.objects.filter(
            content_variant__generation__in=GeneratedContent.objects.for_user(user)
        )
        queryset = queryset.distinct()

        design_id = self.request.query_params.get("design")
        if design_id and design_id.isdigit():
            queryset = queryset.filter(design_id=int(design_id))

        generation_id = self.request.query_params.get("generated_content")
        if generation_id and generation_id.isdigit():
            queryset = queryset.filter(generated_content_id=int(generation_id))

        return queryset


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def evaluate_now(request: Request) -> Response:
    """``POST /api/compliance/evaluate/`` — check something without storing it.

    Used by the review UI to show flags before an agent commits to anything.
    Nothing is persisted: the stored audit trail is written at the moments that
    matter (after generation, at export), not every time a panel refreshes.
    """
    serializer = EvaluateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    target = data["_target"]

    subject = _build_subject(request, target, data)
    if subject is None:
        return Response(
            {"detail": "No such object, or it is not available to you."},
            status=status.HTTP_404_NOT_FOUND,
        )

    report = evaluate(subject)
    return Response(report.as_dict())


def _build_subject(request, target: str, data: dict):
    """Resolve the request to a subject, scoped to the caller.

    Scoping happens here rather than after evaluation: a compliance report on
    someone else's listing would leak its contents through the evidence
    strings.
    """
    from apps.ai_content.models import ContentVariant, GeneratedContent
    from apps.listings.models import Listing
    from apps.templates.models import Design

    user = request.user

    if target == "text":
        return subjects.from_text(data["text"], label="ad-hoc text")

    if target == "design":
        design = Design.objects.for_user(user).filter(pk=data["design"]).first()
        return subjects.from_design(design) if design else None

    if target == "generated_content":
        generation = (
            GeneratedContent.objects.for_user(user)
            .filter(pk=data["generated_content"])
            .first()
        )
        return subjects.from_generated_content(generation) if generation else None

    if target == "content_variant":
        variant = (
            ContentVariant.objects.filter(
                pk=data["content_variant"],
                generation__in=GeneratedContent.objects.for_user(user),
            )
            .select_related("generation", "generation__listing")
            .first()
        )
        return subjects.from_content_variant(variant) if variant else None

    if target == "listing":
        listing = Listing.objects.for_user(user).filter(pk=data["listing"]).first()
        return subjects.from_listing(listing) if listing else None

    return None
