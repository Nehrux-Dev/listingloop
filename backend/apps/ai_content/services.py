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
    GeneratedContent,
    JobStatus,
    ValidationStatus,
)
from apps.ai_content.prompts import PROMPT_VERSION, RESPONSE_SCHEMA, build_messages
from apps.ai_content.validation import validate_generation
from apps.listings.models import Listing

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
        kind=ContentKind.SOCIAL_CAPTION,
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

    report = validate_generation(result.payload, listing, facts)
    generation.validation_status = report.status
    generation.validation_issues = report.as_list()

    caption = (result.payload.get("caption") or "").strip()
    hashtags = result.payload.get("hashtags") or []

    if report.rejected:
        # The words are kept for debugging but NOT in the fields the UI renders
        # as copy, so an invented claim cannot be copied out by accident.
        generation.caption = ""
        generation.hashtags = []
        generation.rejected_output = {
            "caption": caption,
            "hashtags": hashtags,
            "facts_used": result.payload.get("facts_used", []),
        }
    else:
        generation.caption = caption
        generation.hashtags = [tag for tag in hashtags if isinstance(tag, str)]
        generation.rejected_output = {}

    generation.job_status = JobStatus.READY
    generation.finished_at = timezone.now()
    generation.save()

    logger.info(
        "Generation %s for listing %s: %s (%s tokens, $%s)",
        generation.pk,
        listing.pk,
        generation.validation_status,
        generation.total_tokens,
        generation.estimated_cost_usd,
    )
    return generation


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
    "create_generation",
    "generate_for_listing",
    "latest_usable_for_listing",
    "run_generation",
]
