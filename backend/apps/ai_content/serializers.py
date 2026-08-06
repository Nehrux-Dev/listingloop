"""Serializers for generated content."""

from __future__ import annotations

from rest_framework import serializers

from apps.ai_content.models import ContentVariant, GeneratedContent
from apps.listings.models import Listing


class ContentVariantSerializer(serializers.ModelSerializer):
    """One reviewable piece of copy."""

    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    display_text = serializers.CharField(read_only=True)
    is_usable = serializers.BooleanField(read_only=True)
    error_count = serializers.SerializerMethodField()
    warning_count = serializers.SerializerMethodField()

    class Meta:
        model = ContentVariant
        fields = (
            "id",
            "generation",
            "kind",
            "kind_display",
            "text",
            "items",
            "rejected_text",
            "rejected_items",
            "display_text",
            "validation_status",
            "validation_issues",
            "error_count",
            "warning_count",
            "review_status",
            "reviewed_at",
            "is_usable",
            "is_edited",
            "original_text",
            "edited_at",
        )
        read_only_fields = fields

    def get_error_count(self, obj: ContentVariant) -> int:
        return sum(1 for issue in obj.validation_issues if issue.get("severity") == "error")

    def get_warning_count(self, obj: ContentVariant) -> int:
        return sum(1 for issue in obj.validation_issues if issue.get("severity") == "warning")


class VariantEditSerializer(serializers.Serializer):
    """An agent rewriting one variant.

    ``text`` for prose variants, ``items`` for hashtags. The server picks based
    on the variant's kind rather than trusting which field arrived.
    """

    text = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    items = serializers.ListField(
        child=serializers.CharField(max_length=80), required=False, max_length=30
    )

    def validate(self, attrs: dict) -> dict:
        if "text" not in attrs and "items" not in attrs:
            raise serializers.ValidationError("Send either 'text' or 'items'.")
        return attrs


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
    variants = ContentVariantSerializer(many=True, read_only=True)
    usable_variant_count = serializers.IntegerField(read_only=True)
    language_name = serializers.CharField(read_only=True)
    #: Surfaced so the UI can say the fact check only partly understood this
    #: language, rather than leaving an agent to assume a full check ran.
    has_partial_validation = serializers.BooleanField(read_only=True)

    class Meta:
        model = GeneratedContent
        fields = (
            "id",
            "listing",
            "listing_address",
            "kind",
            "language",
            "language_name",
            "has_partial_validation",
            "variants",
            "usable_variant_count",
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
    """Input for an explicit Generate / Regenerate action.

    ``languages`` fans out to one job — and therefore one API call and one
    stored pack — per language. Not one call returning every language: six
    languages of six variants would be a very long response, and truncation
    would lose the last language silently. Separate jobs also mean one language
    failing does not take the others with it, and each is costed on its own.
    """

    listing = serializers.PrimaryKeyRelatedField(queryset=Listing.objects.all())
    tone = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        help_text="Optional style note. Adds no facts and relaxes no rule.",
    )
    languages = serializers.ListField(
        child=serializers.CharField(max_length=16),
        required=False,
        allow_empty=False,
        max_length=8,
        help_text="Language codes. Defaults to English only.",
    )

    def validate_languages(self, value: list[str]) -> list[str]:
        from apps.ai_content.languages import enabled_codes

        allowed = enabled_codes()
        unknown = [code for code in value if code not in allowed]
        if unknown:
            raise serializers.ValidationError(
                f"Not enabled: {', '.join(unknown)}. Available: {', '.join(allowed)}."
            )

        # Preserve order, drop duplicates — asking for French twice is a client
        # slip, not a reason to pay for it twice.
        seen: list[str] = []
        for code in value:
            if code not in seen:
                seen.append(code)
        return seen

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
