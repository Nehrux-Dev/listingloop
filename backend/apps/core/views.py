"""Infrastructure endpoints."""

import logging

import redis
from django.conf import settings
from django.db import connections
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


def _check_database() -> dict:
    """Run a trivial query against the default database."""
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # surface any connection/driver failure as unhealthy
        logger.warning("Database health check failed: %s", exc)
        return {"status": "error", "detail": str(exc)}
    return {"status": "ok"}


def _check_redis() -> dict:
    """PING the Redis instance Celery and the cache both point at."""
    client = None
    try:
        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        client.ping()
    except Exception as exc:
        logger.warning("Redis health check failed: %s", exc)
        return {"status": "error", "detail": str(exc)}
    finally:
        if client is not None:
            client.close()
    return {"status": "ok"}


class HealthCheckView(APIView):
    """``GET /api/health/``

    Returns ``200`` when Django can reach both Postgres and Redis, and ``503``
    otherwise, so container orchestrators and load balancers can use it as a
    readiness probe.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request: Request) -> Response:
        checks = {
            "database": _check_database(),
            "redis": _check_redis(),
        }
        healthy = all(check["status"] == "ok" for check in checks.values())

        payload = {
            "status": "ok" if healthy else "error",
            "checks": checks,
        }
        http_status = (
            status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        return Response(payload, status=http_status)
