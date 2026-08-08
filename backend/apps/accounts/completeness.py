"""Profile completeness — one reusable check, enforced where it matters.

=============================================================================
NOTHING HERE IS COLLECTED AT SIGN-UP
=============================================================================

Registration asks for a name, an email and a password. Every field below is
optional, nullable, and filled in from Settings whenever the agent gets round
to it. An agent evaluating the product — or waiting on their brokerage to
approve the spend — is not stopped on day one by a licence-number box.

The rest is collected contextually: this module says what is missing, the
dashboard offers it as a dismissible prompt, and the export path is the only
thing that actually insists (see apps/templates/readiness.py).

=============================================================================
WHY THIS IS NOT JUST A PROGRESS BAR
=============================================================================

Two different questions, and conflating them is how an agent ends up with a
listing card that has a blank rectangle where their brokerage logo should be:

  COMPLETION  — how much of the reusable profile is filled in. A percentage,
                shown on the dashboard, purely informational. Dismissible.

  READINESS   — whether the specific fields a marketing asset *needs* are
                present. A hard check, run before rendering, that names what is
                missing instead of rendering an empty element.

An agent can be at 80% and still be ready, or at 90% and not — because the
missing 10% might be the brokerage logo. So readiness is computed from a
declared requirement list, not from the percentage.

WHAT COUNTS AS REQUIRED IS DATA, NOT CODE
-----------------------------------------
``REQUIRED_FOR_MARKETING`` is a list of checks. Adding a requirement means
adding an entry, not editing a rendering path — the same reasoning as the
compliance engine. Each entry knows how to find its value, what to call it in a
message, and which Settings screen fixes it, so every message can link straight
there instead of saying "something is missing".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ProfileField:
    key: str
    label: str
    #: Which Settings area owns it, so every message can deep-link the fix.
    step: str
    getter: Callable[[Any], Any]
    #: Required to generate marketing, as opposed to merely nice to have.
    required_for_marketing: bool = True
    hint: str = ""

    def value(self, profile) -> Any:
        try:
            return self.getter(profile)
        except Exception:
            return None

    def is_present(self, profile) -> bool:
        value = self.value(profile)
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        # An ImageField is falsey when empty, which is what we want.
        return bool(value)


def _brokerage(profile):
    return profile.brokerage


def _brand_kit(profile):
    """The agent's own kit, falling back to their brokerage's.

    Matches how the renderer resolves branding, so completion cannot claim a
    brand is missing when the render would have found one.
    """
    kit = getattr(profile, "brand_kit", None)
    if kit is not None:
        return kit
    brokerage = profile.brokerage
    return getattr(brokerage, "brand_kit", None) if brokerage else None


#: Everything the profile can hold. Order matters: it is the order shown.
PROFILE_FIELDS: tuple[ProfileField, ...] = (
    # -- Settings > Your profile ---------------------------------------------
    ProfileField(
        "agent_name", "Your name", "profile",
        lambda p: p.name or p.user.full_name,
        hint="Shown on every marketing asset.",
    ),
    ProfileField(
        "agent_photo", "Profile photo", "profile", lambda p: p.photo,
        hint="Used in the agent block on listing cards.",
    ),
    ProfileField(
        "agent_phone", "Professional phone", "profile", lambda p: p.phone,
    ),
    ProfileField(
        "agent_email", "Professional email", "profile",
        lambda p: p.email or p.user.email,
    ),
    ProfileField(
        "job_title", "Job title", "profile", lambda p: p.job_title,
        required_for_marketing=False,
    ),
    ProfileField(
        "tagline", "Tagline", "profile", lambda p: p.tagline,
        required_for_marketing=False,
    ),
    ProfileField(
        "licence_number", "Licence number", "profile", lambda p: p.licence_number,
        # Not universally required — a jurisdiction question, not a code one.
        required_for_marketing=False,
        hint="Where your jurisdiction requires it on marketing material.",
    ),
    # -- Settings > Brokerage ------------------------------------------------
    ProfileField(
        "brokerage", "Brokerage", "brokerage",
        lambda p: _brokerage(p),
        hint="Marketing material has to say who publishes it.",
    ),
    ProfileField(
        "brokerage_logo", "Brokerage logo", "brokerage",
        lambda p: _brokerage(p).logo if _brokerage(p) else None,
    ),
    ProfileField(
        "brokerage_disclaimer", "Required disclaimer", "brokerage",
        lambda p: _brokerage(p).required_disclaimer if _brokerage(p) else None,
        hint="The compliance text that must appear on your material.",
    ),
    # -- Settings > Brand kit ------------------------------------------------
    ProfileField(
        "brand_colours", "Brand colours", "brand",
        lambda p: (_brand_kit(p).primary_color if _brand_kit(p) else None),
    ),
    ProfileField(
        "brand_font", "Brand font", "brand",
        lambda p: (_brand_kit(p).heading_font if _brand_kit(p) else None),
        required_for_marketing=False,
    ),
    ProfileField(
        "design_style", "Preferred design style", "brand",
        lambda p: (_brand_kit(p).design_style if _brand_kit(p) else None),
        required_for_marketing=False,
    ),
)

REQUIRED_FOR_MARKETING = tuple(
    field for field in PROFILE_FIELDS if field.required_for_marketing
)

STEP_LABELS = {
    "profile": "Your profile",
    "brokerage": "Brokerage",
    "brand": "Brand kit",
}

#: Which Settings screen fixes each area. These are frontend routes, which is a
#: small coupling accepted on purpose: "the required disclaimer is missing" is
#: not actionable, and every caller that reports a gap would otherwise have to
#: reinvent the same mapping.
STEP_PATHS = {
    "profile": "/profile",
    "brokerage": "/brokerage",
    "brand": "/brand-kit",
}


def fix_path_for(step: str, profile=None) -> str:
    """Where to send someone to fill in a missing field.

    The brokerage case is not a constant. An agent with no brokerage at all
    cannot go to /brokerage — that screen administers a brokerage you are
    already in, and the guard would bounce them. Joining or creating one lives
    on the profile screen, so that is where the link has to point until they
    have one.
    """
    if step == "brokerage" and (profile is None or profile.brokerage_id is None):
        return STEP_PATHS["profile"]
    return STEP_PATHS.get(step, "/profile")


def assess_profile(profile) -> dict:
    """Completion and readiness for one agent profile."""
    if profile is None:
        return {
            "completion_percent": 0,
            "is_complete": False,
            "ready_for_marketing": False,
            "fields": [],
            "missing_required": [],
            "missing_optional": [],
            "by_step": {},
        }

    rows = []
    for field in PROFILE_FIELDS:
        present = field.is_present(profile)
        rows.append(
            {
                "key": field.key,
                "label": field.label,
                "step": field.step,
                "step_label": STEP_LABELS.get(field.step, field.step),
                "fix_path": fix_path_for(field.step, profile),
                "present": present,
                "required_for_marketing": field.required_for_marketing,
                "hint": field.hint,
            }
        )

    # The percentage counts every field, required or not — it answers "how much
    # of my profile is filled in", which is not the same question as "can I
    # publish", and pretending otherwise makes a 100% badge misleading.
    present_count = sum(1 for row in rows if row["present"])
    percent = round(present_count / len(rows) * 100) if rows else 0

    missing_required = [row for row in rows if row["required_for_marketing"] and not row["present"]]
    missing_optional = [
        row for row in rows if not row["required_for_marketing"] and not row["present"]
    ]

    by_step: dict[str, dict] = {}
    for step, label in STEP_LABELS.items():
        step_rows = [row for row in rows if row["step"] == step]
        done = sum(1 for row in step_rows if row["present"])
        by_step[step] = {
            "label": label,
            "total": len(step_rows),
            "present": done,
            "complete": done == len(step_rows),
        }

    return {
        "completion_percent": percent,
        "is_complete": present_count == len(rows),
        "ready_for_marketing": not missing_required,
        "fields": rows,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "by_step": by_step,
    }


class ProfileIncompleteError(Exception):
    """Raised when an asset cannot be generated because data is missing.

    Carries the field list so the caller can tell the agent exactly what to
    fill in and where — "your profile is incomplete" is not an actionable
    message.
    """

    def __init__(self, missing: list[dict]) -> None:
        self.missing = missing
        names = ", ".join(row["label"] for row in missing)
        super().__init__(
            f"Your profile is missing information needed for marketing material: {names}."
        )

    def as_dict(self) -> dict:
        return {
            "detail": str(self),
            "missing": self.missing,
            "steps": sorted({row["step"] for row in self.missing}),
        }


def require_marketing_ready(profile) -> None:
    """Raise unless ``profile`` has everything a marketing asset needs.

    Called before rendering. The alternative — rendering anyway — produces an
    asset with a blank space where the brokerage logo should be, which an agent
    may not notice until it is published.
    """
    assessment = assess_profile(profile)
    if not assessment["ready_for_marketing"]:
        raise ProfileIncompleteError(assessment["missing_required"])
