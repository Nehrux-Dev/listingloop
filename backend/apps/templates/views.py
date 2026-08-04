"""Template library and design endpoints.

    /api/templates/                 browse the library (read-only, filterable)
    /api/templates/facets/          category and style options for the filters
    /api/designs/                   CRUD
    /api/designs/{id}/duplicate/    copy
    /api/designs/{id}/rename/       rename
    /api/designs/{id}/preview/      render without saving an export
    /api/designs/{id}/export/       render and save, one or more dimensions
    /api/design-exports/            saved exports
    /api/render-dimensions/         the supported social sizes
"""

from __future__ import annotations

import logging

from django.db.models import QuerySet
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.templates.dimensions import DEFAULT_DIMENSION, SOCIAL_DIMENSIONS, get_dimension
from apps.templates.html_builder import describe_design
from apps.templates.models import (
    Design,
    DesignExport,
    ExportFormat,
    Template,
    TemplateCategory,
    TemplateStyle,
)
from apps.templates.permissions import DesignPermission
from apps.templates.render_context import build_context
from apps.templates.rendering import export_design_bundle, render_design
from apps.templates.serializers import (
    DesignDuplicateSerializer,
    DesignExportRequestSerializer,
    DesignExportSerializer,
    DesignRenameSerializer,
    DesignSerializer,
    TemplateDetailSerializer,
    TemplateListSerializer,
)

logger = logging.getLogger(__name__)


class TemplateViewSet(viewsets.ReadOnlyModelViewSet):
    """The template library.

    Read-only over the API: templates are product content, authored by Nehrux
    through the Django admin. Agents choose from them, they do not edit them —
    which is what makes the permission map meaningful.
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[Template]:
        queryset = Template.objects.filter(is_active=True).prefetch_related("elements")

        params = self.request.query_params
        category = params.get("category")
        if category in TemplateCategory.values:
            queryset = queryset.filter(category=category)

        style = params.get("style")
        if style in TemplateStyle.values:
            queryset = queryset.filter(style=style)

        search = params.get("search")
        if search:
            queryset = queryset.filter(name__icontains=search)

        return queryset

    def get_serializer_class(self):
        return (
            TemplateDetailSerializer
            if self.action == "retrieve"
            else TemplateListSerializer
        )

    @action(detail=False, methods=["get"], url_path="facets")
    def facets(self, request: Request) -> Response:
        """Filter options, with counts, so the UI need not hardcode them."""
        active = Template.objects.filter(is_active=True)
        return Response(
            {
                "categories": [
                    {
                        "value": value,
                        "label": label,
                        "count": active.filter(category=value).count(),
                    }
                    for value, label in TemplateCategory.choices
                ],
                "styles": [
                    {
                        "value": value,
                        "label": label,
                        "count": active.filter(style=value).count(),
                    }
                    for value, label in TemplateStyle.choices
                ],
            }
        )


class DesignViewSet(viewsets.ModelViewSet):
    """Saved designs, scoped like listings: own work, or the brokerage's."""

    serializer_class = DesignSerializer
    permission_classes = [IsAuthenticated, DesignPermission]

    def get_queryset(self) -> QuerySet[Design]:
        queryset = (
            Design.objects.for_user(self.request.user)
            .select_related("template", "agent", "agent__brokerage", "listing")
            .prefetch_related("template__elements", "exports")
        )

        template_id = self.request.query_params.get("template")
        if template_id and template_id.isdigit():
            queryset = queryset.filter(template_id=int(template_id))

        listing_id = self.request.query_params.get("listing")
        if listing_id and listing_id.isdigit():
            queryset = queryset.filter(listing_id=int(listing_id))

        return queryset

    @action(detail=True, methods=["get"], url_path="resolved")
    def resolved(self, request: Request, pk=None) -> Response:
        """The design with every element resolved to its final value.

        What the editor binds to: current content, geometry and style after
        overrides are applied, plus the permission and constraints for each
        element so the right controls can be rendered — and disabled.
        """
        design = self.get_object()
        dimension = get_dimension(
            request.query_params.get("dimension", DEFAULT_DIMENSION)
        )
        context = build_context(design)
        return Response(describe_design(design, context, dimension))

    @action(detail=True, methods=["post"], url_path="rename")
    def rename(self, request: Request, pk=None) -> Response:
        design = self.get_object()
        serializer = DesignRenameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        design.name = serializer.validated_data["name"]
        design.save(update_fields=["name", "updated_at"])
        return Response(self.get_serializer(design).data)

    @action(detail=True, methods=["post"], url_path="duplicate")
    def duplicate(self, request: Request, pk=None) -> Response:
        """Copy a design, including its overrides.

        Exports are deliberately not copied: they are rendered artefacts of a
        particular moment, and the copy has not been rendered yet.
        """
        design = self.get_object()
        serializer = DesignDuplicateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        copy = Design.objects.create(
            name=serializer.validated_data.get("name") or f"{design.name} (copy)",
            template=design.template,
            agent=design.agent,
            listing=design.listing,
            overrides=dict(design.overrides or {}),
        )
        return Response(
            self.get_serializer(copy).data, status=status.HTTP_201_CREATED
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="preview",
        throttle_classes=[ScopedRateThrottle],
    )
    def preview(self, request: Request, pk=None) -> Response:
        """Render without saving an export.

        Used by the editor. Throttled because every call occupies a browser
        page, and the pool is intentionally small.
        """
        design = self.get_object()
        dimension_key = request.data.get("dimension", DEFAULT_DIMENSION)
        if dimension_key not in SOCIAL_DIMENSIONS:
            return Response(
                {"dimension": [f"Unknown dimension '{dimension_key}'."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = render_design(design, dimension_key, ExportFormat.PNG)
        import base64

        return Response(
            {
                "dimension": dimension_key,
                "width": result.dimension.width,
                "height": result.dimension.height,
                "render_ms": result.render_ms,
                # Returned inline: a preview is transient and should not leave
                # a stored file behind on every keystroke.
                "image": f"data:image/png;base64,{base64.b64encode(result.content).decode('ascii')}",
            }
        )

    preview.throttle_scope = "render"

    @action(
        detail=True,
        methods=["post"],
        url_path="export",
        throttle_classes=[ScopedRateThrottle],
    )
    def export(self, request: Request, pk=None) -> Response:
        """Render and save one design at one or more dimensions."""
        design = self.get_object()
        serializer = DesignExportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        exports = export_design_bundle(
            design,
            serializer.validated_data["dimensions"],
            serializer.validated_data["export_format"],
        )
        return Response(
            DesignExportSerializer(
                exports, many=True, context=self.get_serializer_context()
            ).data,
            status=status.HTTP_201_CREATED,
        )

    export.throttle_scope = "render"


class DesignExportViewSet(viewsets.ReadOnlyModelViewSet):
    """Saved exports. Created through the design's export action."""

    serializer_class = DesignExportSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[DesignExport]:
        designs = Design.objects.for_user(self.request.user)
        queryset = DesignExport.objects.filter(design__in=designs).select_related("design")

        design_id = self.request.query_params.get("design")
        if design_id and design_id.isdigit():
            queryset = queryset.filter(design_id=int(design_id))
        return queryset


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def render_dimensions(request: Request) -> Response:
    """The social sizes one template can be exported at."""
    return Response(
        [
            {
                "key": dimension.key,
                "label": dimension.label,
                "width": dimension.width,
                "height": dimension.height,
                "aspect": round(dimension.aspect, 4),
            }
            for dimension in SOCIAL_DIMENSIONS.values()
        ]
    )
