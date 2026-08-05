from django.contrib import admin

from apps.ai_content.models import GeneratedContent


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
    # Everything here is produced by the pipeline. Editing a caption by hand in
    # the admin would detach it from the validation report that vouches for it.
    readonly_fields = tuple(
        field.name for field in GeneratedContent._meta.fields
    ) + ("hashtags",)

    def has_add_permission(self, request) -> bool:
        return False
