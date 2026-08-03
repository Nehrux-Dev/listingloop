"""
Django settings for the Real Estate project.

All environment-specific values are read from environment variables (see
`.env.example` at the repository root). Nothing secret should ever be
hard-coded here.
"""

import sys
from datetime import timedelta
from pathlib import Path

import environ

# backend/config/settings.py -> backend/
BASE_DIR = Path(__file__).resolve().parent.parent
# repository root, where .env lives
REPO_ROOT = BASE_DIR.parent

#: True while `manage.py test` is running. Used to keep tests hermetic
#: (in-memory cache instead of Redis, fast password hashing).
TESTING = "test" in sys.argv

env = environ.Env()

# Read .env from the repo root when present (local runs outside Docker).
# Inside Docker, compose injects the same variables into the environment.
env_file = REPO_ROOT / ".env"
if env_file.exists():
    env.read_env(str(env_file))


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

# Also used as the HS256 signing key for JWTs, so it must be long (>= 32
# bytes) as well as secret.
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="dev-insecure-key-replace-me-before-any-real-deployment",
)
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "0.0.0.0", "backend"]
)

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    # Stores revoked/rotated refresh tokens so logout and rotation actually
    # invalidate them. Without it, a refresh token would stay valid until it
    # expired, even after the user logged out.
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
]

# One app per domain.
LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.listings",
    "apps.templates",
    "apps.ai_content",
    "apps.compliance",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

if env("DATABASE_URL", default=None):
    DATABASES = {"default": env.db("DATABASE_URL")}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", default="real_estate"),
            "USER": env("POSTGRES_USER", default="real_estate"),
            "PASSWORD": env("POSTGRES_PASSWORD", default="real_estate"),
            "HOST": env("POSTGRES_HOST", default="localhost"),
            "PORT": env("POSTGRES_PORT", default="5432"),
        }
    }

DATABASES["default"].setdefault("CONN_MAX_AGE", env.int("DB_CONN_MAX_AGE", default=60))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Redis / cache
# ---------------------------------------------------------------------------

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

if TESTING:
    # Keep the test suite independent of a running Redis, and stop DRF's
    # throttle counters from leaking between test runs.
    CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }


# ---------------------------------------------------------------------------
# Celery (connection only — no tasks defined yet)
# ---------------------------------------------------------------------------

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = env("DJANGO_TIME_ZONE", default="UTC")
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True


# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": env.int("PASSWORD_MIN_LENGTH", default=10)},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

if TESTING:
    # The default PBKDF2 hasher is intentionally slow; swapping it out keeps
    # the suite fast. Never do this outside tests.
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("DJANGO_TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Static / media
# ---------------------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"


# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    # JWT only. Session auth is deliberately absent: mixing a cookie-based
    # session with a cookie-based refresh token invites CSRF confusion, and
    # the API has exactly one client — the SPA.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    # Fail closed. Endpoints that must be public (health check, login,
    # register, refresh) opt out explicitly with `permission_classes`.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": (
        [
            "rest_framework.renderers.JSONRenderer",
            "rest_framework.renderers.BrowsableAPIRenderer",
        ]
        if DEBUG
        else ["rest_framework.renderers.JSONRenderer"]
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_THROTTLE_RATES": {
        # Applied to login / register / refresh (see the `auth` throttle scope)
        # to blunt credential stuffing.
        "auth": env("AUTH_THROTTLE_RATE", default="30/min"),
    },
}


# ---------------------------------------------------------------------------
# JWT (djangorestframework-simplejwt)
# ---------------------------------------------------------------------------

SIMPLE_JWT = {
    # Short-lived by design: the access token is a bearer credential held in
    # browser memory and cannot be revoked once issued, so its window of use
    # is kept small.
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=env.int("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", default=5)
    ),
    # Long-lived, but only ever travels in the httpOnly cookie.
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=env.int("JWT_REFRESH_TOKEN_LIFETIME_DAYS", default=7)
    ),
    # Every refresh issues a new refresh token...
    "ROTATE_REFRESH_TOKENS": True,
    # ...and blacklists the one that was presented, so a captured refresh
    # token is usable at most once.
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}


# ---------------------------------------------------------------------------
# Refresh-token cookie
#
# See apps/accounts/cookies.py for the full explanation of why the refresh
# token lives in an httpOnly cookie and what each flag defends against.
# ---------------------------------------------------------------------------

AUTH_COOKIE_NAME = env("AUTH_COOKIE_NAME", default="refresh_token")
# HTTPS-only. Defaults to on whenever DEBUG is off, so production is secure
# by default and only local http://localhost development relaxes it.
AUTH_COOKIE_SECURE = env.bool("AUTH_COOKIE_SECURE", default=not DEBUG)
# 'Lax' blocks the cookie on cross-site POSTs, which is the CSRF defence for
# the refresh endpoint. Only move to 'None' if the SPA is served from a
# different site than the API — and add a CSRF token if you do.
AUTH_COOKIE_SAMESITE = env("AUTH_COOKIE_SAMESITE", default="Lax")
# Scoped so the browser only attaches this credential to the auth endpoints.
AUTH_COOKIE_PATH = env("AUTH_COOKIE_PATH", default="/api/auth/")
# Empty means a host-only cookie, which is the safest default.
AUTH_COOKIE_DOMAIN = env("AUTH_COOKIE_DOMAIN", default="")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "/admin/login/"


# ---------------------------------------------------------------------------
# CORS / CSRF
# ---------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:5173", "http://127.0.0.1:5173"],
)
# Required for the browser to send the refresh cookie on cross-origin calls.
# In development the Vite proxy makes API calls same-origin, so this only
# matters if the SPA is pointed straight at the API.
CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=["http://localhost:5173", "http://127.0.0.1:5173"],
)


# ---------------------------------------------------------------------------
# Security headers (relaxed under DEBUG for local http development)
# ---------------------------------------------------------------------------

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

if not DEBUG:
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[{levelname}] {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
