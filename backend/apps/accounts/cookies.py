"""Refresh-token cookie handling.

=============================================================================
WHY THE REFRESH TOKEN LIVES IN AN httpOnly COOKIE
=============================================================================

Two tokens, two very different storage rules:

  * ACCESS token  — short-lived (minutes). Returned in the JSON response body
    and held **in memory only** by the browser (a JavaScript variable inside
    the React auth provider). It is sent on every API call as
    ``Authorization: Bearer <token>``. It is never written to localStorage or
    sessionStorage, so a page refresh loses it — that is intentional, and the
    frontend transparently gets a new one via the refresh endpoint.

  * REFRESH token — long-lived (days). Never touches JavaScript at all. It is
    set by the server as a cookie with the ``HttpOnly`` flag, which makes it
    unreadable from ``document.cookie``. The browser attaches it
    automatically, and only to the refresh/logout endpoints.

The threat being defended against is XSS. If an attacker manages to run
JavaScript on our origin, anything reachable from JS is compromised:

  - Token in localStorage  -> attacker exfiltrates a token valid for *days*
                              and can use it from their own machine, offline,
                              long after the victim closes the tab.
  - Token in httpOnly cookie -> attacker cannot read it. They can still make
                              requests *as* the user while their script runs
                              in the page, but they cannot steal a durable
                              credential and walk away with it.

That difference — "abuse confined to the live page" versus "permanent
credential theft" — is the whole point. It does not make XSS harmless; it caps
the blast radius.

-----------------------------------------------------------------------------
THE COOKIE FLAGS, AND WHAT EACH ONE STOPS
-----------------------------------------------------------------------------

``HttpOnly=True``
    Removes the cookie from ``document.cookie``. Stops JS exfiltration.
    Non-negotiable — this is the entire reason we use a cookie.

``Secure=<AUTH_COOKIE_SECURE>``
    Browser only sends the cookie over HTTPS. Stops passive network capture.
    MUST be True in production. Defaults to ``not DEBUG`` here so that plain
    ``http://localhost`` dev still works, and so a production deploy is secure
    unless someone explicitly opts out.

``SameSite=<AUTH_COOKIE_SAMESITE>``
    This is our CSRF defence. Because the browser attaches the cookie
    automatically, a POST to the refresh endpoint forged by another site would
    otherwise succeed. ``Lax`` means the cookie is not sent on cross-site POST
    requests, which blocks the forgery.

    In development the React app is served through the Vite proxy on the same
    origin as the API, so ``Lax`` works with no friction, and it stays correct
    in production when the SPA and API are served from the same site.

    If you ever deploy the SPA on a genuinely different site from the API you
    are forced to ``SameSite=None``, which requires ``Secure=True`` AND
    reintroduces CSRF exposure — at that point add a double-submit CSRF token
    (or an ``Origin`` header allowlist check) on the refresh endpoint. Do not
    set ``None`` casually.

``Path=<AUTH_COOKIE_PATH>``
    Scopes the cookie to ``/api/auth/`` so the browser does not attach a
    long-lived credential to every single API request. Fewer places it can
    leak (logs, proxies, ``Referer``-adjacent tooling), and less to get wrong.

``Domain=<AUTH_COOKIE_DOMAIN>``
    Left unset by default, which produces a host-only cookie — the safest
    option. Only set it if you genuinely need to share the cookie across
    subdomains, and understand that every subdomain then receives it.

-----------------------------------------------------------------------------
THE FULL FLOW
-----------------------------------------------------------------------------

  1. LOGIN     POST /api/auth/login/  {email, password}
               -> 200 {access, user}   + Set-Cookie: refresh_token=...; HttpOnly
               Frontend keeps `access` in a JS variable. It never sees the
               refresh token, and does not need to.

  2. API CALL  GET /api/auth/me/  with `Authorization: Bearer <access>`

  3. EXPIRY    Access token dies after ACCESS_TOKEN_LIFETIME -> API returns 401.

  4. REFRESH   POST /api/auth/refresh/  with an EMPTY body.
               The browser attaches the refresh cookie automatically; the
               server reads it from ``request.COOKIES``, not from the body.
               -> 200 {access}  + Set-Cookie: refresh_token=<new one>
               Rotation is on (ROTATE_REFRESH_TOKENS), and the old token is
               blacklisted (BLACKLIST_AFTER_ROTATION), so a stolen refresh
               token is single-use and its reuse fails.
               The frontend retries the original request with the new access
               token. All of this is invisible to the user.

  5. RELOAD    A page refresh wipes the in-memory access token. On boot the
               auth provider calls /api/auth/refresh/ once: if the cookie is
               still valid the session is restored, otherwise the user is
               shown the login page.

  6. LOGOUT    POST /api/auth/logout/
               Server blacklists the refresh token (so it is dead even if it
               was copied) and clears the cookie. The frontend drops the
               in-memory access token. The access token itself remains
               cryptographically valid until it expires — that is the accepted
               trade-off of stateless JWTs, and why its lifetime is minutes.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.response import Response


def set_refresh_cookie(response: Response, refresh_token: str) -> Response:
    """Attach the refresh token to ``response`` as an httpOnly cookie.

    ``max_age`` is deliberately tied to the token's own lifetime, so the
    browser drops the cookie at roughly the moment the token stops being
    accepted. The server never trusts ``max_age`` for security — the token's
    signed ``exp`` claim is the real expiry.
    """
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=refresh_token,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        httponly=True,  # invisible to document.cookie — the core protection
        secure=settings.AUTH_COOKIE_SECURE,  # HTTPS only (True in production)
        samesite=settings.AUTH_COOKIE_SAMESITE,  # CSRF defence
        path=settings.AUTH_COOKIE_PATH,  # only sent to the auth endpoints
        domain=settings.AUTH_COOKIE_DOMAIN or None,  # host-only when unset
    )
    return response


def clear_refresh_cookie(response: Response) -> Response:
    """Delete the refresh cookie.

    ``path`` and ``domain`` must match what was used when setting it, or the
    browser treats it as a different cookie and quietly keeps the original.
    """
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path=settings.AUTH_COOKIE_PATH,
        domain=settings.AUTH_COOKIE_DOMAIN or None,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    return response


def get_refresh_token(request) -> str | None:
    """Read the refresh token from the cookie.

    The refresh token is read *only* from the cookie — never from the request
    body or a header. Accepting it from the body as a fallback would hand any
    XSS payload a way to use a token it could not otherwise read, undoing the
    httpOnly guarantee.
    """
    return request.COOKIES.get(settings.AUTH_COOKIE_NAME)
