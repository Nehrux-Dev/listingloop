"""Admin for the template library.

Templates are product content: Nehrux authors them here, agents consume them
through the API. That asymmetry is why the template endpoints are read-only.
"""

from django.contrib import admin

from apps.templates.models import Design, DesignExport, Template, TemplateElement


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
    list_display = ("name", "category", "style", "element_count", "is_active", "updated_at")
    list_filter = ("category", "style", "is_active")
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
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


@admin.register(DesignExport)
class DesignExportAdmin(admin.ModelAdmin):
    list_display = ("__str__", "design", "dimension", "export_format", "width", "height", "created_at")
    list_filter = ("dimension", "export_format")
    readonly_fields = ("created_at", "updated_at")
