"""Celery tasks for the templates app.

Deliberately thin, the same way ``ai_content.tasks`` is: everything that
decides anything lives in ``importing.run_import``, and this layer adds
queueing and a terminal state. That split is what lets the pipeline be run
straight from a shell or a test with no broker running.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.templates.importing import TemplateImportError, run_import
from apps.templates.models import TERMINAL_IMPORT_STATUSES, ImportStatus, TemplateImport

logger = logging.getLogger(__name__)


def _fail(job: TemplateImport, message: str) -> None:
    """Put the job in a terminal failed state with a message worth reading."""
    job.status = ImportStatus.FAILED
    job.error = message
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "error", "finished_at", "updated_at"])


@shared_task(
    name="templates.import_artwork",
    bind=True,
    # Same reasoning as ai_content.generate: the provider client already
    # retries transient HTTP failures, and run_import leaves a clean record
    # rather than raising for anything the user can act on. Task-level retries
    # would mostly re-run vision calls that failed for a real reason, at full
    # price each time.
    max_retries=0,
    acks_late=True,
)
def import_template_artwork(self, import_id: int) -> dict:
    """Extract one queued upload into a template."""
    job = TemplateImport.objects.filter(pk=import_id).first()
    if job is None:
        logger.warning("Template import %s no longer exists; nothing to do.", import_id)
        return {"id": import_id, "status": "missing"}

    if job.status in TERMINAL_IMPORT_STATUSES:
        # acks_late means a task can be redelivered after a worker dies.
        # Without this guard, a redelivery re-runs a finished extraction and
        # bills for it a second time.
        logger.info("Template import %s is already %s; skipping.", import_id, job.status)
        return {"id": import_id, "status": job.status}

    try:
        template = run_import(job)
    except TemplateImportError as exc:
        # Raised with a message written for the user — the only kind of failure
        # that reaches them verbatim.
        logger.info("Template import %s failed: %s", import_id, exc)
        _fail(job, str(exc))
        return {"id": import_id, "status": ImportStatus.FAILED}
    except Exception as exc:  # pragma: no cover - defensive
        # Anything unexpected must still leave a terminal state, or the
        # frontend polls a job that will never finish. The exception's own text
        # is logged and not shown: it can carry request detail, and says
        # nothing the user could act on.
        logger.exception("Template import %s crashed", import_id)
        job.refresh_from_db()
        _fail(
            job,
            "Something went wrong while importing that design. The file was "
            "saved — try again, and contact support if it keeps failing.",
        )
        return {"id": import_id, "status": ImportStatus.FAILED, "error": type(exc).__name__}

    return {"id": import_id, "status": ImportStatus.SUCCEEDED, "template": template.pk}
