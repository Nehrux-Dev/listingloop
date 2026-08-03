"""Celery application.

Broker/result backend point at Redis via settings (``CELERY_*`` keys).
No tasks are defined yet — ``autodiscover_tasks`` will pick up
``apps/<domain>/tasks.py`` as soon as they exist.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("real_estate")

# All Celery settings live in Django settings under the CELERY_ namespace.
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
