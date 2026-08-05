"""Serializers for generated content."""

from __future__ import annotations

from rest_framework import serializers

from apps.ai_content.models import GeneratedContent
from apps.listings.models import Listing


class GeneratedContentSerializer(serializers.ModelSerializer):
    """Full record.

    Note what is absent: no API key, no prompt text, no raw provider response.
    ``prompt_facts`` is included because an agent should be able to see exactly
    which facts the copy was written from — that is the whole basis on which
    they are being asked to approve it.
    """

    is_usable = serializers.BooleanField(read_only=True)
    listing_address = serializers.CharField(source="listing.full_address", read_only=True)
    error_count = serializers.SerializerMethodField()
    warning_count = serializers.SerializerMethodField()

    class Meta:
        model = GeneratedContent
        fields = (
            "id",
            "listing",
            "listing_address",
            "kind",
            "job_status",
            "error_message",
            "caption",
            "hashtags",
            "rejected_output",
            "validation_status",
            "validation_issues",
            "error_count",
            "warning_count",
            "review_status",
            "reviewed_at",
            "is_usable",
            "model_name",
            "prompt_version",
            "prompt_facts",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "estimated_cost_usd",
            "duration_ms",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_error_count(self, obj: GeneratedContent) -> int:
        return sum(1 for issue in obj.validation_issues if issue.get("severity") == "error")

    def get_warning_count(self, obj: GeneratedContent) -> int:
        return sum(1 for issue in obj.validation_issues if issue.get("severity") == "warning")


class GeneratedContentStatusSerializer(serializers.ModelSerializer):
    """Small payload for polling. Kept minimal because it is fetched on a timer."""

    is_usable = serializers.BooleanField(read_only=True)

    class Meta:
        model = GeneratedContent
        fields = (
            "id",
            "job_status",
            "validation_status",
            "review_status",
            "is_usable",
            "error_message",
        )
        read_only_fields = fields


class GenerateRequestSerializer(serializers.Serializer):
    """Input for an explicit Generate / Regenerate action."""

    listing = serializers.PrimaryKeyRelatedField(queryset=Listing.objects.all())
    tone = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        help_text="Optional style note. Adds no facts and relaxes no rule.",
    )

    def validate_listing(self, value: Listing) -> Listing:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            raise serializers.ValidationError("Authentication required.")

        # Scoping first, so an out-of-scope id is not confirmed to exist by a
        # more specific error message.
        if not Listing.objects.for_user(user).filter(pk=value.pk).exists():
            raise serializers.ValidationError("No such listing.")

        if not value.is_usable_for_content:
            raise serializers.ValidationError(
                "This listing has not been verified. Review and confirm its "
                "details before generating content from it."
            )
        return value


class ReviewSerializer(serializers.Serializer):
    """Explicit agent decision on a draft."""

    decision = serializers.ChoiceField(choices=["approved", "rejected"])
