"""Serializers for templates, designs and exports."""

from __future__ import annotations

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
    TemplateElement,
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
            "allows_added_elements",
            "default_dimension",
            "layout_definition",
        )
        read_only_fields = fields


class TemplateDetailSerializer(TemplateListSerializer):
    elements = TemplateElementSerializer(many=True, read_only=True)

    class Meta(TemplateListSerializer.Meta):
        fields = TemplateListSerializer.Meta.fields + ("elements",)
        read_only_fields = fields


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

        # A seasonal template needs no property; a "Just Sold" one is
        # meaningless without it and would render with empty fields.
        listing = attrs.get("listing", getattr(self.instance, "listing", None))
        if template.requires_listing and listing is None:
            raise serializers.ValidationError(
                {
                    "listing": (
                        f"“{template.name}” describes a specific property, so it "
                        f"needs a listing."
                    )
                }
            )

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
        if not validated_data.get("agent"):
            request = self.context.get("request")
            profile = AgentProfile.objects.filter(user=request.user).first()
            if profile is None:
                raise serializers.ValidationError(
                    {"agent": "You need an agent profile before creating designs."}
                )
            validated_data["agent"] = profile

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
