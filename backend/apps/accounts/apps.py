from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Users, organisations, agent profiles and permissions."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Accounts"

    def ready(self) -> None:
        # Importing for the @receiver side effects; the app registry is ready
        # at this point, so model imports are safe.
        from apps.accounts import signals  # noqa: F401
