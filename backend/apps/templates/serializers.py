"""Serializers for templates, designs and exports."""

from __future__ import annotations

from rest_framework import serializers

from apps.accounts.models import AgentProfile
from apps.listings.models import Listing
from apps.templates.dimensions import SOCIAL_DIMENSIONS
from apps.templates.models import (
    Design,
    DesignExport,
    ExportFormat,
    Template,
    TemplateElement,
)
from apps.templates.overrides import validate_overrides


class TemplateElementSerializer(serializers.ModelSerializer):
    """An element and, crucially, what may be done to it.

    ``permission`` and ``constraints`` are part of the public payload so the
    editor can build the right controls. They are also re-checked on every
    write — the client is being told the rules, not trusted to apply them.
    """

    editable_fields = serializers.SerializerMethodField()

    class Meta:
        model = TemplateElement
        fields = (
            "id",
            "key",
            "label",
            "element_type",
            "permission",
            "editable_fields",
            "geometry",
            "style_properties",
            "constraints",
            "content_source",
            "default_content",
            "z_index",
        )
        read_only_fields = fields

    def get_editable_fields(self, obj: TemplateElement) -> list[str]:
        from apps.templates.overrides import ALLOWED_FIELDS

        return sorted(ALLOWED_FIELDS.get(obj.permission, frozenset()))


class TemplateListSerializer(serializers.ModelSerializer):
    """Compact shape for the library grid."""

    category_display = serializers.CharField(source="get_category_display", read_only=True)
    style_display = serializers.CharField(source="get_style_display", read_only=True)
    element_count = serializers.IntegerField(source="elements.count", read_only=True)

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
            "layout_definition",
        )
        read_only_fields = fields


class TemplateDetailSerializer(TemplateListSerializer):
    elements = TemplateElementSerializer(many=True, read_only=True)
    permission_map = serializers.SerializerMethodField()

    class Meta(TemplateListSerializer.Meta):
        fields = TemplateListSerializer.Meta.fields + ("elements", "permission_map")
        read_only_fields = fields

    def get_permission_map(self, obj: Template) -> dict[str, str]:
        return obj.permission_map


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
            "overrides",
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
        # Overrides are validated against the template's permission map. The
        # template may be arriving in this same request, so resolve it from the
        # payload first and only then fall back to the stored instance.
        template = attrs.get("template") or getattr(self.instance, "template", None)
        if template is None:
            raise serializers.ValidationError({"template": "A template is required."})

        if "overrides" in attrs:
            attrs["overrides"] = validate_overrides(template, attrs["overrides"])
        elif self.instance is not None and attrs.get("template") not in (None, self.instance.template):
            # Switching template invalidates overrides keyed to the old one.
            attrs["overrides"] = {}

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
        return super().create(validated_data)


class DesignRenameSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)


class DesignDuplicateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160, required=False, allow_blank=True)


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
