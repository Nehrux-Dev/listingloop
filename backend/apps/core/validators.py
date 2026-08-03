"""Upload validation.

These validators run at the *model* layer, so they apply to every write path —
the REST API, the Django admin, a management command, a data migration — and
they are independent of which storage backend is configured. Swapping
FileSystemStorage for S3 changes where bytes land, not what is allowed in.

Three checks, cheapest first:

  1. Size      — rejected before anything reads the content.
  2. Extension — an allowlist, never a denylist.
  3. Content   — the file is decoded as an image and its *real* format is
                 compared against the allowlist.

Step 3 is the one that matters. Extension and Content-Type are both supplied
by the client and can say anything; only decoding the bytes proves what the
file actually is. It is what stops `payload.php` renamed to `photo.png`.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from django.conf import settings
from django.core.exceptions import ValidationError
from django.template.defaultfilters import filesizeformat
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _
from PIL import Image, UnidentifiedImageError

#: Extension -> the format name Pillow reports for it.
IMAGE_FORMATS: dict[str, str] = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
}


@deconstructible
class ImageUploadValidator:
    """Validate that an upload is a real image, of an allowed type and size.

    ``@deconstructible`` lets Django serialise an instance of this class into a
    migration, so the constraint travels with the field definition.
    """

    def __init__(
        self,
        max_bytes: int | None = None,
        allowed_extensions: tuple[str, ...] = ("jpg", "jpeg", "png", "webp"),
    ) -> None:
        # Left as None so the limit is read from settings at validation time.
        # Baking the number in would freeze the current MAX_IMAGE_UPLOAD_MB
        # into a migration and make the env variable a lie.
        self.max_bytes = max_bytes
        self.allowed_extensions = tuple(ext.lower() for ext in allowed_extensions)

    @property
    def limit(self) -> int:
        return self.max_bytes or settings.MAX_IMAGE_UPLOAD_BYTES

    @property
    def allowed_formats(self) -> set[str]:
        return {IMAGE_FORMATS[ext] for ext in self.allowed_extensions if ext in IMAGE_FORMATS}

    def __call__(self, file) -> None:
        self._check_size(file)
        extension = self._check_extension(file)
        self._check_content(file, extension)

    # -- individual checks --------------------------------------------------

    def _check_size(self, file) -> None:
        size = getattr(file, "size", None)
        if size is None:
            return
        if size > self.limit:
            raise ValidationError(
                _("File is too large (%(size)s). The maximum size is %(limit)s."),
                code="file_too_large",
                params={
                    "size": filesizeformat(size),
                    "limit": filesizeformat(self.limit),
                },
            )
        if size == 0:
            raise ValidationError(_("The uploaded file is empty."), code="file_empty")

    def _check_extension(self, file) -> str:
        name = getattr(file, "name", "") or ""
        extension = PurePosixPath(name.replace("\\", "/")).suffix.lower().lstrip(".")

        if extension not in self.allowed_extensions:
            raise ValidationError(
                _("%(ext)s files are not allowed. Allowed types: %(allowed)s."),
                code="invalid_extension",
                params={
                    "ext": f".{extension}" if extension else "Extensionless",
                    "allowed": ", ".join(f".{ext}" for ext in self.allowed_extensions),
                },
            )
        return extension

    def _check_content(self, file, extension: str) -> None:
        """Decode the bytes and confirm the real format matches the extension.

        A renamed executable has a valid-looking name and may even carry an
        `image/png` Content-Type, but it will not decode — this is the check
        that catches it.
        """
        position = file.tell() if hasattr(file, "tell") else None
        try:
            file.seek(0)
            with Image.open(file) as image:
                # verify() parses the header and checks structural integrity
                # without decoding every pixel, so a huge file cannot be used
                # to burn memory here.
                image.verify()
                detected = (image.format or "").upper()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValidationError(
                _("This file is not a valid image."), code="invalid_image"
            ) from exc
        finally:
            # Leave the pointer where the caller expects it — Django still has
            # to read the file to save it.
            if hasattr(file, "seek"):
                file.seek(position or 0)

        if detected not in self.allowed_formats:
            raise ValidationError(
                _("Unsupported image format %(format)s. Allowed: %(allowed)s."),
                code="unsupported_format",
                params={
                    "format": detected or "unknown",
                    "allowed": ", ".join(sorted(self.allowed_formats)),
                },
            )

        # Catch a real image whose extension lies (a JPEG named .png). Harmless
        # in itself, but it means the stored key would advertise the wrong type.
        expected = IMAGE_FORMATS.get(extension)
        if expected and detected != expected:
            raise ValidationError(
                _(
                    "File content (%(detected)s) does not match its .%(ext)s "
                    "extension."
                ),
                code="extension_mismatch",
                params={"detected": detected, "ext": extension},
            )

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, ImageUploadValidator)
            and self.max_bytes == other.max_bytes
            and self.allowed_extensions == other.allowed_extensions
        )
