"""Authentication endpoints.

    POST /api/auth/register/   create an account, log in immediately
    POST /api/auth/login/      exchange credentials for tokens
    POST /api/auth/refresh/    new access token, using the httpOnly cookie
    POST /api/auth/logout/     blacklist the refresh token, clear the cookie
    GET  /api/auth/me/         the authenticated user

Plus two role-gated example endpoints used to demonstrate and test the
permission classes.

The access token is returned in the JSON body (the SPA keeps it in memory);
the refresh token is *only* ever sent as an httpOnly cookie and is never
included in a response body. See ``apps.accounts.cookies`` for the full
rationale.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import update_last_login
from django.db.models import Count
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.cookies import (
    clear_refresh_cookie,
    get_refresh_token,
    set_refresh_cookie,
)
from apps.accounts.models import Role
from apps.accounts.permissions import IsBrokerageAdminOrAbove, IsNehruxAdmin
from apps.accounts.serializers import (
    LoginSerializer,
    RegisterSerializer,
    UserSerializer,
)
from apps.accounts.tokens import build_tokens_for_user

User = get_user_model()


def _auth_response(user, status_code: int = status.HTTP_200_OK) -> Response:
    """Build the standard authenticated response.

    Body: the access token + the user. Cookie: the refresh token.
    The refresh token deliberately never appears in the body — if it did, the
    frontend's JavaScript would be able to read it, which is exactly what the
    httpOnly cookie exists to prevent.
    """
    access_token, refresh_token = build_tokens_for_user(user)
    response = Response(
        {"access": access_token, "user": UserSerializer(user).data},
        status=status_code,
    )
    return set_refresh_cookie(response, refresh_token)


class RegisterView(GenericAPIView):
    """``POST /api/auth/register/`` — create an account and log in."""

    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return _auth_response(user, status_code=status.HTTP_201_CREATED)


class LoginView(GenericAPIView):
    """``POST /api/auth/login/`` — exchange email + password for tokens.

    Throttled per IP: a login endpoint is the front door for credential
    stuffing, so it should never accept unlimited attempts.
    """

    serializer_class = LoginSerializer
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        # `authenticate()` does not touch last_login (only `login()` does), and
        # we never create a session — so record it here.
        update_last_login(None, user)
        return _auth_response(user)


class TokenRefreshView(APIView):
    """``POST /api/auth/refresh/`` — mint a new access token.

    The request body is empty. The refresh token is read from the httpOnly
    cookie the browser attaches automatically — never from the body, so a
    hijacked JS context cannot supply one it stole from elsewhere.

    ``ROTATE_REFRESH_TOKENS`` + ``BLACKLIST_AFTER_ROTATION`` mean every
    refresh issues a *new* refresh token and kills the old one, so a leaked
    refresh token is usable at most once, and its reuse is detectable.
    """

    permission_classes = [AllowAny]  # the cookie *is* the credential here
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request: Request) -> Response:
        raw_token = get_refresh_token(request)
        if not raw_token:
            return Response(
                {"detail": "Refresh cookie not found."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            refresh = RefreshToken(raw_token)
        except TokenError:
            # Expired, malformed, or already blacklisted. Clear the dead
            # cookie so the browser stops sending it.
            response = Response(
                {"detail": "Refresh token is invalid or expired."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            return clear_refresh_cookie(response)

        user = User.objects.filter(id=refresh.get("user_id")).first()
        if user is None or not user.is_active:
            # The account was deleted or deactivated after the token was
            # issued. A signed token is not enough — the user must still exist
            # and be allowed in.
            response = Response(
                {"detail": "User is inactive or no longer exists."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            return clear_refresh_cookie(response)

        try:
            # Rotation: invalidate the token that was just presented so it
            # cannot be replayed.
            refresh.blacklist()
        except AttributeError:  # pragma: no cover - blacklist app not installed
            pass

        # Fresh pair, with claims re-read from the database so a role change
        # takes effect on the next refresh.
        return _auth_response(user)


class LogoutView(APIView):
    """``POST /api/auth/logout/`` — end the session.

    Deliberately ``AllowAny``: logging out must work even when the access
    token has already expired. Authority comes from the refresh cookie.

    Always returns 205 — an unauthenticated logout is not an error, and
    reporting "you were not logged in" would leak session state.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request: Request) -> Response:
        raw_token = get_refresh_token(request)

        if raw_token:
            try:
                # Blacklisting matters: without it, a refresh token copied
                # before logout would keep working for days.
                RefreshToken(raw_token).blacklist()
            except TokenError:
                # Already expired or blacklisted — nothing left to revoke.
                pass

        response = Response(status=status.HTTP_205_RESET_CONTENT)
        # Note: the *access* token stays valid until it expires. Stateless
        # JWTs cannot be recalled, which is why the lifetime is minutes.
        return clear_refresh_cookie(response)


class MeView(APIView):
    """``GET /api/auth/me/`` — the authenticated user.

    The SPA calls this after boot to learn who it is talking to and, crucially,
    which role to render. Client-side role checks are UX only; the server
    enforces the real boundary on every request.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(UserSerializer(request.user).data)


# ---------------------------------------------------------------------------
# Role-gated example endpoints
# ---------------------------------------------------------------------------


class PlatformOverviewView(APIView):
    """``GET /api/admin/platform-overview/`` — Nehrux Admins only.

    Agents and Brokerage Admins get 403 here.
    """

    permission_classes = [IsNehruxAdmin]

    def get(self, request: Request) -> Response:
        counts = {row["role"]: row["total"] for row in User.objects.values("role").annotate(total=Count("id"))}
        return Response(
            {
                "scope": "platform",
                "total_users": User.objects.count(),
                "users_by_role": {role.value: counts.get(role.value, 0) for role in Role},
            }
        )


class BrokerageOverviewView(APIView):
    """``GET /api/admin/brokerage-overview/`` — Brokerage Admins and above.

    Demonstrates the hierarchical permission: a Nehrux Admin passes this too,
    an Agent does not.
    """

    permission_classes = [IsBrokerageAdminOrAbove]

    def get(self, request: Request) -> Response:
        return Response(
            {
                "scope": "brokerage",
                "requested_by": request.user.email,
                "role": request.user.role,
            }
        )
