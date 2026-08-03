from django.apps import AppConfig


class TemplatesConfig(AppConfig):
    """Reusable content templates used to generate listing copy."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.templates"
    label = "templates"
    verbose_name = "Templates"
