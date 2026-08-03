from django.contrib import admin

from apps.listings.models import Listing, ListingPhoto


class ListingPhotoInline(admin.TabularInline):
    model = ListingPhoto
    extra = 0
    fields = ("image", "caption", "order", "source_url")
    readonly_fields = ("source_url",)


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "agent",
        "price",
        "status",
        "verification_status",
        "source",
        "updated_at",
    )
    list_filter = ("verification_status", "status", "property_type", "source")
    search_fields = ("address", "city", "postcode", "agent__name", "agent__user__email")
    autocomplete_fields = ("agent",)
    inlines = [ListingPhotoInline]
    readonly_fields = (
        # Verification is earned through the API action, not typed in here.
        "verification_status",
        "verified_at",
        "verified_by",
        "imported_fields",
        "import_warnings",
        "created_at",
        "updated_at",
    )


@admin.register(ListingPhoto)
class ListingPhotoAdmin(admin.ModelAdmin):
    list_display = ("__str__", "listing", "order", "created_at")
    list_filter = ("listing__status",)
    autocomplete_fields = ("listing",)
