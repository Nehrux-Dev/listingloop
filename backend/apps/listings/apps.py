from django.apps import AppConfig


class ListingsConfig(AppConfig):
    """Property listings and their media, pricing and status."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.listings"
    label = "listings"
    verbose_name = "Listings"
