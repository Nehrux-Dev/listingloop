"""Listing serializers."""

from __future__ import annotations

from rest_framework import serializers

from apps.accounts.models import AgentProfile
from apps.core.fields import ValidatedImageField
from apps.listings.models import (
    Listing,
    ListingPhoto,
    VerificationStatus,
    validate_features,
)


class ListingPhotoSerializer(serializers.ModelSerializer):
    image = ValidatedImageField(write_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = ListingPhoto
        fields = (
            "id",
            "listing",
            "image",
            "image_url",
            "caption",
            "order",
            "source_url",
            "created_at",
        )
        read_only_fields = ("id", "image_url", "source_url", "created_at")

    def get_image_url(self, obj: ListingPhoto) -> str | None:
        request = self.context.get("request")
        if not obj.image:
            return None
        url = obj.image.url
        return request.build_absolute_uri(url) if request else url

    def validate_listing(self, value: Listing) -> Listing:
        """You may only attach photos to a listing you can already manage."""
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            raise serializers.ValidationError("Authentication required.")

        if not Listing.objects.for_user(user).filter(pk=value.pk).exists():
            raise serializers.ValidationError("No such listing.")
        return value


class ListingSerializer(serializers.ModelSerializer):
    photos = ListingPhotoSerializer(many=True, read_only=True)
    full_address = serializers.CharField(read_only=True)
    is_verified = serializers.BooleanField(read_only=True)
    missing_required_fields = serializers.SerializerMethodField()
    agent_name = serializers.CharField(source="agent.name", read_only=True)

    class Meta:
        model = Listing
        fields = (
            "id",
            "agent",
            "agent_name",
            "address",
            "city",
            "state",
            "postcode",
            "country",
            "full_address",
            "price",
            "bedrooms",
            "bathrooms",
            "square_footage",
            "property_type",
            "features",
            "description",
            "status",
            "verification_status",
            "is_verified",
            "verified_at",
            "verified_by",
            "missing_required_fields",
            "source",
            "source_url",
            "imported_fields",
            "import_warnings",
            "photos",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "agent_name",
            "full_address",
            "is_verified",
            # Verification is only ever changed through the verify/unverify
            # actions or by editing the data. Making these writable would let a
            # client mark its own listing verified in a plain PATCH, which is
            # precisely the review step the feature exists to enforce.
            "verification_status",
            "verified_at",
            "verified_by",
            "missing_required_fields",
            # Provenance is set by the importer, never by the client.
            "source",
            "source_url",
            "imported_fields",
            "import_warnings",
            "photos",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {
            "agent": {"required": False},
        }

    def get_missing_required_fields(self, obj: Listing) -> list[str]:
        """What still needs filling in before the agent can verify."""
        return obj.missing_required_fields()

    def validate_features(self, value):
        validate_features(value)
        return value

    def validate_agent(self, value: AgentProfile) -> AgentProfile:
        """Agents may only file listings under their own profile."""
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            raise serializers.ValidationError("Authentication required.")

        if user.is_nehrux_admin:
            return value
        if user.is_brokerage_admin:
            if not user.administered_brokerages.filter(
                pk=value.brokerage_id or 0
            ).exists():
                raise serializers.ValidationError(
                    "That agent is not part of a brokerage you administer."
                )
            return value
        if value.user_id != user.id:
            raise serializers.ValidationError(
                "You can only create listings for your own profile."
            )
        return value

    def create(self, validated_data: dict) -> Listing:
        # Default the owner to the caller's own profile so an agent never has
        # to send an id that identifies themselves.
        if not validated_data.get("agent"):
            request = self.context.get("request")
            profile = AgentProfile.objects.filter(user=request.user).first()
            if profile is None:
                raise serializers.ValidationError(
                    {"agent": "You do not have an agent profile to file listings under."}
                )
            validated_data["agent"] = profile
        return super().create(validated_data)


class ListingImportSerializer(serializers.Serializer):
    """Input for the one-off URL import."""

    url = serializers.URLField(max_length=2000)


class ListingImportResultSerializer(serializers.Serializer):
    """What the import returns: the draft, plus an honest account of it."""

    listing = ListingSerializer(read_only=True)
    extracted_fields = serializers.ListField(child=serializers.CharField(), read_only=True)
    warnings = serializers.ListField(child=serializers.CharField(), read_only=True)
    photo_count = serializers.IntegerField(read_only=True)


class ListingVerifySerializer(serializers.Serializer):
    """Explicit confirmation that a human reviewed the data.

    ``confirmed`` must be sent as true. It exists so verification can never be
    the accidental result of an empty POST — the caller has to state that they
    checked.
    """

    confirmed = serializers.BooleanField()

    def validate_confirmed(self, value: bool) -> bool:
        if not value:
            raise serializers.ValidationError(
                "Set 'confirmed' to true to verify this listing."
            )
        return value


class ListingStatusSummarySerializer(serializers.Serializer):
    """Compact shape used by the listings index in the UI."""

    total = serializers.IntegerField()
    verified = serializers.IntegerField()
    unverified = serializers.IntegerField()

    @staticmethod
    def from_queryset(queryset) -> dict:
        total = queryset.count()
        verified = queryset.filter(
            verification_status=VerificationStatus.VERIFIED
        ).count()
        return {"total": total, "verified": verified, "unverified": total - verified}
