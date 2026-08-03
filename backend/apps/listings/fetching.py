"""Guarded outbound HTTP fetching for the listing import.

=============================================================================
THIS ENDPOINT MAKES THE SERVER FETCH A URL THE USER CHOSE
=============================================================================

That is server-side request forgery (SSRF) by construction, and the whole
value of this module is the restrictions it puts around it. Without them an
agent could paste:

    http://169.254.169.254/latest/meta-data/iam/...   cloud instance credentials
    http://localhost:8000/api/admin/platform-overview/  our own internal API
    http://10.0.0.5:6379/                               the Redis instance
    file:///etc/passwd                                  local files

...and the response would come back through our own privileged network
position. The defences, in order:

  1. **Scheme allowlist** — http and https only. Kills file://, gopher://,
     ftp://, and the redirect tricks built on them.
  2. **Address filtering** — the hostname is resolved and *every* address it
     maps to is checked. Loopback, private, link-local (including the cloud
     metadata range), reserved, multicast and unspecified addresses are all
     refused. An allowlist of address *kinds* is the wrong model here; only
     globally routable public addresses pass.
  3. **Manual redirect handling** — redirects are followed one hop at a time
     and each hop is re-validated. Letting the HTTP library follow them would
     mean a public URL could bounce to 127.0.0.1 after the check had passed.
  4. **Size and time limits** — the response is streamed and abandoned past a
     byte ceiling, with a short connect/read timeout, so a slow or endless
     body cannot tie up a worker.
  5. **Content-type allowlist** — only what we can actually parse.
  6. **No credentials** — no cookies, no auth headers, no proxy auth. The
     fetch carries none of our identity.

KNOWN RESIDUAL RISK — DNS REBINDING
-----------------------------------
Between our ``getaddrinfo`` check and the socket the HTTP library opens, a
hostile DNS server can change the answer to a private address (a TOCTOU
window). Closing it properly means pinning the validated IP for the actual
connection, which conflicts with TLS SNI and certificate validation unless a
custom transport adapter is used.

For a deployment that matters, the right control is at the network edge, not
here: run this fetch through an egress proxy or in a network namespace with no
route to internal ranges. That is defence the application layer cannot fake.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

import requests

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_REDIRECTS = 3
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 10
MAX_HTML_BYTES = 3 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
CHUNK_SIZE = 64 * 1024

HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
IMAGE_CONTENT_TYPES = ("image/jpeg", "image/png", "image/webp")

# A plain, honest user agent. Pretending to be a browser to evade blocking
# would be a decision for the site owner to make, not us.
USER_AGENT = "RealEstateListingImporter/1.0 (+one-off import, agent triggered)"


class UnsafeUrlError(Exception):
    """The URL points somewhere we refuse to fetch from."""


class FetchError(Exception):
    """The URL could not be fetched (network error, timeout, bad status)."""


@dataclass
class FetchedDocument:
    url: str
    content_type: str
    content: bytes

    @property
    def text(self) -> str:
        # Listing pages are frequently mislabelled or unlabelled; replacing
        # undecodable bytes is better than failing the whole import.
        return self.content.decode("utf-8", errors="replace")


def _is_public_address(raw_address: str) -> bool:
    try:
        address = ipaddress.ip_address(raw_address)
    except ValueError:
        return False

    # is_global is the positive test; the rest are belt and braces for
    # ranges whose classification differs between Python versions.
    return address.is_global and not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def assert_fetchable(url: str) -> str:
    """Validate ``url`` and return it normalised, or raise ``UnsafeUrlError``."""
    if not url or len(url) > 2000:
        raise UnsafeUrlError("Enter a valid URL.")

    parsed = urlparse(url.strip())

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeUrlError("Only http:// and https:// URLs can be imported.")

    if not parsed.hostname:
        raise UnsafeUrlError("That URL has no hostname.")

    # Credentials in the URL (http://user:pass@host) are a classic way to
    # confuse parsers about which host is really being contacted.
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URLs containing credentials are not supported.")

    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or None)
    except socket.gaierror as exc:
        raise UnsafeUrlError("That hostname could not be resolved.") from exc

    resolved = {info[4][0] for info in addresses}
    if not resolved:
        raise UnsafeUrlError("That hostname could not be resolved.")

    # EVERY address must be public. A hostname resolving to both a public and
    # a private address is a deliberate attack pattern, not a misconfiguration
    # we should be lenient about.
    for address in resolved:
        if not _is_public_address(address):
            raise UnsafeUrlError(
                "That URL resolves to a private or internal address, which "
                "cannot be imported."
            )

    return urlunparse(parsed)


def fetch_document(
    url: str,
    *,
    allowed_content_types: tuple[str, ...] = HTML_CONTENT_TYPES,
    max_bytes: int = MAX_HTML_BYTES,
) -> FetchedDocument:
    """Fetch ``url``, following redirects one validated hop at a time."""
    current = assert_fetchable(url)

    session = requests.Session()
    # Never inherit ambient proxy configuration or credentials.
    session.trust_env = False

    try:
        for _hop in range(MAX_REDIRECTS + 1):
            try:
                response = session.get(
                    current,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": ", ".join(allowed_content_types) + ", */*;q=0.1",
                    },
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                    # Redirects are handled here so each hop is re-validated.
                    allow_redirects=False,
                    stream=True,
                )
            except requests.RequestException as exc:
                logger.info("Listing import fetch failed for %r: %s", current, exc)
                raise FetchError("The page could not be reached.") from exc

            with response:
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get("Location")
                    if not location:
                        raise FetchError("The page redirected without a target.")
                    # Re-validate: a public URL is allowed to redirect, but not
                    # to somewhere we would have refused in the first place.
                    current = assert_fetchable(requests.compat.urljoin(current, location))
                    continue

                if response.status_code >= 400:
                    raise FetchError(
                        f"The page returned HTTP {response.status_code}."
                    )

                content_type = (
                    response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                )
                if content_type and not content_type.startswith(allowed_content_types):
                    raise FetchError(
                        f"Unsupported content type '{content_type}'."
                    )

                # Trust the declared length only as an early exit; the real
                # limit is enforced while reading, because the header lies.
                declared = response.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise FetchError("The page is too large to import.")

                chunks: list[bytes] = []
                total = 0
                try:
                    for chunk in response.iter_content(CHUNK_SIZE):
                        total += len(chunk)
                        if total > max_bytes:
                            raise FetchError("The page is too large to import.")
                        chunks.append(chunk)
                except requests.RequestException as exc:
                    raise FetchError("The page could not be read.") from exc

                return FetchedDocument(
                    url=current,
                    content_type=content_type,
                    content=b"".join(chunks),
                )

        raise FetchError("Too many redirects.")
    finally:
        session.close()


def fetch_image(url: str) -> FetchedDocument:
    """Fetch a remote image through the same guards."""
    return fetch_document(
        url,
        allowed_content_types=IMAGE_CONTENT_TYPES,
        max_bytes=MAX_IMAGE_BYTES,
    )
