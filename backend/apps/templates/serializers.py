"""Serializers for templates, designs and exports."""

from __future__ import annotations

from pathlib import PurePosixPath

from django.conf import settings
from django.template.defaultfilters import filesizeformat
from rest_framework import serializers

from apps.accounts.models import AgentProfile
from apps.core.fields import ValidatedImageField
from apps.listings.models import Listing
from apps.templates.dimensions import SOCIAL_DIMENSIONS
from apps.templates.models import (
    CalendarEvent,
    Design,
    DesignExport,
    ExportFormat,
    Template,
    TemplateCategory,
    TemplateElement,
    TemplateImport,
    TemplateStyle,
)
from apps.templates.document import elements_from_template, validate_document


class TemplateElementSerializer(serializers.ModelSerializer):
    """One element of a template, as the library preview shows it.

    Read-only, and thinner than it used to be: `permission` and
    `editable_fields` are gone with the permission model, and nothing consumes
    `constraints` any more either — a design owns its elements outright, so a
    template no longer states what may be done to them.
    """

    class Meta:
        model = TemplateElement
        fields = (
            "id",
            "key",
            "label",
            "element_type",
            "geometry",
            "style_properties",
            "content_source",
            "default_content",
            "z_index",
        )
        read_only_fields = fields


class TemplateListSerializer(serializers.ModelSerializer):
    """Compact shape for the library grid."""

    category_display = serializers.CharField(source="get_category_display", read_only=True)
    style_display = serializers.CharField(source="get_style_display", read_only=True)
    element_count = serializers.IntegerField(source="elements.count", read_only=True)
    #: Published so the library can stop asking for a listing on a Diwali card.
    requires_listing = serializers.BooleanField(read_only=True)
    is_seasonal = serializers.BooleanField(read_only=True)
    #: True for a template the viewer imported from their own artwork, false
    #: for the shared Nehrux library. The gallery uses it to badge one and to
    #: offer deleting it — a library template is not the viewer's to remove.
    is_imported = serializers.BooleanField(read_only=True)
    #: The rasterised source page, when there is one. This is the first time a
    #: template has a real picture of itself rather than a colour swatch, so
    #: the grid shows it and falls back to the swatch when it is null.
    source_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Template
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "category",
            "category_display",
            "style",
            "style_display",
            "element_count",
            "requires_listing",
            "is_seasonal",
            "is_imported",
            "source_image_url",
            "allows_added_elements",
            "default_dimension",
            "layout_definition",
        )
        read_only_fields = fields

    def get_source_image_url(self, obj: Template) -> str | None:
        if not obj.source_image:
            return None
        request = self.context.get("request")
        url = obj.source_image.url
        return request.build_absolute_uri(url) if request else url


class TemplateDetailSerializer(TemplateListSerializer):
    elements = TemplateElementSerializer(many=True, read_only=True)

    class Meta(TemplateListSerializer.Meta):
        fields = TemplateListSerializer.Meta.fields + ("elements",)
        read_only_fields = fields


#: What the importer can actually open. Sniffed from the bytes as well as the
#: extension, below — an extension is whatever the client typed.
IMPORT_EXTENSIONS = ("pdf", "png", "jpg", "jpeg", "webp")

_PDF_MAGIC = b"%PDF"


class TemplateImportCreateSerializer(serializers.Serializer):
    """The upload that starts an import.

    Validation here is about whether the file is worth spending a vision call
    on — size, extension and a content sniff. Everything about *what is in
    the design* is the extractor's problem, and cannot be known before it runs.
    """

    file = serializers.FileField(write_only=True)
    #: Optional. Blank means the extractor names the template from its own
    #: headline, which is usually a better name than "flyer-final-v3.pdf".
    name = serializers.CharField(max_length=160, required=False, allow_blank=True)
    category = serializers.ChoiceField(
        choices=TemplateCategory.choices, default=TemplateCategory.NEW_LISTING
    )
    style = serializers.ChoiceField(
        choices=TemplateStyle.choices, default=TemplateStyle.MINIMAL
    )

    def validate_file(self, value):
        limit = settings.MAX_TEMPLATE_IMPORT_BYTES
        if value.size > limit:
            raise serializers.ValidationError(
                f"That file is {filesizeformat(value.size)}. The maximum is "
                f"{filesizeformat(limit)}."
            )
        if value.size == 0:
            raise serializers.ValidationError("That file is empty.")

        extension = PurePosixPath(value.name.replace("\\", "/")).suffix.lower().lstrip(".")
        if extension not in IMPORT_EXTENSIONS:
            raise serializers.ValidationError(
                "Upload a PDF, PNG, JPG or WebP of the design."
            )

        # The bytes, not the name. A .png that is really a PDF should import
        # fine; a .png that is really a zip should not reach a worker.
        head = value.read(1024)
        value.seek(0)
        if head[:4] != _PDF_MAGIC and not _looks_like_image(value):
            raise serializers.ValidationError(
                "That file is not a readable PDF or image."
            )
        return value


def _looks_like_image(uploaded) -> bool:
    """Whether Pillow can decode this upload's header.

    ``verify()`` reads structure without decoding the whole bitmap, so a large
    photo costs almost nothing here. The file is rewound afterwards because a
    verified file object is left unusable by design.
    """
    from PIL import Image

    try:
        Image.open(uploaded).verify()
        return True
    except Exception:
        return False
    finally:
        uploaded.seek(0)


#: Fill types that mean "a person should look at this", and what to tell them.
#: Anything not listed here extracted cleanly and is not worth a warning —
#: a review list that cries wolf is one nobody reads.
_WARNING_TEXT = {
    "unsupported_pattern": (
        "The fill could not be identified — it may be a gradient, a texture or "
        "a tiling pattern. The shape is there but has no colour; set one in the "
        "editor."
    ),
    "image_texture": (
        "A photographic or textured fill, kept as a plain shape. Replace it with "
        "an image in the editor if it matters."
    ),
}


class TemplateImportSerializer(serializers.ModelSerializer):
    """One import job, as the gallery polls it.

    Carries the finished template inline on success so the client can drop the
    new card straight into the grid without a second request — the moment the
    job says "succeeded" is exactly the moment it needs the template.
    """

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    template_detail = TemplateListSerializer(source="template", read_only=True)
    is_finished = serializers.BooleanField(read_only=True)
    warnings = serializers.SerializerMethodField()

    class Meta:
        model = TemplateImport
        fields = (
            "id",
            "original_filename",
            "status",
            "status_display",
            "is_finished",
            "error",
            "warnings",
            "template",
            "template_detail",
            "element_count",
            "created_at",
            "finished_at",
        )
        read_only_fields = fields

    def get_warnings(self, job) -> list[dict]:
        """Elements the extractor could not describe with confidence.

        WHY THIS IS SURFACED RATHER THAN SWALLOWED
        --------------------------------------------------------------------
        An import that half-worked used to look exactly like one that worked:
        a shape with a fill nothing could classify was dropped or flattened to
        a guess, and the first anyone knew was noticing the flyer looked wrong
        weeks later. A silent partial failure is the expensive kind.

        So anything unclassified keeps its box and says so, and this reports
        those at the moment of upload — when the person who chose the file is
        still looking at the screen and can fix them in the editor before
        publishing to every agent.

        DERIVED, NOT STORED
        --------------------------------------------------------------------
        Read from the template's own elements rather than kept in a column on
        the job. The flag already lives in `style_properties.fill_type`, so a
        second copy would need a migration and could then disagree with the
        thing it describes — an element fixed in the editor would still be
        reported as broken.
        """
        template = job.template
        if template is None:
            return []
        warnings = [
            {
                "element": element.label or element.key,
                "issue": _WARNING_TEXT[fill_type],
                "fill_type": fill_type,
            }
            for element in template.elements.all()
            for fill_type in [str((element.style_properties or {}).get("fill_type", ""))]
            if fill_type in _WARNING_TEXT
        ]

        # A whole-page fidelity note, when the render-and-compare stage ran and
        # scored the reconstruction below the threshold. Derived, like the
        # above, from what was stored on the template rather than a second copy
        # on the job — and absent entirely when validation was off, which is the
        # default, so this adds nothing to the common import.
        fidelity = (template.layout_definition or {}).get("import_fidelity") or {}
        score = fidelity.get("score")
        threshold = getattr(settings, "TEMPLATE_IMPORT_VALIDATE_MIN_SCORE", 0.9)
        if isinstance(score, (int, float)) and score < threshold:
            warnings.append(
                {
                    "element": "",
                    "issue": (
                        "The rebuilt layout came back looking noticeably "
                        f"different from the upload (similarity {score:.0%}). "
                        "Check the positions and photos in the editor before "
                        "publishing."
                    ),
                    "fill_type": "low_fidelity",
                }
            )
        return warnings


class CalendarEventSerializer(serializers.ModelSerializer):
    """One dated occasion, with the templates that suit it."""

    category_display = serializers.CharField(source="get_category_display", read_only=True)
    days_away = serializers.IntegerField(read_only=True)
    is_past = serializers.BooleanField(read_only=True)
    template_count = serializers.SerializerMethodField()

    class Meta:
        model = CalendarEvent
        fields = (
            "id",
            "name",
            "slug",
            "category",
            "category_display",
            "date",
            "days_away",
            "is_past",
            "description",
            "regions",
            "needs_date_review",
            "template_count",
        )
        read_only_fields = fields

    def get_template_count(self, obj: CalendarEvent) -> int:
        counts = self.context.get("template_counts")
        if counts is not None:
            return counts.get(obj.category, 0)
        return Template.objects.filter(category=obj.category, is_active=True).count()


class DesignExportSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    dimension_label = serializers.SerializerMethodField()

    class Meta:
        model = DesignExport
        fields = (
            "id",
            "design",
            "dimension",
            "dimension_label",
            "export_format",
            "image_url",
            "width",
            "height",
            "bytes",
            "render_ms",
            "created_at",
        )
        read_only_fields = fields

    def get_image_url(self, obj: DesignExport) -> str | None:
        if not obj.image:
            return None
        request = self.context.get("request")
        url = obj.image.url
        return request.build_absolute_uri(url) if request else url

    def get_dimension_label(self, obj: DesignExport) -> str:
        dimension = SOCIAL_DIMENSIONS.get(obj.dimension)
        return dimension.label if dimension else obj.dimension


class DesignSerializer(serializers.ModelSerializer):
    template_detail = TemplateListSerializer(source="template", read_only=True)
    exports = DesignExportSerializer(many=True, read_only=True)
    listing_address = serializers.CharField(source="listing.full_address", read_only=True)

    #: "Yes, I really do want a second one." See `create` for why the default
    #: is the opposite, and why this lives on the server rather than being a
    #: rule each screen remembers to follow.
    fresh = serializers.BooleanField(write_only=True, required=False, default=False)

    #: Set by `create` when it handed back a design that already existed, so
    #: the viewset can answer 200 rather than claiming it made something.
    reused_existing = False

    class Meta:
        model = Design
        fields = (
            "id",
            "name",
            "template",
            "template_detail",
            "agent",
            "listing",
            "listing_address",
            "calendar_event",
            "elements",
            "exports",
            "fresh",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "template_detail",
            "listing_address",
            "exports",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {"agent": {"required": False}}

    def validate_listing(self, value: Listing | None) -> Listing | None:
        """A design may only be built on a verified listing.

        This is the Step 4 gate being honoured: verification exists so that
        nothing downstream renders unreviewed data onto marketing material.
        """
        if value is None:
            return value

        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            raise serializers.ValidationError("Authentication required.")

        if not Listing.objects.for_user(user).filter(pk=value.pk).exists():
            raise serializers.ValidationError("No such listing.")

        if not value.is_usable_for_content:
            raise serializers.ValidationError(
                "This listing has not been verified yet. Review and confirm its "
                "details before using it in a design."
            )
        return value

    def validate_template(self, value: Template) -> Template:
        """A design may only be built on a template the caller can see.

        Without this, a template id guessed or remembered from another account
        would open someone else's imported artwork — the design copies its
        elements outright, so it would be handed over wholesale.
        """
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            raise serializers.ValidationError("Authentication required.")
        if not Template.objects.visible_to(user).filter(pk=value.pk).exists():
            raise serializers.ValidationError("No such template.")
        return value

    def validate_agent(self, value: AgentProfile) -> AgentProfile:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            raise serializers.ValidationError("Authentication required.")
        if user.is_nehrux_admin:
            return value
        if user.is_brokerage_admin:
            if not user.administered_brokerages.filter(pk=value.brokerage_id or 0).exists():
                raise serializers.ValidationError(
                    "That agent is not part of a brokerage you administer."
                )
            return value
        if value.user_id != user.id:
            raise serializers.ValidationError("You can only create designs for yourself.")
        return value

    def validate(self, attrs: dict) -> dict:
        # The template may be arriving in this same request, so resolve it from
        # the payload first and only then fall back to the stored instance.
        template = attrs.get("template") or getattr(self.instance, "template", None)
        if template is None:
            raise serializers.ValidationError({"template": "A template is required."})

        # A property template no longer demands its property up front.
        #
        # It used to: creating a "Just Sold" without a listing was refused
        # here. That forced the choice of property to happen in the gallery,
        # before the agent had seen the design — so the library defaulted it to
        # their most recent listing, and every template they opened silently
        # became about that property whether they meant it or not.
        #
        # The requirement has not been dropped, it has moved to the moment it
        # is actually real. `readiness.assess_design` refuses to export any
        # design whose bound elements resolve to nothing, names the empty
        # fields, and links to the listing screen — so an empty flyer still
        # cannot reach a client, and an agent can lay one out before deciding
        # which property it is for.

        # The whole canvas arrives in one autosave and is re-checked in full.
        # Not for permission — there is none — but because every value here is
        # about to be interpolated into HTML and handed to a real browser. See
        # document.validate_document.
        if "elements" in attrs:
            attrs["elements"] = validate_document(attrs["elements"])
        elif self.instance is not None and attrs.get("template") not in (
            None,
            self.instance.template,
        ):
            # Switching template replaces the canvas: the old elements were
            # copied from a template this design no longer uses.
            attrs["elements"] = elements_from_template(attrs["template"])

        return attrs

    def create(self, validated_data: dict) -> Design:
        fresh = validated_data.pop("fresh", False)

        if not validated_data.get("agent"):
            request = self.context.get("request")
            profile = AgentProfile.objects.filter(user=request.user).first()
            if profile is None:
                raise serializers.ValidationError(
                    {"agent": "You need an agent profile before creating designs."}
                )
            validated_data["agent"] = profile

        # ONE DESIGN PER TEMPLATE, UNLESS A SECOND IS ASKED FOR.
        #
        # Opening a template you have already customised resumes that design
        # rather than starting another. Without this, every visit to a template
        # left a new row: an agent who opened "Just Listed" on three days had
        # three near-identical designs and no way to tell which held the edits
        # they actually made.
        #
        # This is enforced here, and not in the screens that open templates,
        # because there are four of them — the gallery, the content calendar,
        # the editor's own template picker, and anything added later. Three of
        # the four had the bug; a rule each screen has to remember is a rule
        # that gets forgotten, so the endpoint keeps it instead.
        #
        # `calendar_event` is part of the identity: Diwali 2026 and Diwali 2027
        # are different events on the same seasonal template, and collapsing
        # them would make this year's post overwrite last year's. Everything
        # else — the listing especially — is not, because attaching a property
        # is something you do to a design *after* opening it.
        #
        # Deliberate copies are untouched: `fresh=true` is the "Start a fresh
        # copy" button, and Duplicate / Add variation are a different endpoint
        # entirely.
        if not fresh:
            existing = (
                Design.objects.filter(
                    agent=validated_data["agent"],
                    template=validated_data["template"],
                    calendar_event=validated_data.get("calendar_event"),
                )
                .order_by("-updated_at")
                .first()
            )
            if existing is not None:
                self.reused_existing = True
                return existing

        # THE COPY. Opening a template for editing gives the agent their own
        # elements, there and then — not a reference to the template's, and not
        # an empty canvas to be filled in lazily on first edit. Everything
        # after this point mutates the design; the Template is never written to
        # again by anything an agent can reach.
        if not validated_data.get("elements"):
            validated_data["elements"] = elements_from_template(
                validated_data["template"]
            )
        return super().create(validated_data)


class DesignRenameSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)


class DesignDuplicateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160, required=False, allow_blank=True)


class DesignImageUploadSerializer(serializers.Serializer):
    """Input for uploading an image to use as an element's content — the
    "upload a new one" half of image replace, alongside picking a listing
    photo.

    Deliberately not tied to any model: the file is written straight through
    the storage API (see the view) and only the resulting key is kept, which
    is exactly what an image element's `content` holds. Nothing here creates a
    row an agent would need to separately clean up.
    """

    image = ValidatedImageField(write_only=True)


class DesignExportRequestSerializer(serializers.Serializer):
    """Ask for one design at one or more social dimensions."""

    dimensions = serializers.ListField(
        child=serializers.ChoiceField(choices=sorted(SOCIAL_DIMENSIONS)),
        allow_empty=False,
        max_length=len(SOCIAL_DIMENSIONS),
    )
    export_format = serializers.ChoiceField(
        choices=ExportFormat.choices, default=ExportFormat.PNG
    )

    def validate_dimensions(self, value: list[str]) -> list[str]:
        # Preserve order, drop duplicates: asking for the same size twice is a
        # client slip, not a reason to render it twice.
        seen = []
        for item in value:
            if item not in seen:
                seen.append(item)
        return seen
