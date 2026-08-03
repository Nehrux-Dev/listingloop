"""One-off, agent-triggered import of a listing from a public URL.

The flow is deliberately synchronous and manual: an agent pastes a URL, the
server fetches that one page once, and returns a draft. Nothing is scheduled,
nothing recurs, and nothing is re-fetched later.

What comes back is always a **draft**:

  * ``status`` is DRAFT and ``verification_status`` is UNVERIFIED, whatever was
    extracted,
  * ``imported_fields`` names exactly which fields the page populated,
  * ``import_warnings`` says, in plain language, what could not be read.

Nothing downstream can use the listing until the agent reviews it and
explicitly verifies. An import is a typing shortcut, not a source of truth.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from apps.core.validators import ImageUploadValidator
from apps.listings.extraction import extract_listing_data
from apps.listings.fetching import FetchError, UnsafeUrlError, fetch_document, fetch_image
from apps.listings.models import (
    Listing,
    ListingPhoto,
    ListingSource,
    ListingStatus,
    VerificationStatus,
)

logger = logging.getLogger(__name__)

image_upload_validator = ImageUploadValidator()

CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


@dataclass
class ImportOutcome:
    listing: Listing
    extracted_fields: list[str]
    warnings: list[str]
    photo_count: int


def _download_photo(listing: Listing, url: str, order: int) -> ListingPhoto | None:
    """Fetch one remote image and attach it, or return None.

    Remote images go through exactly the same guarded fetcher and the same
    upload validator as a browser upload — a URL on a page we do not control is
    no more trustworthy than a file a user picked.
    """
    document = fetch_image(url)

    extension = CONTENT_TYPE_EXTENSIONS.get(document.content_type)
    if extension is None:
        raise FetchError(f"Unsupported image type '{document.content_type}'.")

    upload = SimpleUploadedFile(
        f"imported.{extension}", document.content, content_type=document.content_type
    )
    # Raises if it is not really an image, is too large, or is the wrong format.
    image_upload_validator(upload)
    upload.seek(0)

    return ListingPhoto.objects.create(
        listing=listing, image=upload, order=order, source_url=url[:1000]
    )


def import_listing_from_url(url: str, agent) -> ImportOutcome:
    """Fetch ``url`` once and build an unverified draft listing for ``agent``.

    Raises ``UnsafeUrlError`` or ``FetchError`` when the page cannot be
    retrieved at all — in that case no listing is created, because a draft
    containing nothing but a URL helps nobody.

    If the page *is* retrieved but yields little, a draft is still created with
    whatever was found and warnings for the rest. Blank beats invented.
    """
    document = fetch_document(url)
    result = extract_listing_data(document.text, document.url)

    warnings = list(result.warnings)

    with transaction.atomic():
        listing = Listing.objects.create(
            agent=agent,
            source=ListingSource.IMPORT,
            source_url=document.url[:1000],
            status=ListingStatus.DRAFT,
            # Explicit, not merely the default: an imported listing is never
            # verified, no matter how complete the extraction looked.
            verification_status=VerificationStatus.UNVERIFIED,
            imported_fields=result.extracted_fields,
            import_warnings=warnings,
            **result.fields,
        )

    photo_count = 0
    for index, photo_url in enumerate(result.photo_urls):
        try:
            if _download_photo(listing, photo_url, order=index):
                photo_count += 1
        except (UnsafeUrlError, FetchError, DjangoValidationError) as exc:
            # One bad image must not lose the whole import.
            logger.info("Skipped imported photo %r: %s", photo_url, exc)
            warnings.append(f"A photo could not be imported: {exc}")
        except Exception:  # pragma: no cover - defensive
            logger.warning("Unexpected error importing photo %r", photo_url, exc_info=True)
            warnings.append("A photo could not be imported.")

    if result.photo_urls and photo_count == 0:
        warnings.append("None of the photos on the page could be imported.")

    if warnings != listing.import_warnings:
        listing.import_warnings = warnings
        listing.save(update_fields=["import_warnings", "updated_at"])

    return ImportOutcome(
        listing=listing,
        extracted_fields=result.extracted_fields,
        warnings=warnings,
        photo_count=photo_count,
    )
