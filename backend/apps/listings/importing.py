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
from apps.listings.fetching import (
    FetchError,
    SiteBlockedError,
    UnsafeUrlError,
    fetch_document,
    fetch_document_rendered,
    fetch_image,
)
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
    document, result = _fetch_and_extract(url)
    return _build_from_html(
        document.text, document.url, agent, download_photos=True, result=result
    )


def _fetch_and_extract(url: str):
    """Fetch cheaply; escalate to a browser only when that was not enough.

    The plain HTTP fetch handles most pages in a fraction of a second. It fails
    on two kinds of site: ones that build the listing in JavaScript, and ones
    that decline automated requests outright. A browser fixes the first and
    cannot fix the second, so it is worth exactly one retry and no more.

    Order matters: try cheap first, and only pay for a browser on evidence that
    the cheap answer was empty. Doing it the other way round would put a
    multi-second page load in front of every import to help a minority of them.
    """
    from django.conf import settings

    blocked: SiteBlockedError | None = None
    document = None
    result = None

    try:
        document = fetch_document(url)
        result = extract_listing_data(document.text, document.url)
        if result.structured:
            return document, result
    except SiteBlockedError as exc:
        # Hold it: a browser may well be served where a plain client was not,
        # and being an actual browser is not a disguise. If that fails too, the
        # site has genuinely refused and this is what we re-raise.
        blocked = exc

    if not settings.LISTING_IMPORT_USE_BROWSER:
        if blocked is not None:
            raise blocked
        return document, result

    try:
        rendered = fetch_document_rendered(url)
    except SiteBlockedError as exc:
        raise exc from blocked
    except (FetchError, UnsafeUrlError):
        if blocked is not None:
            raise blocked
        # The browser is a bonus, not a dependency. If it is down, slow, or
        # refuses the address, the plain result still stands — nothing about
        # the retry should be able to fail an import that already worked.
        logger.info("Browser retry failed for %r; keeping the plain fetch", url)
        return document, result

    rendered_result = extract_listing_data(rendered.text, rendered.url)

    if blocked is not None or result is None:
        return rendered, rendered_result

    # Only prefer the browser's version if it actually did better. A page that
    # is genuinely thin should not look richer just because it was rendered.
    if rendered_result.structured or len(rendered_result.fields) > len(result.fields):
        return rendered, rendered_result
    return document, result


def import_listing_from_html(html: str, agent, source_url: str = "") -> ImportOutcome:
    """Build a draft from HTML the agent supplied themselves.

    WHY THIS EXISTS
    ---------------
    Some listing portals refuse automated requests outright — they serve a
    challenge page to anything that is not an interactive browser. We do not
    try to look like one; that is their decision to make and working around it
    would be both a breach of their terms and a good way to get the platform's
    IP banned for every agent at once.

    What an agent *can* do is open the page themselves, in their own browser,
    as a person, and paste what they are already looking at. The parsing is
    identical to the URL path — the same extractor, the same refusal to invent
    a value — the only difference is who did the fetching.

    Photos are not downloaded here. The image URLs in pasted markup usually sit
    behind the same protection that blocked the page, so the agent uploads
    photos directly instead of watching every one fail.
    """
    return _build_from_html(html, source_url, agent, download_photos=False)


def _build_from_html(
    html: str, source_url: str, agent, *, download_photos: bool, result=None
) -> ImportOutcome:
    # `result` lets the URL path reuse the extraction it already ran while
    # deciding whether to escalate to a browser, instead of parsing twice.
    if result is None:
        result = extract_listing_data(html, source_url)

    warnings = list(result.warnings)

    with transaction.atomic():
        listing = Listing.objects.create(
            agent=agent,
            source=ListingSource.IMPORT,
            source_url=source_url[:1000],
            status=ListingStatus.DRAFT,
            # Explicit, not merely the default: an imported listing is never
            # verified, no matter how complete the extraction looked.
            verification_status=VerificationStatus.UNVERIFIED,
            imported_fields=result.extracted_fields,
            import_warnings=warnings,
            **result.fields,
        )

    photo_count = 0
    if download_photos:
        for index, photo_url in enumerate(result.photo_urls):
            try:
                if _download_photo(listing, photo_url, order=index):
                    photo_count += 1
            except (UnsafeUrlError, FetchError, DjangoValidationError) as exc:
                # One bad image must not lose the whole import.
                logger.info("Skipped imported photo %r: %s", photo_url, exc)
                warnings.append(f"A photo could not be imported: {exc}")
            except Exception:  # pragma: no cover - defensive
                logger.warning(
                    "Unexpected error importing photo %r", photo_url, exc_info=True
                )
                warnings.append("A photo could not be imported.")

        if result.photo_urls and photo_count == 0:
            warnings.append("None of the photos on the page could be imported.")
    elif result.photo_urls:
        warnings.append(
            f"{len(result.photo_urls)} photo(s) were referenced on the page but "
            "not downloaded — please upload the photos yourself."
        )

    if warnings != listing.import_warnings:
        listing.import_warnings = warnings
        listing.save(update_fields=["import_warnings", "updated_at"])

    return ImportOutcome(
        listing=listing,
        extracted_fields=result.extracted_fields,
        warnings=warnings,
        photo_count=photo_count,
    )
