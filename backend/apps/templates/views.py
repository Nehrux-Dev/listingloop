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

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, QuerySet
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.templates.dimensions import DEFAULT_DIMENSION, SOCIAL_DIMENSIONS, get_dimension
from apps.templates.html_builder import describe_design
from apps.templates.models import (
    LISTING_CATEGORIES,
    SEASONAL_CATEGORIES,
    CalendarEvent,
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
    CalendarEventSerializer,
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

    def get_serializer_class(self):
        return (
            TemplateDetailSerializer
            if self.action == "retrieve"
            else TemplateListSerializer
        )

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

        # `seasonal=true` is how the content calendar asks for the templates an
        # agent can use with no property attached.
        seasonal = params.get("seasonal")
        if seasonal == "true":
            queryset = queryset.filter(category__in=SEASONAL_CATEGORIES)
        elif seasonal == "false":
            queryset = queryset.exclude(category__in=SEASONAL_CATEGORIES)

        if params.get("no_listing_required") == "true":
            queryset = queryset.exclude(category__in=LISTING_CATEGORIES)

        return queryset

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


class CalendarEventViewSet(viewsets.ReadOnlyModelViewSet):
    """The content calendar.

    Read-only: dates for moving festivals are maintained deliberately in the
    admin, not edited by agents. Getting Eid wrong for somebody is not a thing
    to leave to a free-text field in the app.
    """

    serializer_class = CalendarEventSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self) -> QuerySet[CalendarEvent]:
        queryset = CalendarEvent.objects.filter(is_active=True)

        params = self.request.query_params
        # Default to what is still ahead: a calendar of past festivals is a
        # history lesson, not a planning tool.
        if params.get("include_past") != "true":
            queryset = queryset.filter(date__gte=timezone.localdate())

        within = params.get("within_days")
        if within and within.isdigit():
            queryset = queryset.filter(
                date__lte=timezone.localdate() + timedelta(days=int(within))
            )

        category = params.get("category")
        if category:
            queryset = queryset.filter(category=category)

        return queryset.order_by("date")

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        # Counted once for the whole page rather than per row.
        context["template_counts"] = {
            row["category"]: row["total"]
            for row in Template.objects.filter(is_active=True)
            .values("category")
            .annotate(total=Count("id"))
        }
        return context

    @action(detail=True, methods=["get"], url_path="templates")
    def templates_for_event(self, request: Request, pk=None) -> Response:
        """The templates an agent can use for this occasion.

        None of them need a listing — that is the point of the calendar.
        """
        event = self.get_object()
        templates = Template.objects.filter(category=event.category, is_active=True)
        return Response(
            {
                "event": self.get_serializer(event).data,
                "templates": TemplateListSerializer(
                    templates, many=True, context=self.get_serializer_context()
                ).data,
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
        # Preview deliberately does NOT require a complete profile: seeing what
        # is missing is exactly why an agent previews. Export is the gate.
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

    @action(detail=True, methods=["get"], url_path="readiness")
    def readiness(self, request: Request, pk=None) -> Response:
        """What this design still needs, without trying to export it.

        The editor calls this so an agent sees the gaps while they are working,
        rather than meeting them at the export button.
        """
        from apps.templates.readiness import assess_design

        design = self.get_object()
        missing = assess_design(design, build_context(design))
        return Response(
            {
                "ready": not missing,
                "missing": [item.as_dict() for item in missing],
                "steps": sorted({item.step for item in missing}),
            }
        )

    @action(detail=True, methods=["get"], url_path="compliance")
    def compliance(self, request: Request, pk=None) -> Response:
        """What the compliance rules say about this design, right now.

        Read-only and unstored: the editor calls this to show flags while the
        agent is still working. The stored record is written at export, which
        is the moment that needs an audit trail.
        """
        from apps.compliance.engine import evaluate
        from apps.compliance.subjects import from_design

        return Response(evaluate(from_design(self.get_object())).as_dict())

    @action(
        detail=True,
        methods=["post"],
        url_path="export",
        throttle_classes=[ScopedRateThrottle],
    )
    def export(self, request: Request, pk=None) -> Response:
        """Render and save one design at one or more dimensions.

        Compliance runs first. A rule with ERROR severity stops the export and
        returns the report — the point of the check is to catch material before
        it is published, and an export is the last moment that is still true.
        Warnings are returned alongside a successful export rather than
        blocking it.
        """
        from apps.compliance.engine import evaluate_and_store
        from apps.compliance.subjects import from_design
        from apps.templates.readiness import DesignNotReadyError, require_design_ready

        design = self.get_object()
        serializer = DesignExportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Before anything is rendered: an asset with a blank space where the
        # brokerage logo belongs is worse than a clear refusal naming the
        # missing field, because the blank one may not be noticed until it is
        # published. Judged against THIS design's elements, so a template that
        # never shows a logo is never blocked for the want of one.
        try:
            require_design_ready(design, build_context(design))
        except DesignNotReadyError as exc:
            return Response(exc.as_dict(), status=status.HTTP_409_CONFLICT)

        report, _evaluation = evaluate_and_store(from_design(design), design=design)

        if report.blocks_export and settings.COMPLIANCE_BLOCK_EXPORTS:
            return Response(
                {
                    "detail": (
                        "This design cannot be exported yet: it does not meet "
                        "the compliance rules below."
                    ),
                    "compliance": report.as_dict(),
                },
                status=status.HTTP_409_CONFLICT,
            )

        exports = export_design_bundle(
            design,
            serializer.validated_data["dimensions"],
            serializer.validated_data["export_format"],
        )
        return Response(
            {
                "exports": DesignExportSerializer(
                    exports, many=True, context=self.get_serializer_context()
                ).data,
                # Returned even on success so warnings are seen rather than
                # silently passed over.
                "compliance": report.as_dict(),
            },
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
