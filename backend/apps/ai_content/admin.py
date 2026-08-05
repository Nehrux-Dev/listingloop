from django.contrib import admin

from apps.ai_content.models import ContentVariant, GeneratedContent


class ContentVariantInline(admin.StackedInline):
    model = ContentVariant
    extra = 0
    can_delete = False
    fields = (
        ("kind", "validation_status", "review_status", "is_edited"),
        "text",
        "items",
        "rejected_text",
        "rejected_items",
        "validation_issues",
    )
    # Flat: `fields` groups names into tuples for layout, but readonly_fields
    # must be plain strings.
    readonly_fields = (
        "kind",
        "validation_status",
        "review_status",
        "is_edited",
        "text",
        "items",
        "rejected_text",
        "rejected_items",
        "validation_issues",
    )

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(GeneratedContent)
class GeneratedContentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "listing",
        "job_status",
        "validation_status",
        "review_status",
        "total_tokens",
        "estimated_cost_usd",
        "created_at",
    )
    list_filter = ("job_status", "validation_status", "review_status", "model_name")
    search_fields = ("caption", "listing__address", "listing__city")
    autocomplete_fields = ("listing",)
    inlines = [ContentVariantInline]
    # Everything here is produced by the pipeline. Editing copy by hand in the
    # admin would detach it from the validation report that vouches for it —
    # agents edit through the API, which re-validates.
    readonly_fields = tuple(
        field.name for field in GeneratedContent._meta.fields
    ) + ("hashtags",)

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(ContentVariant)
class ContentVariantAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "generation",
        "kind",
        "validation_status",
        "review_status",
        "is_edited",
    )
    list_filter = ("kind", "validation_status", "review_status", "is_edited")
    search_fields = ("text", "generation__listing__address")
    readonly_fields = tuple(field.name for field in ContentVariant._meta.fields)

    def has_add_permission(self, request) -> bool:
        return False
