from django.apps import AppConfig


class ComplianceConfig(AppConfig):
    """Regulatory rules, disclosures and audit trails."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.compliance"
    label = "compliance"
    verbose_name = "Compliance"
