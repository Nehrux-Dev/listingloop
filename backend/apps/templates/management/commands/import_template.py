"""Import artwork into a template from the command line.

WHY THIS EXISTS ALONGSIDE THE API
=============================================================================
The API endpoint is how an agent imports a design: upload, queue, poll. This
command is the same pipeline with two things the endpoint cannot offer.

**A spec instead of a vision call.** ``--spec`` takes a JSON file in exactly
the shape the model would have returned, and skips the provider entirely. That
matters for three real cases:

  * seeding a template into the library deterministically, so the same artwork
    produces the same geometry on every environment rather than whatever the
    model said that morning;
  * correcting an import — dump what came back, fix the eight boxes that were
    wrong, re-run, pay nothing;
  * developing and testing the pipeline with no API key configured at all.

**Ownership.** ``--owner`` attaches the result to one agent; omitting it
creates a *library* template, visible to everyone, which is a thing no agent
should be able to do through the API.

    python manage.py import_template --file flyer.pdf --spec flyer.json \\
        --name "Find Comfort" --category new_listing --style bold

    python manage.py import_template --file flyer.pdf --owner agent@example.com
"""

from __future__ import annotations

import json

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import AgentProfile
from apps.templates.importing import (
    TemplateImportError,
    bake_assets,
    build_template,
    extract_layout,
    normalise_elements,
    rasterise,
)
from apps.templates.models import Template, TemplateCategory, TemplateStyle


class Command(BaseCommand):
    help = "Import a PDF or image into an editable template."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="PDF or image to import.")
        parser.add_argument(
            "--spec",
            help=(
                "JSON layout to use instead of calling the vision model. Same "
                "shape as the model's response: {page: {...}, elements: [...]}."
            ),
        )
        parser.add_argument("--name", default="", help="Template name.")
        parser.add_argument(
            "--category", default=TemplateCategory.NEW_LISTING,
            choices=TemplateCategory.values,
        )
        parser.add_argument(
            "--style", default=TemplateStyle.MINIMAL, choices=TemplateStyle.values
        )
        parser.add_argument(
            "--owner",
            help=(
                "Email of the agent who owns this. Omit to create a shared "
                "library template that every agent can see."
            ),
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Delete any existing template with the same name first.",
        )

    def handle(self, *args, **options):
        source = Path(options["file"])
        if not source.exists():
            raise CommandError(f"No such file: {source}")

        owner = None
        if options["owner"]:
            owner = AgentProfile.objects.filter(user__email=options["owner"]).first()
            if owner is None:
                raise CommandError(f"No agent profile for {options['owner']!r}.")

        try:
            page = rasterise(source.read_bytes(), source.name)
        except TemplateImportError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"rasterised {source.name} at {page.width}x{page.height}")

        if options["spec"]:
            spec_path = Path(options["spec"])
            if not spec_path.exists():
                raise CommandError(f"No such spec: {spec_path}")
            payload = json.loads(spec_path.read_text(encoding="utf-8"))
            self.stdout.write(self.style.WARNING("using --spec; no vision call made"))
        else:
            try:
                result = extract_layout(page)
            except TemplateImportError as exc:
                raise CommandError(str(exc)) from exc
            payload = result.payload
            self.stdout.write(
                f"extracted with {result.model} in {result.duration_ms}ms "
                f"({result.prompt_tokens}+{result.completion_tokens} tokens)"
            )

        try:
            elements = normalise_elements(payload, page)
        except TemplateImportError as exc:
            raise CommandError(str(exc)) from exc

        baked = bake_assets(elements, page)
        self.stdout.write(f"{len(elements)} elements, {baked} with artwork extracted")

        name = options["name"] or payload.get("page", {}).get("suggested_name") or source.stem

        if options["replace"]:
            # Scoped to the same owner: two agents may legitimately hold a
            # template of the same name, and replacing one must not touch the
            # other's.
            removed, _ = Template.objects.filter(name=name, owner=owner).delete()
            if removed:
                self.stdout.write(self.style.WARNING(f"replaced existing {name!r}"))

        template = build_template(
            owner=owner,
            name=name,
            category=options["category"],
            style=options["style"],
            page=page,
            elements=elements,
            payload=payload,
            description=(
                f"Imported from {source.name}. Every element is editable — "
                f"attach a listing to fill the photos and details with a real "
                f"property."
            ),
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"created template {template.pk}: {template.name} "
                f"({template.elements.count()} elements, opens at "
                f"{template.default_dimension}, "
                f"{'owned by ' + options['owner'] if owner else 'shared library'})"
            )
        )
