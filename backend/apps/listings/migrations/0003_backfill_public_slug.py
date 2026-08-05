"""Give existing listings a public slug.

`publicly_visible()` requires a slug, so without this every listing created
before the public pages shipped would be permanently invisible — silently, and
only noticed when someone asked why their link 404s.
"""

from uuid import uuid4

from django.db import migrations
from django.utils.text import slugify


def backfill(apps, schema_editor):
    Listing = apps.get_model("listings", "Listing")

    # The historical model has no methods, so the slug is built here. Kept in
    # step with Listing._build_public_slug — if that changes, old and new rows
    # simply differ in shape, which is harmless.
    for listing in Listing.objects.filter(public_slug__isnull=True).iterator():
        base = slugify(f"{listing.address} {listing.city}")[:150] or f"listing-{listing.pk}"
        listing.public_slug = f"{base}-{uuid4().hex[:6]}".strip("-")
        listing.save(update_fields=["public_slug"])


def noop(apps, schema_editor):
    """Reversing does not clear slugs: a link that has been shared should keep
    working even if this migration is rolled back."""


class Migration(migrations.Migration):
    dependencies = [
        ("listings", "0002_listing_latitude_listing_longitude_and_more"),
    ]

    operations = [migrations.RunPython(backfill, noop)]
