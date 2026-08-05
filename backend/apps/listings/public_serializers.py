"""Serializers for the public, unauthenticated listing page.

DELIBERATELY SEPARATE FROM THE AUTHENTICATED ONES
-------------------------------------------------
These do not subclass ``ListingSerializer``. Reusing it and blacklisting a few
fields would mean every future field is public by default, and someone would
eventually add an internal note that nobody remembered to exclude. Here the
field list is an allowlist, written out in full: anything not named is not
published.

Not published, specifically: verification state, import provenance and
warnings, source URL, internal ids of the agent's other records, and any
contact detail belonging to the agent that they have not put on their public
profile.
"""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.listings.models import Enquiry, Listing, ListingPhoto
from apps.listings.spam import issue_form_token


class PublicPhotoSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = ListingPhoto
        fields = ("id", "image_url", "caption", "order")
        read_only_fields = fields

    def get_image_url(self, obj: ListingPhoto) -> str | None:
        if not obj.image:
            return None
        request = self.context.get("request")
        url = obj.image.url
        return request.build_absolute_uri(url) if request else url


class PublicAgentSerializer(serializers.Serializer):
    """The agent, as they present themselves publicly."""

    name = serializers.CharField()
    job_title = serializers.CharField()
    phone = serializers.CharField()
    email = serializers.EmailField()
    tagline = serializers.CharField()
    photo_url = serializers.SerializerMethodField()

    def get_photo_url(self, obj) -> str | None:
        if not obj.photo:
            return None
        request = self.context.get("request")
        url = obj.photo.url
        return request.build_absolute_uri(url) if request else url


class PublicBrokerageSerializer(serializers.Serializer):
    name = serializers.CharField()
    phone = serializers.CharField()
    website = serializers.CharField()
    required_disclaimer = serializers.CharField()
    logo_url = serializers.SerializerMethodField()

    def get_logo_url(self, obj) -> str | None:
        if not obj.logo:
            return None
        request = self.context.get("request")
        url = obj.logo.url
        return request.build_absolute_uri(url) if request else url


class PublicListingSerializer(serializers.ModelSerializer):
    """One verified listing, as the public sees it."""

    photos = PublicPhotoSerializer(many=True, read_only=True)
    agent = serializers.SerializerMethodField()
    brokerage = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    property_type_display = serializers.CharField(
        source="get_property_type_display", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    #: Issued with the page so the enquiry form can prove it was actually
    #: loaded before being submitted. See apps/listings/spam.py.
    enquiry_form_token = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = (
            "public_slug",
            "address",
            "city",
            "state",
            "postcode",
            "country",
            "full_address",
            "location",
            "price",
            "bedrooms",
            "bathrooms",
            "square_footage",
            "property_type",
            "property_type_display",
            "features",
            "description",
            "status",
            "status_display",
            "photos",
            "agent",
            "brokerage",
            "enquiry_form_token",
        )
        read_only_fields = fields

    def get_location(self, obj: Listing) -> dict:
        """Map coordinates, when the agent has set a pin."""
        return {
            "latitude": float(obj.latitude) if obj.latitude is not None else None,
            "longitude": float(obj.longitude) if obj.longitude is not None else None,
            "has_pin": obj.has_map_pin,
            "label": obj.full_address,
        }

    def get_agent(self, obj: Listing) -> dict:
        return PublicAgentSerializer(obj.agent, context=self.context).data

    def get_brokerage(self, obj: Listing) -> dict | None:
        brokerage = obj.agent.brokerage
        if brokerage is None:
            return None
        return PublicBrokerageSerializer(brokerage, context=self.context).data

    def get_enquiry_form_token(self, obj: Listing) -> str:
        return issue_form_token()


class PublicEnquirySerializer(serializers.ModelSerializer):
    """Input for the public enquiry form.

    ``website`` is the honeypot: hidden in the UI, never filled by a person.
    It is named something a bot would want to complete.
    """

    website = serializers.CharField(required=False, allow_blank=True, write_only=True)
    form_token = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Enquiry
        fields = ("name", "email", "phone", "message", "website", "form_token")
        extra_kwargs = {
            "name": {"required": True, "max_length": 120},
            "message": {"required": True},
            "email": {"required": False, "allow_blank": True},
            "phone": {"required": False, "allow_blank": True},
        }

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Please give your name.")
        return value

    def validate_message(self, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise serializers.ValidationError(
                "Please write a little more so the agent can help."
            )
        if len(value) > 4000:
            raise serializers.ValidationError("That message is too long.")
        return value

    def validate(self, attrs: dict) -> dict:
        # One way to reply is the minimum for this to be an enquiry at all.
        if not attrs.get("email") and not attrs.get("phone"):
            raise serializers.ValidationError(
                {"email": "Please give an email address or a phone number."}
            )
        return attrs


class EnquirySerializer(serializers.ModelSerializer):
    """The authenticated view: what the agent sees in their inbox."""

    listing_address = serializers.CharField(source="listing.full_address", read_only=True)
    listing_slug = serializers.CharField(source="listing.public_slug", read_only=True)
    agent_name = serializers.CharField(source="agent.name", read_only=True)
    is_spam = serializers.BooleanField(read_only=True)
    contact_summary = serializers.CharField(read_only=True)

    class Meta:
        model = Enquiry
        fields = (
            "id",
            "listing",
            "listing_address",
            "listing_slug",
            "agent",
            "agent_name",
            "name",
            "email",
            "phone",
            "message",
            "status",
            "is_spam",
            "contact_summary",
            "spam_reasons",
            "read_at",
            "created_at",
        )
        read_only_fields = tuple(
            name for name in fields if name != "status"
        )


class EnquiryStatusSerializer(serializers.Serializer):
    from apps.listings.models import EnquiryStatus

    status = serializers.ChoiceField(choices=EnquiryStatus.choices)


def price_for_display(value: Decimal | None) -> str:
    return f"${value:,.0f}" if value is not None else ""
