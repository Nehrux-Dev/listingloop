"""Template library and design endpoints.

    /api/templates/                 browse the library (read-only, filterable)
    /api/templates/facets/          category, style and format options + counts
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
from django.core.files.storage import default_storage
from django.db.models import Count, QuerySet
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.models import AgentProfile
from apps.accounts.permissions import IsNehruxAdmin
from apps.core.storage import build_upload_key
from apps.templates.document import (
    BLANK_ELEMENTS,
    PROPERTY_FIELDS,
    new_element,
    new_element_id,
)
from apps.templates.dimensions import DEFAULT_DIMENSION, SOCIAL_DIMENSIONS, get_dimension
from apps.templates.layout_adaptation import adapt_elements
from apps.templates.models import (
    LISTING_CATEGORIES,
    SEASONAL_CATEGORIES,
    CalendarEvent,
    Design,
    DesignExport,
    ExportFormat,
    ImportStatus,
    Template,
    TemplateCategory,
    TemplateImport,
    TemplateStyle,
)
from apps.templates.permissions import DesignPermission
from apps.templates.tasks import import_template_artwork
from apps.templates.render_context import build_context, resolve_path
from apps.templates.rendering import (
    describe_design_for_editor,
    export_design_bundle,
    render_design,
)
from apps.templates.serializers import (
    CalendarEventSerializer,
    DesignAdaptSerializer,
    DesignDuplicateSerializer,
    DesignExportRequestSerializer,
    DesignExportSerializer,
    DesignImageUploadSerializer,
    DesignRenameSerializer,
    DesignSerializer,
    TemplateDetailSerializer,
    TemplateImportCreateSerializer,
    TemplateImportSerializer,
    TemplateListSerializer,
)

logger = logging.getLogger(__name__)


class TemplateLibraryPagination(PageNumberPagination):
    """A gallery's page, not a record list's.

    The project default of 25 suits rows an agent reads one at a time. The
    template library is scanned a screenful at a time in a four-column grid,
    where 25 is two and a bit rows — paging that often turns browsing into
    clicking. Still bounded: `max_page_size` stops a crafted `page_size` from
    asking for the whole table.
    """

    page_size = 60
    page_size_query_param = "page_size"
    max_page_size = 120


class TemplateViewSet(mixins.DestroyModelMixin, viewsets.ReadOnlyModelViewSet):
    """The template library.

    Read-only to everybody except the platform owner, who publishes into it and
    can take things back out. Agents choose from templates, they do not edit
    them — which is what makes the permission map meaningful.
    """

    permission_classes = [IsAuthenticated]
    pagination_class = TemplateLibraryPagination

    def get_permissions(self):
        """Removing from the library is a Nehrux Admin's alone.

        The library is one shelf shared by every agency. A brokerage admin
        deleting from it would be deleting a rival firm's templates too, so
        the capability belongs to whoever owns the shelf.
        """
        if self.action in ("destroy", "publish"):
            return [IsAuthenticated(), IsNehruxAdmin()]
        return super().get_permissions()

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        """Take a template out of every agent's gallery.

        TWO OUTCOMES, AND THE DIFFERENCE IS NOT COSMETIC
        --------------------------------------------------------------------
        A template nobody has used is deleted outright. One that designs were
        made from is *retired* instead — `is_active=False`, which removes it
        from the gallery just as completely, because `get_queryset` filters on
        it.

        The reason is `Design.template`, which is `on_delete=PROTECT`. That
        protection is deliberate and worth keeping: an agent's finished flyer
        must not disappear because somebody tidied the library. Without this
        branch a delete would simply raise, and the admin would be told the
        template cannot be removed when what they asked for — gone from the
        agents' panel — is perfectly achievable.

        Either way the answer to "is it still in the agent dashboard" is no.
        """
        template = self.get_object()
        designs = template.designs.count()

        if designs:
            template.is_active = False
            template.save(update_fields=["is_active", "updated_at"])
            logger.info(
                "Template %s retired by user %s (%d design(s) keep it)",
                template.pk, request.user.pk, designs,
            )
            return Response(
                {
                    "retired": True,
                    "designs": designs,
                    "detail": (
                        f"Removed from the library. {designs} design"
                        f"{'' if designs == 1 else 's'} already made from it "
                        f"still open and export normally."
                    ),
                },
                status=status.HTTP_200_OK,
            )

        name = template.name
        template.delete()
        logger.info("Template %r deleted by user %s", name, request.user.pk)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_serializer_class(self):
        return (
            TemplateDetailSerializer
            if self.action == "retrieve"
            else TemplateListSerializer
        )

    def get_queryset(self) -> QuerySet[Template]:
        # `visible_to` is what keeps one agent's imported artwork out of every
        # other agent's gallery. The shared Nehrux library (owner IS NULL) is
        # visible to all; an import belongs to whoever uploaded it.
        queryset = (
            Template.objects.visible_to(self.request.user)
            .filter(is_active=True)
            .prefetch_related("elements")
        )

        params = self.request.query_params

        def chosen(name: str, allowed: list[str]) -> list[str]:
            """Comma-separated values, filtered to ones that exist.

            Multi-value because the library's filters are checkboxes: an
            agent narrowing to "Just Sold or Open House" is one question, and
            answering it with two requests the client then has to merge would
            get the counts and the paging wrong.

            A single value is still a single value, so callers written before
            this are unaffected. Unknown values are dropped rather than
            rejected — a stale bookmark should show the library, not a 400.
            """
            raw = params.get(name, "")
            return [value for value in raw.split(",") if value in allowed]

        categories = chosen("category", TemplateCategory.values)
        if categories:
            queryset = queryset.filter(category__in=categories)

        styles = chosen("style", TemplateStyle.values)
        if styles:
            queryset = queryset.filter(style__in=styles)

        # The format the template was composed for. Agents browse by "what am
        # I posting this to" at least as often as by occasion, and that is a
        # different axis from `category` — a Just Sold exists as a Post and as
        # a Story.
        dimensions = chosen("dimension", list(SOCIAL_DIMENSIONS))
        if dimensions:
            queryset = queryset.filter(default_dimension__in=dimensions)

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
            # Must mirror Template.requires_listing, which exempts imported
            # templates whatever their category — see that property for why.
            # Expressed as a query rather than reusing it because this filters
            # in the database, so the two have to be kept in step by hand: an
            # import left out here would be openable everywhere except the one
            # list that exists to name what is openable.
            queryset = queryset.exclude(
                category__in=LISTING_CATEGORIES, owner__isnull=True
            )

        return queryset

    @action(detail=True, methods=["post"], url_path="publish")
    def publish(self, request: Request, pk=None) -> Response:
        """Move an imported template into the shared library.

        This is the Upload button on the platform dashboard, and it is the only
        way a template reaches every agent in every brokerage.

        An import lands owned by whoever uploaded it, which makes it a private
        draft: `Template.visible_to` shows an owned template to its owner and
        nobody else. Clearing the owner is what publishes it — the same
        queryset then returns it to everyone. So the review step is not a
        workflow bolted on top, it is just the state an import already starts
        in.

        Nehrux Admins only. A brokerage admin publishing here would be putting
        their own artwork into a rival brokerage's gallery.
        """
        template = self.get_object()
        if template.owner_id is None:
            return Response(
                {"detail": "That template is already in the shared library."},
                status=status.HTTP_409_CONFLICT,
            )

        template.owner = None
        template.is_active = True
        template.save(update_fields=["owner", "is_active", "updated_at"])
        logger.info(
            "Template %s published to the library by user %s", template.pk, request.user.pk
        )
        return Response(TemplateDetailSerializer(template, context={"request": request}).data)

    @action(detail=False, methods=["get"], url_path="facets")
    def facets(self, request: Request) -> Response:
        """Filter options, with counts, so the UI need not hardcode them.

        Every option is listed whether or not anything matches it, including
        the zeroes — the caller decides whether to show an empty filter, and
        an option that silently vanishes from the sidebar reads as a bug.

        Counted with one grouped query per axis rather than one per option:
        three axes over twenty-odd options is a lot of `COUNT(*)` for what is
        a page of checkboxes.

        Scoped exactly like the list it describes. A count that includes
        templates the caller cannot see sends them to a filter that comes back
        empty, which reads as a bug rather than as a permission boundary.
        """
        active = Template.objects.visible_to(request.user).filter(is_active=True)

        def tally(field: str) -> dict[str, int]:
            # `.order_by()` first, and not for tidiness. Template.Meta orders
            # by (category, style, name), and Django folds a model's default
            # ordering into the GROUP BY of a values().annotate() — leaving it
            # in would group by all three columns and count combinations
            # rather than categories. Clearing it is what makes this one row
            # per value.
            return {
                row[field]: row["total"]
                for row in active.order_by().values(field).annotate(total=Count("id"))
            }

        by_category = tally("category")
        by_style = tally("style")
        by_dimension = tally("default_dimension")

        return Response(
            {
                "categories": [
                    {"value": value, "label": label, "count": by_category.get(value, 0)}
                    for value, label in TemplateCategory.choices
                ],
                "styles": [
                    {"value": value, "label": label, "count": by_style.get(value, 0)}
                    for value, label in TemplateStyle.choices
                ],
                "dimensions": [
                    {
                        "value": key,
                        "label": dimension.label,
                        "count": by_dimension.get(key, 0),
                    }
                    for key, dimension in SOCIAL_DIMENSIONS.items()
                ],
            }
        )


class TemplateImportViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Turn uploaded artwork into a template.

        POST /api/template-imports/    upload a PDF or image, returns 202
        GET  /api/template-imports/    this agent's imports, newest first
        GET  /api/template-imports/1/  poll one

    No update and no delete. An import is a record of something that happened;
    editing one would make the audit trail a suggestion, and deleting one
    would orphan the template it produced.

    The work runs on a Celery worker: extraction is a minute-scale vision call,
    and holding an HTTP request open for it means a gateway timeout is
    indistinguishable from a failure — with nothing left behind to look at.
    """

    serializer_class = TemplateImportSerializer
    permission_classes = [IsAuthenticated]
    # multipart only: this endpoint exists to receive a file.
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "template_import"

    def get_throttles(self):
        """The platform owner gets the higher ceiling.

        The low limit exists because an import can mean a paid vision call, and
        that reasoning holds for an agent importing their own artwork. It does
        not hold for Nehrux filling the library: a text PDF is read structurally
        and costs nothing, and stocking the gallery is a sitting-down job that
        being cut off after ten uploads makes impossible.

        Set per request rather than per class because `throttle_scope` is read
        off the view instance, and the two scopes have to be able to coexist.
        """
        user = getattr(self.request, "user", None)
        if getattr(user, "is_nehrux_admin", False):
            self.throttle_scope = "template_import_admin"
        return super().get_throttles()

    def get_queryset(self) -> QuerySet[TemplateImport]:
        # Strictly the caller's own. Unlike designs, an import is not
        # brokerage-visible work: it is a file somebody dragged in, and the
        # error messages on a failed one can quote their filename.
        return (
            TemplateImport.objects.filter(agent__user=self.request.user)
            .select_related("template")
            .prefetch_related("template__elements")
        )

    def create(self, request: Request, *args, **kwargs) -> Response:
        """Accept the file, queue the extraction, return the job to poll."""
        profile = AgentProfile.objects.filter(user=request.user).first()
        if profile is None:
            return Response(
                {
                    "detail": (
                        "You need an agent profile before importing templates."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = TemplateImportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["file"]

        job = TemplateImport.objects.create(
            agent=profile,
            source_file=upload,
            # Kept separately from the storage key, which is a random UUID by
            # design (see core/storage.py) and so cannot carry the name back.
            original_filename=upload.name[:255],
            requested_name=serializer.validated_data.get("name", ""),
            category=serializer.validated_data["category"],
            style=serializer.validated_data["style"],
        )

        # Queued after the row is committed, so the worker cannot look for a
        # record that is not there yet.
        try:
            import_template_artwork.delay(job.pk)
        except Exception:
            # A broker that is down must not swallow the upload silently: the
            # file is already stored, so the job is marked failed with
            # something a user can act on rather than left queued forever.
            logger.exception("Could not queue template import %s", job.pk)
            job.status = ImportStatus.FAILED
            job.error = (
                "The import queue is unavailable right now. Your file was "
                "saved — try importing it again shortly."
            )
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error", "finished_at", "updated_at"])

        logger.info(
            "Queued template import %s (%r) for user %s",
            job.pk, job.original_filename, request.user.pk,
        )
        return Response(
            self.get_serializer(job).data, status=status.HTTP_202_ACCEPTED
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
        # Counted once for the whole page rather than per row, and scoped to
        # what this user can actually open.
        context["template_counts"] = {
            row["category"]: row["total"]
            for row in Template.objects.visible_to(self.request.user)
            .filter(is_active=True)
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
        templates = Template.objects.visible_to(request.user).filter(
            category=event.category, is_active=True
        )
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

        # `?mine=1` narrows to the caller's own designs.
        #
        # `for_user` above is the *permission* boundary — a brokerage admin may
        # legitimately read the whole firm's work. That is the wrong answer for
        # the two screens that ask "what have I been making": the Designs panel,
        # and the check for an existing design behind a template. Without this,
        # an admin's panel fills with their agents' designs, and clicking a
        # template would offer to resume somebody else's work in it.
        if self.request.query_params.get("mine") in {"1", "true"}:
            queryset = queryset.filter(agent__user=self.request.user)

        template_id = self.request.query_params.get("template")
        if template_id and template_id.isdigit():
            queryset = queryset.filter(template_id=int(template_id))

        listing_id = self.request.query_params.get("listing")
        if listing_id and listing_id.isdigit():
            queryset = queryset.filter(listing_id=int(listing_id))

        return queryset

    def create(self, request: Request, *args, **kwargs) -> Response:
        """POST a design, or get back the one you already had.

        `DesignSerializer.create` resumes an existing design rather than making
        a near-duplicate of it. When it does, saying 201 Created would be a
        lie — and a caller that trusts the status to mean "this is new" would
        be wrong about it — so a resumed design answers 200 instead.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        code = (
            status.HTTP_200_OK
            if serializer.reused_existing
            else status.HTTP_201_CREATED
        )
        return Response(serializer.data, status=code, headers=headers)

    @action(detail=True, methods=["get"], url_path="resolved")
    def resolved(self, request: Request, pk=None) -> Response:
        """The design with every element resolved to its final value.

        The design's own elements, each with its content resolved: what the
        bound field currently says, or the agent's own words where they typed
        over it. Images are resolved to real data URIs here rather than left as
        storage keys, via ``describe_design_for_editor`` — the same resolver an
        actual export uses, so the canvas never shows something the export
        would render differently.
        """
        design = self.get_object()
        dimension_key = request.query_params.get("dimension", DEFAULT_DIMENSION)
        return Response(describe_design_for_editor(design, dimension_key))

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
        """Copy a design, including its whole canvas.

        Element ids are regenerated. Two designs sharing an element id would
        make anything keyed on one — a selection, a client-side cache, an undo
        entry — able to address the wrong design's element.

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
            elements=[
                {**element, "id": new_element_id()}
                for element in design.ensure_document()
            ],
        )
        return Response(
            self.get_serializer(copy).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="adapt")
    def adapt(self, request: Request, pk=None) -> Response:
        """Copy a design with its layout re-composed for another format.

        A copy, not an in-place change, for the same reason Canva's resize
        makes one: a design's single document renders at every dimension, so
        re-laying it out for LinkedIn in place would wreck the Instagram
        version the agent already has. The copy is an ordinary design —
        hand-editable, exportable — whose ``preferred_dimension`` tells the
        editor which format to open it at.

        The layout maths is ``layout_adaptation.adapt_elements``; it runs once
        here, and only the stored numbers travel further, so the editor, the
        renderer and the export cannot disagree about what "adapted" means.
        """
        design = self.get_object()
        serializer = DesignAdaptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = get_dimension(serializer.validated_data["dimension"])
        # The format this document is actually composed for. An adapted copy
        # carries its own; treating it as still flyer-shaped would re-adapt
        # geometry that already moved and scramble it.
        source = get_dimension(
            design.preferred_dimension or design.template.default_dimension
        )
        if target.key == source.key:
            return Response(
                {
                    "detail": (
                        "This design is already composed for "
                        f"{source.label} — there is nothing to adapt."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        adapted = adapt_elements(design.ensure_document(), source, target)
        # Suffixed like a duplicate is, and truncated the same way any name
        # field is — a long design name must not turn a 201 into a 500.
        name = (
            serializer.validated_data.get("name")
            or f"{design.name} — {target.label}"
        )[:160]
        copy = Design.objects.create(
            name=name,
            template=design.template,
            agent=design.agent,
            listing=design.listing,
            preferred_dimension=target.key,
            elements=[{**element, "id": new_element_id()} for element in adapted],
        )
        return Response(
            self.get_serializer(copy).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="elements/add")
    def add_element(self, request: Request, pk=None) -> Response:
        """Drop a new element onto this design's canvas.

        Thin on purpose. Creating an element is a local act in a canvas editor
        — the client already knows where the user clicked — so this exists to
        keep one definition of what a fresh text box or button looks like
        (``document.BLANK_ELEMENTS``), not because the server needs to be
        consulted. Everything after creation is saved with the rest of the
        document.
        """
        design = self.get_object()
        kind = request.data.get("kind")
        elements = design.ensure_document()
        highest = max((int((e.get("transform") or {}).get("z_index", 0)) for e in elements), default=-1)

        element = new_element(kind, z_index=highest + 1)
        elements.append(element)
        design.save(update_fields=["elements", "updated_at"])
        return Response(
            {
                "element": element,
                "design": describe_design_for_editor(design, DEFAULT_DIMENSION),
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path=r"elements/(?P<element_id>[\w-]+)/reset",
    )
    def reset_element(self, request: Request, pk=None, element_id=None) -> Response:
        """Put one element back the way the template has it.

        Matched by ``original_element_id``, so it survives every edit that
        could have happened in between — rename, restyle, move, reorder,
        duplicate. An element the agent added has no original and cannot be
        reset; that is answered with 400 and a reason rather than a silent
        no-op, because "nothing happened" is indistinguishable from a bug.
        """
        design = self.get_object()
        design.ensure_document()
        restored = design.reset_element(element_id)
        if restored is None:
            return Response(
                {
                    "detail": (
                        "This element has no template original to reset to — it "
                        "was added to this design, or the template element it "
                        "came from no longer exists."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        design.save(update_fields=["elements", "updated_at"])
        return Response(
            {
                "element": restored,
                "design": describe_design_for_editor(design, DEFAULT_DIMENSION),
            }
        )

    @action(detail=True, methods=["post"], url_path="reset")
    def reset(self, request: Request, pk=None) -> Response:
        """Throw the whole canvas away and re-copy it from the template.

        Destructive and unrecoverable — every edit on this design goes. The
        confirmation is the client's job; what this end of it does is refuse to
        act on a bare POST, so a mis-wired button or a replayed request cannot
        wipe a design on its own.
        """
        design = self.get_object()
        if request.data.get("confirm") is not True:
            return Response(
                {
                    "confirm": [
                        "Resetting discards every edit on this design. Send "
                        "confirm: true to proceed."
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        design.reset_document()
        design.save(update_fields=["elements", "updated_at"])
        return Response(describe_design_for_editor(design, DEFAULT_DIMENSION))

    @action(detail=True, methods=["get"], url_path="property-data")
    def property_data(self, request: Request, pk=None) -> Response:
        """The business facts behind this design, and what is bound to them.

        One payload rather than two so the data panel can show "3 elements
        customized" next to a field without a second round trip.
        """
        design = self.get_object()
        context = build_context(design)
        elements = design.ensure_document()

        fields = []
        for field in PROPERTY_FIELDS:
            bound = [e for e in elements if e.get("bound_to") == field.name]
            fields.append(
                {
                    **field.as_dict(),
                    "value": resolve_path(context, field.path),
                    "bound_element_ids": [e["id"] for e in bound],
                    "overridden_element_ids": [
                        e["id"] for e in bound if e.get("manually_overridden")
                    ],
                }
            )
        return Response({"has_listing": design.listing_id is not None, "fields": fields})

    @action(detail=True, methods=["post"], url_path="upload-image")
    def upload_image(self, request: Request, pk=None) -> Response:
        """Upload an image and get back a key usable as an `image_key`
        override — the "upload a new one" half of image replace.

        Requires write access to the design (``self.get_object()`` already
        enforces that) but does not itself change the design: the caller
        still has to PATCH the returned key onto the element they mean it
        for, exactly like picking an existing listing photo would. Nothing is
        assumed about which element this is for.
        """
        design = self.get_object()
        serializer = DesignImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        image_file = serializer.validated_data["image"]
        requested_key = build_upload_key("designs/uploads", image_file.name)
        # build_upload_key is UUID-based, so a collision is not realistically
        # possible — but Storage.save() is the source of truth for what it
        # actually wrote, and using anything else is how this kind of code
        # quietly breaks the day that assumption stops holding.
        key = default_storage.save(requested_key, image_file)

        return Response(
            {
                "image_key": key,
                "url": request.build_absolute_uri(default_storage.url(key)),
            },
            status=status.HTTP_201_CREATED,
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
def element_kinds(request: Request) -> Response:
    """The kinds of element an agent can add, and what a fresh one looks like.

    Published so the canvas can create an element locally — instantly, where
    the user clicked — without inventing its own idea of a default button or
    text box. One definition (``document.BLANK_ELEMENTS``), two consumers.
    """
    return Response(
        [
            {"kind": kind, "label": blueprint["name"], "blueprint": blueprint}
            for kind, blueprint in BLANK_ELEMENTS.items()
        ]
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def render_dimensions(request: Request) -> Response:
    """The social sizes one template can be exported at.

    Includes the safe-area insets html_builder maps geometry into (Story's
    platform chrome, mainly) — additive fields, so a client that already
    ignores them keeps working. Without them, a canvas editor would place
    elements against the raw canvas edge and disagree with what the actual
    renderer produces for every non-zero-inset dimension.
    """
    return Response(
        [
            {
                "key": dimension.key,
                "label": dimension.label,
                "width": dimension.width,
                "height": dimension.height,
                "aspect": round(dimension.aspect, 4),
                "safe_inset_top": dimension.safe_inset_top,
                "safe_inset_bottom": dimension.safe_inset_bottom,
            }
            for dimension in SOCIAL_DIMENSIONS.values()
        ]
    )
