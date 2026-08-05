"""Celery tasks for content generation (Part B).

Deliberately thin. All the behaviour is in ``services.run_generation``, which
Part A validated synchronously; this layer adds queueing and nothing else. That
split is why the async version needed no new logic — and why the pipeline can
still be run without a broker when debugging.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.ai_content.models import GeneratedContent, JobStatus
from apps.ai_content.services import run_generation

logger = logging.getLogger(__name__)


@shared_task(
    name="ai_content.generate",
    bind=True,
    # The provider client already retries transient HTTP failures
    # (OPENAI_MAX_RETRIES), and run_generation records a clean failure rather
    # than raising, so task-level retries would mostly re-run calls that failed
    # for a real reason — at full price each time.
    max_retries=0,
    acks_late=True,
)
def generate_content(self, generation_id: int) -> dict:
    """Run one queued generation."""
    generation = GeneratedContent.objects.filter(pk=generation_id).first()
    if generation is None:
        logger.warning("Generation %s no longer exists; nothing to do.", generation_id)
        return {"id": generation_id, "status": "missing"}

    if generation.job_status not in (JobStatus.QUEUED, JobStatus.RUNNING):
        # acks_late means a task can be redelivered after a worker dies. Without
        # this guard a redelivery would re-run a finished job and bill for it
        # twice.
        logger.info(
            "Generation %s is already %s; skipping.", generation_id, generation.job_status
        )
        return {"id": generation_id, "status": generation.job_status}

    try:
        run_generation(generation)
    except Exception as exc:  # pragma: no cover - defensive
        # Anything unexpected must still leave the record in a terminal state,
        # or the frontend polls a job that will never finish.
        logger.exception("Generation %s crashed", generation_id)
        generation.refresh_from_db()
        generation.job_status = JobStatus.FAILED
        generation.error_message = f"Unexpected error: {type(exc).__name__}"
        generation.finished_at = timezone.now()
        generation.save(
            update_fields=["job_status", "error_message", "finished_at", "updated_at"]
        )
        raise

    return {
        "id": generation.pk,
        "status": generation.job_status,
        "validation": generation.validation_status,
        "total_tokens": generation.total_tokens,
        "estimated_cost_usd": str(generation.estimated_cost_usd),
    }
