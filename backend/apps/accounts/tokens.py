"""Token issuance helpers."""

from __future__ import annotations

from rest_framework_simplejwt.tokens import RefreshToken


def build_tokens_for_user(user) -> tuple[str, str]:
    """Return ``(access_token, refresh_token)`` for ``user``.

    ``role`` and ``email`` are embedded as custom claims so a permission check
    could be made without a database round trip. Claims are a *snapshot* taken
    at issue time: if an admin changes someone's role, the old access token
    still carries the old role until it expires — which is why access tokens
    are short-lived and why ``apps.accounts.permissions`` reads
    ``request.user.role`` from the database rather than the claim.

    Nothing secret belongs in a JWT payload: it is signed, not encrypted, and
    anyone holding the token can base64-decode and read it.
    """
    refresh = RefreshToken.for_user(user)
    refresh["email"] = user.email
    refresh["role"] = user.role

    # The access token is derived from the refresh token and inherits its
    # custom claims.
    return str(refresh.access_token), str(refresh)
