"""Serializers for brokerages, agent profiles and brand kits.

A recurring theme here: fields that decide *authorisation* are read-only for
users who should not control them. An agent may edit their own name, photo and
tagline, but not which brokerage they belong to — otherwise "edit your own
profile" would quietly become "join any brokerage you like".
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.accounts.models import AgentProfile, BrandKit, Brokerage
from apps.core.fields import ValidatedImageField

User = get_user_model()


class BrokerageSummarySerializer(serializers.ModelSerializer):
    """Compact brokerage representation for nesting inside other payloads."""

    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Brokerage
        fields = ("id", "name", "logo_url", "required_disclaimer")
        read_only_fields = fields

    def get_logo_url(self, obj: Brokerage) -> str | None:
        return _file_url(obj.logo, self.context.get("request"))


def _file_url(file_field, request) -> str | None:
    """Absolute URL for a stored file, or None.

    ``.url`` is resolved by the storage backend, so this works unchanged
    whether the file sits on the local disk or in an object store.
    """
    if not file_field:
        return None
    try:
        url = file_field.url
    except ValueError:
        return None
    return request.build_absolute_uri(url) if request is not None else url


class BrokerageSerializer(serializers.ModelSerializer):
    """Full brokerage representation."""

    # Declared explicitly so the size check runs before the image is decoded.
    logo = ValidatedImageField(required=False, allow_null=True, write_only=True)
    logo_url = serializers.SerializerMethodField()
    agent_count = serializers.IntegerField(source="agents.count", read_only=True)

    class Meta:
        model = Brokerage
        fields = (
            "id",
            "name",
            "logo",
            "logo_url",
            "required_disclaimer",
            "website",
            "phone",
            "agent_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "logo_url", "agent_count", "created_at", "updated_at")
        # `logo` is write_only above: clients read the resolved URL and never
        # need the raw storage key.

    def get_logo_url(self, obj: Brokerage) -> str | None:
        return _file_url(obj.logo, self.context.get("request"))


class AgentProfileSerializer(serializers.ModelSerializer):
    """Agent profile.

    ``brokerage`` is read-only for agents and writable for admins — see
    ``get_fields``. ``user`` is only writable on create, and only by an admin.
    """

    photo = ValidatedImageField(required=False, allow_null=True, write_only=True)
    photo_url = serializers.SerializerMethodField()
    brokerage_detail = BrokerageSummarySerializer(source="brokerage", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)
    role = serializers.CharField(source="user.role", read_only=True)

    class Meta:
        model = AgentProfile
        fields = (
            "id",
            "user",
            "user_email",
            "role",
            "brokerage",
            "brokerage_detail",
            "name",
            "photo",
            "photo_url",
            "phone",
            "email",
            "job_title",
            "tagline",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "user_email",
            "role",
            "brokerage_detail",
            "photo_url",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {
            "brokerage": {"required": False, "allow_null": True},
        }

    def get_photo_url(self, obj: AgentProfile) -> str | None:
        return _file_url(obj.photo, self.context.get("request"))

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        user = getattr(request, "user", None)

        if user is None or not user.is_authenticated:
            return fields

        # An agent editing their own profile must not be able to reassign
        # themselves to another brokerage, or to another user account.
        if user.is_agent:
            fields["brokerage"].read_only = True
            fields["user"].read_only = True
        elif self.instance is not None:
            # Reassigning an existing profile to a different user account is
            # never meaningful; the link is created once.
            fields["user"].read_only = True

        return fields

    def validate_user(self, value: User):
        if AgentProfile.objects.filter(user=value).exists():
            raise serializers.ValidationError("This user already has an agent profile.")
        return value

    def validate_brokerage(self, value: Brokerage | None):
        """A Brokerage Admin may only place agents in brokerages they run."""
        request = self.context.get("request")
        user = getattr(request, "user", None)

        if value is None or user is None or not user.is_authenticated:
            return value
        if user.is_nehrux_admin:
            return value
        if user.is_brokerage_admin and not user.administered_brokerages.filter(
            pk=value.pk
        ).exists():
            raise serializers.ValidationError(
                "You can only assign agents to a brokerage you administer."
            )
        return value


class BrandKitSerializer(serializers.ModelSerializer):
    """Brand kit for an agent or a brokerage.

    The owner is set once, at creation, and never reassigned — moving a kit
    between owners would be a way to write to a record you do not control.
    """

    owner_type = serializers.CharField(read_only=True)
    owner_name = serializers.SerializerMethodField()

    class Meta:
        model = BrandKit
        fields = (
            "id",
            "agent",
            "brokerage",
            "owner_type",
            "owner_name",
            "name",
            "primary_color",
            "secondary_color",
            "accent_color",
            "heading_font",
            "body_font",
            "design_style",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "owner_type", "owner_name", "created_at", "updated_at")
        extra_kwargs = {
            "agent": {"required": False, "allow_null": True},
            "brokerage": {"required": False, "allow_null": True},
        }

    def get_owner_name(self, obj: BrandKit) -> str:
        return str(obj.owner) if obj.owner else ""

    def get_fields(self):
        fields = super().get_fields()
        if self.instance is not None:
            # Owner links are immutable after creation.
            fields["agent"].read_only = True
            fields["brokerage"].read_only = True
        return fields

    def validate(self, attrs: dict) -> dict:
        if self.instance is not None:
            return attrs

        agent = attrs.get("agent")
        brokerage = attrs.get("brokerage")

        # Mirrors the database CheckConstraint, so the client gets a 400 with a
        # readable message instead of a 500 from an IntegrityError.
        if bool(agent) == bool(brokerage):
            raise serializers.ValidationError(
                "A brand kit must belong to exactly one owner: set either "
                "'agent' or 'brokerage', not both and not neither."
            )

        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            raise serializers.ValidationError("Authentication required.")

        if user.is_nehrux_admin:
            return attrs

        if brokerage is not None:
            if not user.administered_brokerages.filter(pk=brokerage.pk).exists():
                raise serializers.ValidationError(
                    "You can only create a brand kit for a brokerage you administer."
                )
            return attrs

        # Agent-owned kit.
        if user.is_brokerage_admin:
            if not user.administered_brokerages.filter(
                pk=agent.brokerage_id or 0
            ).exists():
                raise serializers.ValidationError(
                    "You can only create a brand kit for an agent in your brokerage."
                )
            return attrs

        if agent.user_id != user.id:
            raise serializers.ValidationError(
                "You can only create a brand kit for your own profile."
            )
        return attrs
