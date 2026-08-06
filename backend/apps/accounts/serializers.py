"""Serializers for registration, login and user representation."""

from __future__ import annotations

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.accounts.models import SELF_ASSIGNABLE_ROLES, Role

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Public representation of a user. Never includes the password hash."""

    role_display = serializers.CharField(source="get_role_display", read_only=True)
    administers_brokerage = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "role",
            "role_display",
            "administers_brokerage",
            "is_active",
            "date_joined",
        )
        read_only_fields = fields

    def get_administers_brokerage(self, user) -> bool:
        """Whether this user administers any brokerage, regardless of role.

        An agent who created their firm during onboarding administers it while
        remaining an Agent. The frontend needs to know, or it would hide the
        Brokerage screen from the one person able to fill in the logo and
        disclaimer their own exports are blocked on. It is a boolean, not a
        list of ids: which brokerages is the server's business.
        """
        return user.administered_brokerages.exists()


class RegisterSerializer(serializers.ModelSerializer):
    """Self-service registration — step 1 of agent onboarding.

    Only ``SELF_ASSIGNABLE_ROLES`` may be requested here. Allowing a caller to
    name their own role would let anyone register as a Nehrux Admin.

    ``password_confirm`` is write-only and popped before the model is touched,
    so it is never persisted anywhere. The password itself goes through
    ``create_user``, which hashes with the configured PASSWORD_HASHERS.
    """

    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    password_confirm = serializers.CharField(
        write_only=True, style={"input_type": "password"}
    )
    role = serializers.ChoiceField(
        choices=[(role, Role(role).label) for role in SELF_ASSIGNABLE_ROLES],
        default=Role.AGENT,
    )
    # Registration asks for the parts; `full_name` is derived on save. Sent
    # optionally so an existing client posting full_name still works.
    first_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=120, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = (
            "email",
            "first_name",
            "last_name",
            "full_name",
            "password",
            "password_confirm",
            "role",
        )
        extra_kwargs = {"full_name": {"required": False}}


    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_password(self, value: str) -> str:
        # Runs Django's AUTH_PASSWORD_VALIDATORS (length, common passwords, ...).
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def validate(self, attrs: dict) -> dict:
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError(
                {"password_confirm": "The two password fields do not match."}
            )

        # A name is required, but either shape is accepted: the onboarding UI
        # sends first/last, and full_name remains valid for any other caller.
        if not any(
            (attrs.get("first_name"), attrs.get("last_name"), attrs.get("full_name"))
        ):
            raise serializers.ValidationError(
                {"first_name": "Please give your first and last name."}
            )
        return attrs

    def create(self, validated_data: dict) -> User:
        # Popped, never stored — it exists only to catch a typo in the form.
        validated_data.pop("password_confirm", None)
        password = validated_data.pop("password")
        # create_user hashes via PASSWORD_HASHERS; the raw value is never saved.
        return User.objects.create_user(password=password, **validated_data)


class LoginSerializer(serializers.Serializer):
    """Validates credentials and returns the matching user in ``validated_data``."""

    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True, style={"input_type": "password"}, trim_whitespace=False
    )

    def validate(self, attrs: dict) -> dict:
        # `authenticate` also rejects inactive users (ModelBackend runs
        # user_can_authenticate), and it hashes the supplied password even for
        # unknown e-mails so response timing does not reveal which accounts
        # exist.
        user = authenticate(
            request=self.context.get("request"),
            username=attrs["email"].strip().lower(),
            password=attrs["password"],
        )

        if user is None:
            # One generic message for "no such user" and "wrong password" —
            # never confirm that an e-mail is registered.
            raise serializers.ValidationError(
                {"detail": "Invalid email or password."}, code="authorization"
            )

        attrs["user"] = user
        return attrs
