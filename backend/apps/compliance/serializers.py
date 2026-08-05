"""Serializers for compliance rules, evaluations and ad-hoc checks."""

from __future__ import annotations

from rest_framework import serializers

from apps.compliance.models import ComplianceEvaluation, ComplianceRule


class ComplianceRuleSerializer(serializers.ModelSerializer):
    """Read-only over the API.

    Rules are edited in the Django admin by whoever owns them, not through the
    app — the whole point is that changing a rule is not an engineering task,
    and it is not an agent's task either.
    """

    check_type_display = serializers.CharField(source="get_check_type_display", read_only=True)
    severity_display = serializers.CharField(source="get_severity_display", read_only=True)
    is_placeholder = serializers.BooleanField(read_only=True)

    class Meta:
        model = ComplianceRule
        fields = (
            "id",
            "rule_id",
            "description",
            "check_type",
            "check_type_display",
            "severity",
            "severity_display",
            "applies_to",
            "is_active",
            "legal_status",
            "is_placeholder",
            "order",
        )
        read_only_fields = fields


class ComplianceEvaluationSerializer(serializers.ModelSerializer):
    blocks_export = serializers.BooleanField(read_only=True)

    class Meta:
        model = ComplianceEvaluation
        fields = (
            "id",
            "design",
            "generated_content",
            "content_variant",
            "subject_kind",
            "subject_label",
            "status",
            "results",
            "error_count",
            "warning_count",
            "used_placeholder_rules",
            "blocks_export",
            "created_at",
        )
        read_only_fields = fields


class EvaluateRequestSerializer(serializers.Serializer):
    """Check something on demand, without storing the result.

    Exactly one target. Sending several would make the response ambiguous
    about which subject the results belong to.
    """

    design = serializers.IntegerField(required=False)
    generated_content = serializers.IntegerField(required=False)
    content_variant = serializers.IntegerField(required=False)
    listing = serializers.IntegerField(required=False)
    text = serializers.CharField(required=False, allow_blank=False, max_length=20000)

    TARGETS = ("design", "generated_content", "content_variant", "listing", "text")

    def validate(self, attrs: dict) -> dict:
        supplied = [name for name in self.TARGETS if attrs.get(name) is not None]
        if len(supplied) != 1:
            raise serializers.ValidationError(
                "Send exactly one of: " + ", ".join(self.TARGETS) + "."
            )
        attrs["_target"] = supplied[0]
        return attrs
