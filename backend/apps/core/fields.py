"""Serializer fields for uploads."""

from __future__ import annotations

from django.conf import settings
from django.template.defaultfilters import filesizeformat
from rest_framework import serializers

from apps.core.validators import ImageUploadValidator


class ValidatedImageField(serializers.ImageField):
    """An image field that checks size *before* decoding the file.

    DRF's ``ImageField`` runs Pillow over the upload inside
    ``to_internal_value``, which happens before any validator attached to the
    model field. That ordering has two costs:

      * a 500 MB upload gets fully parsed before anything says "too large",
      * the caller is told "not a valid image" when the real problem is the
        size, which is confusing and hard to act on.

    Checking the cheap, unambiguous condition first fixes both.

    The field also attaches ``ImageUploadValidator`` itself. That is not
    belt-and-braces: declaring a field explicitly on a ModelSerializer means
    DRF no longer copies the *model* field's validators onto it, so the
    extension allowlist and format checks would silently stop running at the
    API layer. Defaulting them here makes that impossible to forget.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("validators", [ImageUploadValidator()])
        super().__init__(*args, **kwargs)

    def to_internal_value(self, data):
        size = getattr(data, "size", None)
        limit = settings.MAX_IMAGE_UPLOAD_BYTES

        if size is not None and size > limit:
            raise serializers.ValidationError(
                f"File is too large ({filesizeformat(size)}). "
                f"The maximum size is {filesizeformat(limit)}.",
                code="file_too_large",
            )

        return super().to_internal_value(data)
