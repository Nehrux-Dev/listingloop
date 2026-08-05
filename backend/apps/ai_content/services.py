"""Orchestration: build the prompt, call the API, validate, store.

This is the synchronous core (Part A). The Celery task in ``tasks.py`` is a
thin wrapper around ``run_generation`` — writing it this way means the pipeline
can be exercised, judged and debugged without any async machinery in the way,
and the async layer adds queueing rather than behaviour.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from apps.ai_content.client import (
    AIConfigurationError,
    AIGenerationError,
    complete_json,
)
from apps.ai_content.models import (
    ContentKind,
    ContentVariant,
    GeneratedContent,
    JobStatus,
    ValidationStatus,
    VariantKind,
    VARIANT_ORDER,
)
from apps.ai_content.prompts import PROMPT_VERSION, RESPONSE_SCHEMA, build_messages
from apps.ai_content.validation import validate_hashtags, validate_text
from apps.listings.models import Listing

#: Worst-first, so a generation's headline status reflects its worst variant.
_STATUS_SEVERITY = {
    ValidationStatus.REJECTED: 3,
    ValidationStatus.FLAGGED: 2,
    ValidationStatus.PASSED: 1,
    ValidationStatus.PENDING: 0,
}

logger = logging.getLogger(__name__)


class ListingNotUsable(ValueError):
    """The listing cannot be used for generation."""


def create_generation(listing: Listing, user, *, tone: str = "") -> GeneratedContent:
    """Create the queued record. Does not call the API.

    Separated from ``run_generation`` so the API can return a job id
    immediately, and so nothing is ever generated as a side effect of reading a
    listing — generation only ever starts where this function is called
    explicitly.
    """
    if not listing.is_usable_for_content:
        raise ListingNotUsable(
            "This listing has not been verified. Review and confirm its details "
            "before generating content from it."
        )

    return GeneratedContent.objects.create(
        listing=listing,
        requested_by=user if getattr(user, "is_authenticated", False) else None,
        kind=ContentKind.CONTENT_PACK,
        job_status=JobStatus.QUEUED,
        prompt_version=PROMPT_VERSION,
        prompt_facts={"tone": tone} if tone else {},
    )


def run_generation(generation: GeneratedContent, *, completion_fn=None) -> GeneratedContent:
    """Execute one generation end to end and store the outcome.

    ``completion_fn`` is injectable so tests and the offline sample run can
    substitute a stub without touching the network. Everything after the call —
    parsing, validation, storage — is identical either way, which is the point:
    the validation layer is exercised by the same code path in tests as in
    production.

    Resolved here rather than as a default argument: a default would bind
    ``complete_json`` at import time, and patching the module attribute (which
    is how the tests stub the provider) would then have no effect.
    """
    if completion_fn is None:
        completion_fn = complete_json

    listing = generation.listing
    tone = (generation.prompt_facts or {}).get("tone", "")

    generation.job_status = JobStatus.RUNNING
    generation.started_at = timezone.now()
    generation.save(update_fields=["job_status", "started_at", "updated_at"])

    messages, facts = build_messages(listing, tone=tone)

    try:
        result = completion_fn(messages, RESPONSE_SCHEMA)
    except (AIGenerationError, AIConfigurationError) as exc:
        generation.job_status = JobStatus.FAILED
        generation.error_message = str(exc)
        generation.finished_at = timezone.now()
        generation.prompt_facts = {**facts, **({"tone": tone} if tone else {})}
        generation.save(
            update_fields=[
                "job_status", "error_message", "finished_at", "prompt_facts", "updated_at",
            ]
        )
        return generation

    # Record provenance before validation, so a rejected generation is still
    # fully auditable: which model, which prompt, which facts, what it cost.
    generation.model_name = result.model
    generation.prompt_facts = {**facts, **({"tone": tone} if tone else {})}
    generation.prompt_tokens = result.prompt_tokens
    generation.completion_tokens = result.completion_tokens
    generation.total_tokens = result.total_tokens
    generation.estimated_cost_usd = result.estimated_cost_usd
    generation.duration_ms = result.duration_ms

    variants = _store_variants(generation, result.payload, listing, facts)

    # The generation's own status is the worst of its variants, so a listing
    # index can show "needs attention" without loading every variant. Each
    # variant is still independently usable — one bad LinkedIn caption does
    # not spoil the Instagram one.
    generation.validation_status = max(
        (variant.validation_status for variant in variants),
        key=lambda status: _STATUS_SEVERITY.get(status, 0),
        default=ValidationStatus.PENDING,
    )
    generation.validation_issues = [
        {**issue, "variant": variant.kind}
        for variant in variants
        for issue in variant.validation_issues
    ]

    # `caption` and `hashtags` on the parent mirror the Instagram variant and
    # the hashtag set, for callers that just want the simple case. They follow
    # the same rule as everywhere else: rejected copy never lands in them.
    instagram = next(
        (v for v in variants if v.kind == VariantKind.INSTAGRAM_CAPTION), None
    )
    tags = next((v for v in variants if v.kind == VariantKind.HASHTAGS), None)

    generation.caption = instagram.text if instagram and instagram.is_usable else ""
    generation.hashtags = list(tags.items) if tags and tags.is_usable else []
    generation.rejected_output = {
        variant.kind: variant.rejected_items if variant.is_hashtags else variant.rejected_text
        for variant in variants
        if variant.validation_status == ValidationStatus.REJECTED
    }

    generation.kind = ContentKind.CONTENT_PACK
    generation.job_status = JobStatus.READY
    generation.finished_at = timezone.now()
    generation.save()

    _run_compliance(generation, variants)

    logger.info(
        "Generation %s for listing %s: %s, %s/%s variants usable (%s tokens, $%s)",
        generation.pk,
        listing.pk,
        generation.validation_status,
        sum(1 for variant in variants if variant.is_usable),
        len(variants),
        generation.total_tokens,
        generation.estimated_cost_usd,
    )
    return generation


def _run_compliance(generation, variants) -> None:
    """Check each variant against the compliance rules and store the results.

    Runs here, right after generation, so the flags are already waiting when
    the agent opens the review panel rather than appearing only at export.

    Failures are swallowed on purpose: compliance is a *review aid* layered on
    top of a finished generation, and a broken rule set must not turn a
    successful, paid-for generation into a failed job. The absence of an
    evaluation is visible in the UI, which is the honest signal.
    """
    from apps.compliance.engine import evaluate_and_store
    from apps.compliance.subjects import from_content_variant

    for variant in variants:
        try:
            evaluate_and_store(
                from_content_variant(variant),
                generated_content=generation,
                content_variant=variant,
            )
        except Exception:
            logger.warning(
                "Compliance evaluation failed for variant %s", variant.pk, exc_info=True
            )


def _store_variants(generation, payload: dict, listing, facts: dict) -> list[ContentVariant]:
    """Validate and persist every variant in one response.

    Each variant is checked on its own, by the same rules, so a rejection names
    the format that caused it rather than condemning the whole pack.
    """
    generation.variants.all().delete()  # regeneration replaces, never appends
    variants: list[ContentVariant] = []

    for kind in VARIANT_ORDER:
        if kind == VariantKind.HASHTAGS:
            raw = payload.get("hashtags") or []
            report = validate_hashtags(raw, listing, facts)
            items = [tag for tag in raw if isinstance(tag, str)]
            variant = ContentVariant(
                generation=generation,
                kind=kind,
                validation_status=report.status,
                validation_issues=report.as_list(),
            )
            if report.rejected:
                variant.items = []
                variant.rejected_items = items
            else:
                variant.items = items
        else:
            text = (payload.get(kind) or "").strip()
            report = validate_text(text, listing, facts, label=kind)
            variant = ContentVariant(
                generation=generation,
                kind=kind,
                validation_status=report.status,
                validation_issues=report.as_list(),
                original_text=text,
            )
            if report.rejected:
                variant.text = ""
                variant.rejected_text = text
            else:
                variant.text = text

        variant.save()
        variants.append(variant)

    return variants


def apply_variant_edit(variant: ContentVariant, *, text: str = "", items=None, user=None):
    """Record an agent's edit and re-validate the result.

    Re-validating an edit is advisory rather than blocking: the validator
    exists to stop the *model* inventing things, and a licensed agent writing a
    sentence may well know something the listing does not record. They still
    see the warnings, and ``is_edited`` records whose words these now are.

    Editing returns the variant to draft — an approval applied to different
    words than the ones on screen would be worthless.
    """
    from django.utils import timezone as tz

    listing = variant.generation.listing
    facts = {
        key: value
        for key, value in (variant.generation.prompt_facts or {}).items()
        if key != "tone"
    }

    if variant.is_hashtags:
        items = [tag for tag in (items or []) if isinstance(tag, str)]
        report = validate_hashtags(items, listing, facts)
        variant.items = items
        variant.rejected_items = []
    else:
        report = validate_text(text, listing, facts, label=variant.kind)
        if not variant.original_text:
            variant.original_text = variant.text or variant.rejected_text
        variant.text = text
        variant.rejected_text = ""

    variant.validation_status = report.status
    variant.validation_issues = report.as_list()
    variant.is_edited = True
    variant.edited_at = tz.now()
    variant.review_status = "draft"
    variant.reviewed_at = None
    variant.reviewed_by = None
    variant.save()
    return variant


def generate_for_listing(listing: Listing, user, *, tone: str = "", completion_fn=None):
    """Synchronous convenience wrapper: create then run. Used by Part A."""
    generation = create_generation(listing, user, tone=tone)
    return run_generation(generation, completion_fn=completion_fn)


def latest_usable_for_listing(listing: Listing) -> GeneratedContent | None:
    return (
        GeneratedContent.objects.filter(listing=listing)
        .usable()
        .order_by("-created_at")
        .first()
    )


__all__ = [
    "ListingNotUsable",
    "ValidationStatus",
    "apply_variant_edit",
    "create_generation",
    "generate_for_listing",
    "latest_usable_for_listing",
    "run_generation",
]
