"""Is this particular design ready to export?

WHY THIS IS PER-DESIGN, NOT PER-PROFILE
---------------------------------------
The obvious implementation is "does the agent have every field filled in".
That is wrong, and annoyingly so: it would block a Diwali card because the
agent has not uploaded a listing photo, and block a listing card because they
have not written a tagline.

The requirement is *"if this design shows X and X is missing"* — so the design
is the source of truth. This walks the design's own elements, resolves each one
exactly as the renderer will, and reports the ones that would come out empty. A
design that shows no brokerage logo cannot be blocked for the want of one, and
an agent who deleted that element has said as much.

WHAT COUNTS AS BLOCKING
-----------------------
An element blocks the export when it resolves to nothing AND it draws on
agent / brokerage / brand data — the reusable information the profile exists
to hold.

The template's old ``required`` constraint is no longer consulted: a design
owns its elements, so a template cannot declare that one of them must survive.
What remains is stronger for being simpler — if the design *shows* a field, it
has to have something to show.

This is where a missing disclaimer is actually caught. Not at sign-up: an
agent who has not yet named their brokerage can still create an account, add
listings and explore the template library. The requirement only bites at the
moment it becomes real, which is the moment something is about to be published,
and it arrives with a link to the screen that fixes it.

Elements drawing on *listing* data are deliberately excluded. A listing with no
photo is a listing problem, and the verification gate from Step 4 already
governs that; reporting it here would send the agent to the wrong screen.

Hidden elements are skipped: an agent who turned something off has already
decided it is not needed.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.accounts.completeness import fix_path_for
from apps.templates.html_builder import resolve_content, unresolved_placeholders

#: content_source prefix -> (label shown to the agent, Settings area)
SOURCE_LABELS: dict[str, tuple[str, str]] = {
    "agent.photo": ("Profile photo", "profile"),
    "agent.name": ("Your name", "profile"),
    "agent.full_name": ("Your name", "profile"),
    "agent.phone": ("Professional phone", "profile"),
    "agent.email": ("Professional email", "profile"),
    "agent.job_title": ("Job title", "profile"),
    "agent.tagline": ("Tagline", "profile"),
    "agent.licence_number": ("Licence number", "profile"),
    "brokerage.name": ("Brokerage name", "brokerage"),
    "brokerage.logo": ("Brokerage logo", "brokerage"),
    "brokerage.disclaimer": ("Required disclaimer", "brokerage"),
    "brokerage.required_disclaimer": ("Required disclaimer", "brokerage"),
    "brokerage.phone": ("Brokerage phone", "brokerage"),
    "brokerage.website": ("Brokerage website", "brokerage"),
    "brand.primary_color": ("Brand colours", "brand"),
    "brand_kit.primary_color": ("Brand colours", "brand"),
}

STEP_LABELS = {
    "profile": "Your profile",
    "brokerage": "Brokerage",
    "brand": "Brand kit",
    "listing": "The listing",
}

#: Sources that are the agent's reusable profile rather than the property.
PROFILE_PREFIXES = ("agent.", "brokerage.", "brand.", "brand_kit.")


@dataclass
class MissingElement:
    element_key: str
    label: str
    step: str
    #: Where to send the agent. Carried per item rather than derived by the
    #: caller, because the brokerage case depends on whether they have one yet.
    fix_path: str = "/profile"

    def as_dict(self) -> dict:
        return {
            "element": self.element_key,
            "label": self.label,
            "step": self.step,
            "step_label": STEP_LABELS.get(self.step, self.step),
            "fix_path": self.fix_path,
        }


def _describe(source: str, element: dict) -> tuple[str, str]:
    if source in SOURCE_LABELS:
        return SOURCE_LABELS[source]

    # An unmapped source still gets a usable message rather than a key name,
    # and — more importantly — is attributed to the right screen. Sending an
    # agent to Brokerage settings to fix a missing listing photo is worse than
    # a vague message, because they will look and find nothing wrong.
    label = element.get("name") or "Element"
    if source.startswith(("listing.", "property.")):
        step = "listing"
    elif source.startswith("agent."):
        step = "profile"
    elif source.startswith(("brand.", "brand_kit.")):
        step = "brand"
    elif source.startswith("brokerage."):
        step = "brokerage"
    else:
        # No source at all — a required element with only literal content.
        step = "profile"
    return label, step


def _fix_path(step: str, design) -> str:
    """The screen that fixes a gap, as a link the refusal can offer directly.

    "The required disclaimer is missing" is not actionable on its own — the
    agent has to work out which of four screens owns it. The listing case
    resolves to that listing's own editor rather than the list.
    """
    if step == "listing":
        return f"/listings/{design.listing_id}" if design.listing_id else "/listings"
    return fix_path_for(step, getattr(design, "agent", None))


def assess_design(design, context: dict) -> list[MissingElement]:
    """Elements that would render empty and should not."""
    missing: list[MissingElement] = []
    seen: set[str] = set()

    for element in design.ensure_document():
        if not element.get("visible", True):
            continue

        # Resolved with no image map: an unreadable image is a storage problem,
        # not a missing-profile-field one, and passing images through here
        # would mean reading every file just to ask whether it is empty.
        content = resolve_content(element, context, {})
        is_empty = content is None or (isinstance(content, str) and not content.strip())

        source = element.get("content_source") or ""
        # An element with a data source is *supposed* to show something. If it
        # resolves to nothing, the export gets a blank rectangle where a price
        # or a photo belongs — which an agent may not notice until after it is
        # published.
        #
        # An element with no source and nothing in it is a different case: an
        # empty box the agent left on the canvas. Their business, not a gap.
        #
        # This replaces the template's old `required` constraint, and covers
        # more: that flag had to be set by hand per element, and was the only
        # reason a missing listing photo was ever caught. Now anything the
        # design binds to data is checked, and anything the agent does not want
        # checked they can simply delete — which they could not do before.
        if is_empty and source:
            label, step = _describe(source, element)
            # A design can show the same field twice; the agent only needs
            # telling once.
            if label in seen:
                continue
            seen.add(label)
            missing.append(
                MissingElement(element["id"], label, step, _fix_path(step, design))
            )
            continue

        # A partly-resolved placeholder is its own failure: "Call " with no
        # number reads as finished when it is not.
        stored = element.get("content")
        if isinstance(stored, str) and "{{" in stored:
            for path in unresolved_placeholders(stored, context):
                if not path.startswith(PROFILE_PREFIXES):
                    continue
                label, step = _describe(path, element)
                if label in seen:
                    continue
                seen.add(label)
                missing.append(
                    MissingElement(element["id"], label, step, _fix_path(step, design))
                )

    return missing


class DesignNotReadyError(Exception):
    """Raised when a design would render with holes in it."""

    def __init__(self, missing: list[MissingElement]) -> None:
        self.missing = missing
        names = ", ".join(item.label for item in missing)
        super().__init__(
            f"This design is missing information it needs before it can be "
            f"exported: {names}."
        )

    def as_dict(self) -> dict:
        return {
            "detail": str(self),
            "missing": [item.as_dict() for item in self.missing],
            "steps": sorted({item.step for item in self.missing}),
        }


def require_design_ready(design, context: dict) -> None:
    """Raise unless every element this design shows has something to show.

    Called before rendering an export. The alternative is an asset with a blank
    rectangle where the brokerage logo belongs — which an agent may not notice
    until after it is published.
    """
    missing = assess_design(design, context)
    if missing:
        raise DesignNotReadyError(missing)
