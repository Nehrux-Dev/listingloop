"""Project configuration package.

Importing the Celery app here ensures ``@shared_task`` works everywhere once
tasks are added.
"""

from config.celery import app as celery_app

__all__ = ("celery_app",)
