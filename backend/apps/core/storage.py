"""Storage-agnostic upload helpers.

=============================================================================
WHY THIS MODULE EXISTS
=============================================================================

Files are written through Django's storage API (``django.core.files.storage``)
and never through ``open()`` or ``os.path`` on a hardcoded directory. The
consequence is that swapping the storage backend is a *settings* change, not a
code change:

    # settings.py — local filesystem (today)
    STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}}

    # settings.py — S3-compatible object store (later; needs django-storages)
    STORAGES = {"default": {"BACKEND": "storages.backends.s3.S3Storage", ...}}

Nothing in models, serializers, views or the React app has to change: an
``ImageField`` reads and writes through whatever backend ``STORAGES["default"]``
names, and ``instance.photo.url`` keeps returning a working URL.

The ``upload_to`` callables below return *keys*, not paths — forward-slash
separated, no leading slash, no drive letters. On the local filesystem a key
becomes a path under ``MEDIA_ROOT``; on S3 the same string is the object key.
Keeping them opaque and platform-neutral is what makes them portable.

Keys are randomised (UUID) rather than derived from the uploaded filename:

  * an attacker cannot choose where their file lands or overwrite someone
    else's by guessing a name,
  * user-supplied filenames never reach the filesystem, so path traversal
    ("../../etc/passwd") and reserved Windows names (CON, NUL) are moot,
  * replacing a photo writes a new key, so caches and CDNs see a new URL
    instead of serving a stale image.

The first two hex characters are used as a shard directory: it keeps local
filesystem directories from growing to tens of thousands of entries, and acts
as a harmless key prefix on object stores.
"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath
from uuid import uuid4

logger = logging.getLogger(__name__)


def build_upload_key(prefix: str, filename: str) -> str:
    """Return a random, backend-neutral storage key under ``prefix``."""
    # PurePosixPath keeps this forward-slash based on every platform.
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    # Strip anything that is not a plain extension; the validator has already
    # checked it against an allowlist, this is belt and braces.
    extension = suffix[1:] if suffix else "bin"
    extension = "".join(char for char in extension if char.isalnum())[:10] or "bin"

    token = uuid4().hex
    return f"{prefix}/{token[:2]}/{token}.{extension}"


# ``upload_to`` callables are serialised into migrations by dotted path, so
# they must be importable module-level functions — never lambdas or closures.


def agent_photo_upload_to(instance, filename: str) -> str:
    """Storage key for an agent's profile photo."""
    return build_upload_key("agents/photos", filename)


def brokerage_logo_upload_to(instance, filename: str) -> str:
    """Storage key for a brokerage logo."""
    return build_upload_key("brokerages/logos", filename)


def delete_stored_file(file_field) -> None:
    """Delete the file behind a ``FieldFile``, if any, via the storage API.

    Used when a photo/logo is replaced or its row is deleted, so old objects do
    not accumulate. Failures are logged and swallowed: an orphaned file is
    untidy, but it must never break the request that triggered the cleanup.
    """
    if not file_field:
        return

    name = getattr(file_field, "name", None)
    if not name:
        return

    storage = file_field.storage
    try:
        if storage.exists(name):
            storage.delete(name)
    except Exception:  # pragma: no cover - backend-specific failures
        logger.warning("Could not delete stored file %r", name, exc_info=True)
