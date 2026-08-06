"""Generated-content endpoints.

    POST /api/ai-content/generate/     explicit Generate / Regenerate
    GET  /api/ai-content/              list (scoped, ?listing=)
    GET  /api/ai-content/{id}/         full record
    GET  /api/ai-content/{id}/status/  small payload for polling
    POST /api/ai-content/{id}/review/  agent approves or rejects the draft
    GET  /api/ai-content/usage/        token and cost totals

GENERATION IS NEVER A SIDE EFFECT
---------------------------------
The only code path that starts a generation is the ``generate`` action below.
Nothing in the listing, design or template endpoints creates one, and none of
the read endpoints here does either. Opening a listing a hundred times costs
nothing; the API is only ever called when a person presses a button.
"""

from __future__ import annotations

import logging

from django.db.models import Count, QuerySet, Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.ai_content.languages import SOURCE_LANGUAGE, enabled_languages
from apps.ai_content.models import ContentVariant, GeneratedContent, ReviewStatus
from apps.ai_content.permissions import (
    ContentVariantPermission,
    GeneratedContentPermission,
)
from apps.ai_content.serializers import (
    ContentVariantSerializer,
    GeneratedContentSerializer,
    GeneratedContentStatusSerializer,
    GenerateRequestSerializer,
    ReviewSerializer,
    VariantEditSerializer,
)
from apps.ai_content.services import apply_variant_edit, create_generation
from apps.ai_content.tasks import generate_content

logger = logging.getLogger(__name__)


class GeneratedContentViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only over the collection: records are created by ``generate``."""

    serializer_class = GeneratedContentSerializer
    permission_classes = [IsAuthenticated, GeneratedContentPermission]

    def get_queryset(self) -> QuerySet[GeneratedContent]:
        queryset = (
            GeneratedContent.objects.for_user(self.request.user)
            .select_related("listing", "listing__agent")
            .prefetch_related("variants")
        )

        listing_id = self.request.query_params.get("listing")
        if listing_id and listing_id.isdigit():
            queryset = queryset.filter(listing_id=int(listing_id))

        job_status = self.request.query_params.get("job_status")
        if job_status:
            queryset = queryset.filter(job_status=job_status)

        language = self.request.query_params.get("language")
        if language:
            queryset = queryset.filter(language=language)

        return queryset

    @action(detail=False, methods=["get"], url_path="languages")
    def languages(self, request: Request) -> Response:
        """The languages this deployment offers, and how well each is checked.

        ``fully_validated`` is published rather than hidden: an agent choosing
        a language deserves to know up front that the automatic fact check will
        only partly understand the result.
        """
        return Response(
            [
                {
                    "code": language.code,
                    "name": language.name,
                    "rtl": language.rtl,
                    "fully_validated": language.is_fully_covered,
                    "unchecked": language.missing_checks,
                }
                for language in enabled_languages()
            ]
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="generate",
        throttle_classes=[ScopedRateThrottle],
    )
    def generate(self, request: Request) -> Response:
        """``POST /api/ai-content/generate/`` — the only way to start a job.

        Returns 202 immediately with the record; the OpenAI call happens in a
        Celery worker. Each call creates a NEW record rather than overwriting
        the last one, so regenerating keeps the history — useful when comparing
        prompt versions, and necessary for an audit trail of what was offered
        to an agent.
        """
        serializer = GenerateRequestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        listing = serializer.validated_data["listing"]
        tone = serializer.validated_data.get("tone", "")
        languages = serializer.validated_data.get("languages") or [SOURCE_LANGUAGE]

        generations = []
        for language in languages:
            generation = create_generation(
                listing, request.user, tone=tone, language=language
            )
            # Queued after the row is committed, so the worker cannot look for
            # a record that is not there yet.
            generate_content.delay(generation.pk)
            generations.append(generation)

        logger.info(
            "Queued %s generation(s) for listing %s by user %s: %s",
            len(generations), listing.pk, request.user.pk, ", ".join(languages),
        )
        return Response(
            self.get_serializer(generations, many=True).data,
            status=status.HTTP_202_ACCEPTED,
        )

    generate.throttle_scope = "ai_generate"

    # url_name pinned so the route reverses as `...-status`; DRF would
    # otherwise derive `job-status` from the method name.
    @action(detail=True, methods=["get"], url_path="status", url_name="status")
    def job_status(self, request: Request, pk=None) -> Response:
        """Small payload for polling — this gets called on a timer."""
        return Response(GeneratedContentStatusSerializer(self.get_object()).data)

    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request: Request, pk=None) -> Response:
        """Agent approves or rejects a draft.

        Content is created as a draft and stays one until a person says
        otherwise; that decision is recorded with who made it and when.
        """
        generation = self.get_object()
        serializer = ReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decision = serializer.validated_data["decision"]

        if decision == ReviewStatus.APPROVED and not generation.is_usable:
            return Response(
                {
                    "detail": (
                        "This content cannot be approved: it failed the fact check "
                        "against the listing."
                    ),
                    "validation_issues": generation.validation_issues,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        generation.review_status = decision
        generation.reviewed_at = timezone.now()
        generation.reviewed_by = request.user
        generation.save(
            update_fields=["review_status", "reviewed_at", "reviewed_by", "updated_at"]
        )
        return Response(self.get_serializer(generation).data)

    @action(detail=True, methods=["post"], url_path="review-all")
    def review_all(self, request: Request, pk=None) -> Response:
        """Apply one decision to every variant that can take it.

        A convenience for "these are all fine", not a replacement for
        per-variant review: variants that failed the fact check are skipped
        rather than swept along, and the response says how many.
        """
        generation = self.get_object()
        serializer = ReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decision = serializer.validated_data["decision"]

        applied, skipped = 0, 0
        for variant in generation.variants.all():
            if decision == ReviewStatus.APPROVED and not variant.is_usable:
                skipped += 1
                continue
            variant.review_status = decision
            variant.reviewed_at = timezone.now()
            variant.reviewed_by = request.user
            variant.save(
                update_fields=["review_status", "reviewed_at", "reviewed_by", "updated_at"]
            )
            applied += 1

        generation.refresh_from_db()
        return Response(
            {
                "applied": applied,
                "skipped": skipped,
                "generation": self.get_serializer(generation).data,
            }
        )

    @action(detail=False, methods=["get"], url_path="usage")
    def usage(self, request: Request) -> Response:
        """Token and cost totals for whatever the caller can see."""
        queryset = GeneratedContent.objects.for_user(request.user)
        totals = queryset.aggregate(
            generations=Count("id"),
            prompt_tokens=Sum("prompt_tokens"),
            completion_tokens=Sum("completion_tokens"),
            total_tokens=Sum("total_tokens"),
            estimated_cost_usd=Sum("estimated_cost_usd"),
        )
        return Response(
            {
                "generations": totals["generations"] or 0,
                "prompt_tokens": totals["prompt_tokens"] or 0,
                "completion_tokens": totals["completion_tokens"] or 0,
                "total_tokens": totals["total_tokens"] or 0,
                "estimated_cost_usd": str(totals["estimated_cost_usd"] or "0.000000"),
                "by_status": {
                    row["job_status"]: row["count"]
                    for row in queryset.values("job_status").annotate(count=Count("id"))
                },
            }
        )


class ContentVariantViewSet(viewsets.ReadOnlyModelViewSet):
    """Individual variants: read, edit, review.

    Separate from the generation so an agent can act on one piece of copy at a
    time — approve the Instagram caption, rewrite the LinkedIn one, discard the
    property description — without touching the others.
    """

    serializer_class = ContentVariantSerializer
    permission_classes = [IsAuthenticated, ContentVariantPermission]

    def get_queryset(self) -> QuerySet[ContentVariant]:
        generations = GeneratedContent.objects.for_user(self.request.user)
        queryset = ContentVariant.objects.filter(
            generation__in=generations
        ).select_related("generation", "generation__listing", "generation__listing__agent")

        generation_id = self.request.query_params.get("generation")
        if generation_id and generation_id.isdigit():
            queryset = queryset.filter(generation_id=int(generation_id))
        return queryset

    @action(detail=True, methods=["post"], url_path="edit")
    def edit(self, request: Request, pk=None) -> Response:
        """Rewrite one variant.

        The edit is re-validated and any issues are returned, but they do not
        block: the fact check exists to stop the model inventing, not to stop a
        licensed agent writing a sentence they can stand behind. Editing also
        returns the variant to draft — an approval that referred to different
        words than the ones now on screen would be worthless.
        """
        variant = self.get_object()
        serializer = VariantEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if variant.is_hashtags:
            items = serializer.validated_data.get("items")
            if items is None:
                return Response(
                    {"items": ["This variant is a hashtag list; send 'items'."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            apply_variant_edit(variant, items=items, user=request.user)
        else:
            text = serializer.validated_data.get("text")
            if text is None:
                return Response(
                    {"text": ["This variant is prose; send 'text'."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            apply_variant_edit(variant, text=text, user=request.user)

        return Response(self.get_serializer(variant).data)

    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request: Request, pk=None) -> Response:
        """Approve or discard this one variant."""
        variant = self.get_object()
        serializer = ReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decision = serializer.validated_data["decision"]

        if decision == ReviewStatus.APPROVED and not variant.is_usable:
            return Response(
                {
                    "detail": (
                        "This variant cannot be approved: it failed the fact check "
                        "against the listing. Edit it, or regenerate."
                    ),
                    "validation_issues": variant.validation_issues,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        variant.review_status = decision
        variant.reviewed_at = timezone.now()
        variant.reviewed_by = request.user
        variant.save(
            update_fields=["review_status", "reviewed_at", "reviewed_by", "updated_at"]
        )
        return Response(self.get_serializer(variant).data)
