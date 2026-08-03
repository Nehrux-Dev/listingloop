"""File upload tests: validation, storage keys, and cleanup.

Every test runs against a throwaway MEDIA_ROOT, so nothing touches the real
media directory.

The validation tests matter more than the happy path. An upload endpoint that
accepts whatever the client sends is a file-drop into your infrastructure, and
neither the filename nor the Content-Type header is evidence of anything —
both are supplied by the caller.
"""

from __future__ import annotations

import shutil
import tempfile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.accounts.models import AgentProfile, Brokerage
from apps.accounts.tests.base import AuthAPITestCase, make_image_file
from apps.core.validators import ImageUploadValidator

MEDIA_ROOT = tempfile.mkdtemp(prefix="real-estate-test-media-")


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class UploadTestCase(AuthAPITestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()


class AgentPhotoUploadTests(UploadTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.broker_admin = self.make_brokerage_admin("admin.acme@example.com")
        self.acme = self.make_brokerage("Acme Realty", self.broker_admin)
        self.agent, self.profile = self.make_agent_in(self.acme, "a1@example.com")
        self.authenticate_as(self.agent)

    # -- happy path ---------------------------------------------------------

    def test_agent_can_upload_a_photo(self):
        response = self.client.patch(
            self.agent_me_url,
            {"photo": make_image_file("headshot.png")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.photo)
        self.assertTrue(response.data["photo_url"].startswith("http"))

    def test_stored_key_is_namespaced_and_randomised(self):
        """The client's filename never becomes the storage key."""
        self.client.patch(
            self.agent_me_url,
            {"photo": make_image_file("my holiday photo (1).png")},
            format="multipart",
        )

        self.profile.refresh_from_db()
        name = self.profile.photo.name

        self.assertTrue(name.startswith("agents/photos/"))
        self.assertTrue(name.endswith(".png"))
        self.assertNotIn("holiday", name)
        self.assertNotIn(" ", name)

    def test_jpeg_and_webp_are_accepted(self):
        for filename, image_format in [("a.jpg", "JPEG"), ("b.webp", "WEBP")]:
            with self.subTest(format=image_format):
                response = self.client.patch(
                    self.agent_me_url,
                    {"photo": make_image_file(filename, image_format)},
                    format="multipart",
                )
                self.assertEqual(response.status_code, 200, response.data)

    # -- rejections ---------------------------------------------------------

    def test_non_image_content_is_rejected(self):
        """A text file renamed .png: plausible name, plausible content type."""
        disguised = SimpleUploadedFile(
            "payload.png", b"#!/bin/sh\nrm -rf /\n", content_type="image/png"
        )

        response = self.client.patch(
            self.agent_me_url, {"photo": disguised}, format="multipart"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("photo", response.data)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.photo)

    def test_disallowed_extension_is_rejected(self):
        text_file = SimpleUploadedFile(
            "notes.txt", b"just some text", content_type="text/plain"
        )

        response = self.client.patch(
            self.agent_me_url, {"photo": text_file}, format="multipart"
        )

        self.assertEqual(response.status_code, 400)

    def test_valid_image_with_disallowed_extension_is_rejected(self):
        """A real GIF: decodes fine, but GIF is not on the allowlist.

        This is the case that exercises the extension check specifically —
        a .txt full of text is rejected earlier, by the image decode, so it
        cannot prove the allowlist is wired up.
        """
        response = self.client.patch(
            self.agent_me_url,
            {"photo": make_image_file("anim.gif", "GIF")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("not allowed", str(response.data["photo"][0]).lower())

    def test_svg_is_rejected(self):
        """SVG can carry script; it is not in the allowlist."""
        svg = SimpleUploadedFile(
            "logo.svg",
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            content_type="image/svg+xml",
        )

        response = self.client.patch(
            self.agent_me_url, {"photo": svg}, format="multipart"
        )

        self.assertEqual(response.status_code, 400)

    @override_settings(MAX_IMAGE_UPLOAD_BYTES=1024)
    def test_oversized_file_is_rejected(self):
        """A genuine image, over the configured limit."""
        big_image = make_image_file("large.png", size=(400, 400))
        self.assertGreater(big_image.size, 1024)

        response = self.client.patch(
            self.agent_me_url, {"photo": big_image}, format="multipart"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("too large", str(response.data["photo"][0]).lower())
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.photo)

    def test_oversized_file_is_rejected_at_the_default_limit(self):
        """Exercises the real configured ceiling, not an overridden one.

        The assertion checks the *message*, not just the status: a junk file
        over the limit is rejected by two different rules, and a bare
        assertEqual(400) would pass even if the size check never ran.
        """
        oversized = SimpleUploadedFile(
            "huge.png", b"\x00" * (6 * 1024 * 1024), content_type="image/png"
        )

        response = self.client.patch(
            self.agent_me_url, {"photo": oversized}, format="multipart"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("too large", str(response.data["photo"][0]).lower())

    def test_size_is_checked_before_the_image_is_decoded(self):
        """A genuine but oversized image reports size, not 'invalid image'."""
        genuine_but_huge = make_image_file("wall.png", size=(64, 64))

        with override_settings(MAX_IMAGE_UPLOAD_BYTES=10):
            response = self.client.patch(
                self.agent_me_url, {"photo": genuine_but_huge}, format="multipart"
            )

        self.assertEqual(response.status_code, 400)
        message = str(response.data["photo"][0]).lower()
        self.assertIn("too large", message)
        self.assertNotIn("not an image", message)

    def test_empty_file_is_rejected(self):
        empty = SimpleUploadedFile("empty.png", b"", content_type="image/png")

        response = self.client.patch(
            self.agent_me_url, {"photo": empty}, format="multipart"
        )

        self.assertEqual(response.status_code, 400)

    def test_extension_must_match_actual_content(self):
        """A real JPEG named .png — valid image, misleading key."""
        jpeg_bytes = make_image_file("real.jpg", "JPEG").read()
        mislabelled = SimpleUploadedFile(
            "actually_a_jpeg.png", jpeg_bytes, content_type="image/png"
        )

        response = self.client.patch(
            self.agent_me_url, {"photo": mislabelled}, format="multipart"
        )

        self.assertEqual(response.status_code, 400)

    # -- replacement / cleanup ---------------------------------------------

    def test_replacing_a_photo_deletes_the_previous_file(self):
        self.client.patch(
            self.agent_me_url,
            {"photo": make_image_file("first.png")},
            format="multipart",
        )
        self.profile.refresh_from_db()
        first_name = self.profile.photo.name
        storage = self.profile.photo.storage
        self.assertTrue(storage.exists(first_name))

        self.client.patch(
            self.agent_me_url,
            {"photo": make_image_file("second.png")},
            format="multipart",
        )
        self.profile.refresh_from_db()

        self.assertNotEqual(self.profile.photo.name, first_name)
        # Checked through the storage API, so this test would hold for S3 too.
        self.assertFalse(storage.exists(first_name))
        self.assertTrue(storage.exists(self.profile.photo.name))

    def test_deleting_a_profile_deletes_its_photo(self):
        self.client.patch(
            self.agent_me_url,
            {"photo": make_image_file("gone.png")},
            format="multipart",
        )
        self.profile.refresh_from_db()
        name, storage = self.profile.photo.name, self.profile.photo.storage

        self.authenticate_as(self.broker_admin)
        self.client.delete(self.agent_detail_url(self.profile))

        self.assertFalse(AgentProfile.objects.filter(pk=self.profile.pk).exists())
        self.assertFalse(storage.exists(name))


class BrokerageLogoUploadTests(UploadTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.broker_admin = self.make_brokerage_admin("admin.acme@example.com")
        self.acme = self.make_brokerage("Acme Realty", self.broker_admin)
        self.agent, self.profile = self.make_agent_in(self.acme, "a1@example.com")

    def test_brokerage_admin_can_upload_a_logo(self):
        self.authenticate_as(self.broker_admin)

        response = self.client.patch(
            self.brokerage_detail_url(self.acme),
            {"logo": make_image_file("logo.png")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.acme.refresh_from_db()
        self.assertTrue(self.acme.logo.name.startswith("brokerages/logos/"))

    def test_agent_cannot_upload_a_logo_to_their_brokerage(self):
        self.authenticate_as(self.agent)

        response = self.client.patch(
            self.brokerage_detail_url(self.acme),
            {"logo": make_image_file("logo.png")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 403)
        self.acme.refresh_from_db()
        self.assertFalse(self.acme.logo)

    def test_invalid_logo_is_rejected(self):
        self.authenticate_as(self.broker_admin)

        response = self.client.patch(
            self.brokerage_detail_url(self.acme),
            {"logo": SimpleUploadedFile("logo.png", b"nope", content_type="image/png")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)


class ValidatorUnitTests(UploadTestCase):
    """The validator on its own, independent of any storage backend."""

    def test_accepts_a_valid_image(self):
        ImageUploadValidator()(make_image_file("ok.png"))

    def test_rejects_by_size_before_reading_content(self):
        validator = ImageUploadValidator(max_bytes=10)

        with self.assertRaises(ValidationError) as ctx:
            validator(make_image_file("big.png"))

        self.assertEqual(ctx.exception.code, "file_too_large")

    def test_rejects_unknown_extension(self):
        validator = ImageUploadValidator()
        gif = SimpleUploadedFile("animation.gif", b"GIF89a", content_type="image/gif")

        with self.assertRaises(ValidationError) as ctx:
            validator(gif)

        self.assertEqual(ctx.exception.code, "invalid_extension")

    def test_rejects_corrupt_image(self):
        validator = ImageUploadValidator()
        corrupt = SimpleUploadedFile("x.png", b"\x89PNG\r\n\x1a\n garbage")

        with self.assertRaises(ValidationError) as ctx:
            validator(corrupt)

        self.assertEqual(ctx.exception.code, "invalid_image")

    def test_leaves_the_file_pointer_at_the_start(self):
        """Django still has to read the file to save it after validation."""
        image = make_image_file("ok.png")

        ImageUploadValidator()(image)

        self.assertEqual(image.tell(), 0)
        self.assertTrue(image.read())

    def test_limit_is_read_from_settings_at_call_time(self):
        """So changing MAX_IMAGE_UPLOAD_MB does not require a migration."""
        validator = ImageUploadValidator()

        with override_settings(MAX_IMAGE_UPLOAD_BYTES=1):
            self.assertEqual(validator.limit, 1)
        with override_settings(MAX_IMAGE_UPLOAD_BYTES=999):
            self.assertEqual(validator.limit, 999)

    def test_is_deconstructible_for_migrations(self):
        path, args, kwargs = ImageUploadValidator().deconstruct()

        self.assertEqual(path, "apps.core.validators.ImageUploadValidator")
        self.assertEqual(ImageUploadValidator(*args, **kwargs), ImageUploadValidator())


class StorageIndirectionTests(UploadTestCase):
    """The model must not care which backend is configured."""

    def test_files_are_written_through_the_configured_storage_backend(self):
        brokerage = Brokerage.objects.create(name="Storage Co")
        brokerage.logo.save("logo.png", make_image_file("logo.png"), save=True)

        storage = brokerage.logo.storage

        # No filesystem paths anywhere: existence, URL and deletion all go
        # through the storage API, which is what makes the backend swappable.
        self.assertTrue(storage.exists(brokerage.logo.name))
        self.assertTrue(brokerage.logo.url.endswith(brokerage.logo.name))
        self.assertNotIn("\\", brokerage.logo.name)
