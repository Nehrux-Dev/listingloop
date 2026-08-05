"""Spam protection for the public enquiry form.

An unauthenticated POST endpoint that stores text and emails is a spam magnet.
The defences are layered, because each one alone is weak and together they stop
almost everything without putting a CAPTCHA in front of a real buyer:

  1. RATE LIMIT — DRF throttling per IP (the `enquiry` scope). Blunt, and the
     only one that helps against volume.
  2. HONEYPOT — a form field a human never sees and never fills in. Bots fill
     every field they find.
  3. TIMING — the form is issued with a signed timestamp. A submission that
     arrives implausibly fast was not typed by a person; one that arrives days
     later is a replayed token.
  4. CONTENT HEURISTICS — link stuffing, all-caps shouting, spam vocabulary.
  5. DUPLICATE SUPPRESSION — the same message to the same listing twice in a
     few minutes is a retry loop or a bot.

FLAGGED, NOT DISCARDED
----------------------
A submission that trips a check is stored with ``status = SPAM`` and the
reasons, not thrown away. The expensive failure here is not "some spam reaches
an inbox" — it is a false positive silently binning a real buyer's enquiry
about a $2m house. The agent can see the spam folder; nobody can see a deleted
row.

The one exception is the honeypot, which no human can trip: filling a hidden
field is unambiguous, so that submission is rejected outright rather than
stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.utils import timezone

#: Namespaced so a token minted for this form cannot be replayed at another.
FORM_SIGNER_SALT = "listings.enquiry-form"

#: Below this, the "user" did not read the page. Tunable without a deploy,
#: because the right threshold depends on how much form there is to fill in —
#: and because setting it to 0 is the only sane way to test everything else.
def min_fill_seconds() -> float:
    return getattr(settings, "ENQUIRY_MIN_FILL_SECONDS", 3)
#: Above this, the token is stale — the page was left open for a day, or the
#: token was harvested for later reuse.
MAX_FORM_AGE_SECONDS = 60 * 60 * 6

URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)

#: Deliberately short and unambiguous. A long list of "suspicious" words would
#: catch ordinary buyers asking ordinary questions.
SPAM_VOCABULARY = (
    "seo services",
    "guest post",
    "backlink",
    "crypto",
    "bitcoin",
    "casino",
    "viagra",
    "loan offer",
    "work from home",
    "increase your traffic",
    "rank #1",
    "digital marketing agency",
)


@dataclass
class SpamAssessment:
    reasons: list[str] = field(default_factory=list)
    #: True only for signals a human cannot produce. Everything else is stored
    #: and flagged rather than refused.
    reject_outright: bool = False

    @property
    def is_spam(self) -> bool:
        return bool(self.reasons)

    def add(self, reason: str, *, reject: bool = False) -> None:
        self.reasons.append(reason)
        if reject:
            self.reject_outright = True


def issue_form_token() -> str:
    """A signed timestamp handed out with the public listing payload."""
    return TimestampSigner(salt=FORM_SIGNER_SALT).sign("enquiry")


def check_form_token(token: str | None) -> str | None:
    """Return a reason string if the token is wrong, else None."""
    if not token:
        return "The form token was missing."

    signer = TimestampSigner(salt=FORM_SIGNER_SALT)
    try:
        signer.unsign(token, max_age=timedelta(seconds=MAX_FORM_AGE_SECONDS))
    except SignatureExpired:
        return "The form was left open too long. Please reload and try again."
    except BadSignature:
        return "The form token was not valid."
    return None


def form_age_seconds(token: str) -> float | None:
    """How long ago the token was issued, or None if it cannot be read."""
    signer = TimestampSigner(salt=FORM_SIGNER_SALT)
    try:
        # max_age is deliberately generous here; the caller has already
        # validated freshness. This is only reading the timestamp back.
        signer.unsign(token, max_age=timedelta(seconds=MAX_FORM_AGE_SECONDS))
    except (BadSignature, SignatureExpired):
        return None

    try:
        timestamp = token.rsplit(":", 2)[-2]
        from django.core.signing import b62_decode

        issued_at = b62_decode(timestamp)
    except Exception:
        return None

    return timezone.now().timestamp() - issued_at


def assess(
    *,
    name: str,
    email: str,
    phone: str,
    message: str,
    honeypot: str | None,
    form_token: str | None,
    listing=None,
    ip_address: str | None = None,
) -> SpamAssessment:
    """Score one submission. Returns the reasons it looks like spam."""
    assessment = SpamAssessment()

    # 1. Honeypot — no human can fill a field they cannot see.
    if honeypot:
        assessment.add("A hidden field was filled in.", reject=True)
        return assessment

    # 2. Token validity and timing.
    token_problem = check_form_token(form_token)
    if token_problem:
        assessment.add(token_problem)
    else:
        minimum = min_fill_seconds()
        age = form_age_seconds(form_token or "")
        if minimum and age is not None and age < minimum:
            assessment.add(
                f"The form was submitted {age:.1f}s after loading, which is faster "
                f"than a person can type."
            )

    # 3. Content heuristics.
    body = f"{name} {message}"
    link_count = len(URL_RE.findall(body))
    if link_count >= 2:
        assessment.add(f"The message contains {link_count} links.")

    lowered = body.lower()
    hits = [word for word in SPAM_VOCABULARY if word in lowered]
    if hits:
        assessment.add("The message contains marketing spam vocabulary: " + ", ".join(hits))

    letters = [char for char in message if char.isalpha()]
    if len(letters) > 25 and sum(char.isupper() for char in letters) / len(letters) > 0.7:
        assessment.add("The message is almost entirely capitals.")

    if not email and not phone:
        # Not spam in itself, but an enquiry nobody can answer.
        assessment.add("No way to reply was given.")

    # 4. Duplicate suppression.
    if listing is not None and ip_address:
        from apps.listings.models import Enquiry

        window = timezone.now() - timedelta(minutes=10)
        if Enquiry.objects.filter(
            listing=listing,
            ip_address=ip_address,
            message=message,
            created_at__gte=window,
        ).exists():
            assessment.add("An identical message was sent about this listing minutes ago.")

    return assessment


def client_ip(request) -> str | None:
    """Best-effort client IP.

    ``X-Forwarded-For`` is only consulted when the deployment says it is behind
    a trusted proxy — otherwise any client could spoof the header and walk
    straight through the per-IP rate limit.
    """
    if getattr(settings, "TRUST_PROXY_HEADERS", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
