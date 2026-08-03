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

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "full_name",
            "role",
            "role_display",
            "is_active",
            "date_joined",
        )
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    """Self-service registration.

    Only ``SELF_ASSIGNABLE_ROLES`` may be requested here. Allowing a caller to
    name their own role would let anyone register as a Nehrux Admin.
    """

    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    password_confirm = serializers.CharField(
        write_only=True, style={"input_type": "password"}
    )
    role = serializers.ChoiceField(
        choices=[(role, Role(role).label) for role in SELF_ASSIGNABLE_ROLES],
        default=Role.AGENT,
    )

    class Meta:
        model = User
        fields = ("email", "full_name", "password", "password_confirm", "role")

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
        return attrs

    def create(self, validated_data: dict) -> User:
        validated_data.pop("password_confirm", None)
        password = validated_data.pop("password")
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
