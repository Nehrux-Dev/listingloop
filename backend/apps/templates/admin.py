"""Admin for the template library.

Templates are product content: Nehrux authors them here, agents consume them
through the API. That asymmetry is why the template endpoints are read-only.

The one exception is an *imported* template — extracted from artwork an agent
uploaded, owned by them, and visible only to them. Those are listed here too,
because an operator investigating "why does my import look wrong" needs to see
the geometry that came out; they are marked by their owner rather than
separated into their own screen.
"""

from django.contrib import admin

from apps.templates.models import (
    Design,
    DesignExport,
    Template,
    TemplateElement,
    TemplateImport,
)


class TemplateElementInline(admin.StackedInline):
    model = TemplateElement
    extra = 0
    fields = (
        ("key", "label"),
        ("element_type", "z_index"),
        "geometry",
        "style_properties",
        ("content_source", "default_content"),
        # Only meaningful when element_type is STATIC_GRAPHIC — left visible
        # for every row rather than conditionally hidden, since Django admin
        # inlines don't support per-row conditional fields without JS.
        "static_asset",
    )


@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = (
        "name", "owner", "category", "style", "element_count", "is_active", "updated_at",
    )
    # `owner` as a filter is really "library vs imported", which is the first
    # question anyone browsing this list has.
    list_filter = ("category", "style", "is_active", "owner")
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("owner",)
    inlines = [TemplateElementInline]
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Elements")
    def element_count(self, obj: Template) -> int:
        return obj.elements.count()


@admin.register(TemplateElement)
class TemplateElementAdmin(admin.ModelAdmin):
    list_display = ("key", "template", "element_type", "z_index")
    list_filter = ("element_type", "template__category")
    search_fields = ("key", "label", "template__name")
    autocomplete_fields = ("template",)


class DesignExportInline(admin.TabularInline):
    model = DesignExport
    extra = 0
    fields = ("dimension", "export_format", "width", "height", "bytes", "render_ms", "created_at")
    readonly_fields = fields
    can_delete = False


@admin.register(Design)
class DesignAdmin(admin.ModelAdmin):
    list_display = ("name", "template", "agent", "listing", "updated_at")
    list_filter = ("template__category", "template__style")
    search_fields = ("name", "agent__name", "agent__user__email")
    autocomplete_fields = ("template", "agent", "listing")
    inlines = [DesignExportInline]
    readonly_fields = ("created_at", "updated_at")


@admin.register(TemplateImport)
class TemplateImportAdmin(admin.ModelAdmin):
    """Read-only: an import is a record of something that already happened.

    Editing one would make the audit trail a suggestion, and the token and
    timing columns are the only place the cost of the feature is visible.
    """

    list_display = (
        "original_filename", "agent", "status", "element_count", "model_used",
        "duration_ms", "created_at",
    )
    list_filter = ("status", "model_used")
    search_fields = ("original_filename", "agent__user__email", "requested_name")
    autocomplete_fields = ("agent", "template")
    readonly_fields = (
        "agent", "source_file", "original_filename", "status", "error", "template",
        "requested_name", "category", "style", "element_count", "model_used",
        "prompt_tokens", "completion_tokens", "duration_ms", "started_at",
        "finished_at", "created_at", "updated_at",
    )

    def has_add_permission(self, request) -> bool:
        # An import starts with an upload through the API, never here: there
        # would be no file for the worker to read.
        return False


@admin.register(DesignExport)
class DesignExportAdmin(admin.ModelAdmin):
    list_display = ("__str__", "design", "dimension", "export_format", "width", "height", "created_at")
    list_filter = ("dimension", "export_format")
    readonly_fields = ("created_at", "updated_at")
