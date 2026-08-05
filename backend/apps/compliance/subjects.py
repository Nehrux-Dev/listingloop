"""Turn app objects into something the checks can read.

A check should not know what a Design is. It gets text blocks and a field map,
and works the same whether those came from a rendered design, an AI variant, or
a paste-in from a form. All the app-specific knowledge lives here, in one file,
which is also the only place that needs touching to make compliance cover
something new.

Imports of other apps' models are deferred into the functions on purpose:
``ai_content`` and ``templates`` call into compliance, so importing them at
module level here would close the loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComplianceSubject:
    """A normalised view of one piece of content."""

    kind: str
    label: str
    #: Named blocks of prose. Checks that target a field use these names.
    text_blocks: dict[str, str] = field(default_factory=dict)
    #: Non-prose values a rule may require to be present.
    fields: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Used to pick up brokerage-scoped rules.
    brokerage_id: int | None = None

    @property
    def combined_text(self) -> str:
        return "\n\n".join(value for value in self.text_blocks.values() if value)


def from_text(text: str, *, label: str = "content", kind: str = "all") -> ComplianceSubject:
    """The simplest subject: a block of text with no structure."""
    return ComplianceSubject(kind=kind, label=label, text_blocks={"content": text or ""})


def from_content_variant(variant) -> ComplianceSubject:
    """One AI content variant."""
    listing = variant.generation.listing
    brokerage = listing.agent.brokerage

    return ComplianceSubject(
        kind="ai_content",
        label=f"{variant.get_kind_display()} for listing {listing.pk}",
        text_blocks={variant.kind: variant.display_text},
        fields={
            "brokerage_name": brokerage.name if brokerage else "",
            "required_disclaimer": brokerage.required_disclaimer if brokerage else "",
            "agent_name": listing.agent.name,
            "agent_phone": listing.agent.phone,
            "listing_price": listing.price,
            "listing_address": listing.address,
        },
        metadata={
            "variant_kind": variant.kind,
            "listing_id": listing.pk,
            "generation_id": variant.generation_id,
        },
        brokerage_id=brokerage.pk if brokerage else None,
    )


def from_generated_content(generation) -> ComplianceSubject:
    """A whole content pack, checked as one body of text."""
    listing = generation.listing
    brokerage = listing.agent.brokerage

    blocks = {
        variant.kind: variant.display_text for variant in generation.variants.all()
    }
    if not blocks:
        blocks = {"caption": generation.caption}

    return ComplianceSubject(
        kind="ai_content",
        label=f"Content pack for listing {listing.pk}",
        text_blocks=blocks,
        fields={
            "brokerage_name": brokerage.name if brokerage else "",
            "required_disclaimer": brokerage.required_disclaimer if brokerage else "",
            "agent_name": listing.agent.name,
            "agent_phone": listing.agent.phone,
            "listing_price": listing.price,
        },
        metadata={"generation_id": generation.pk, "listing_id": listing.pk},
        brokerage_id=brokerage.pk if brokerage else None,
    )


def from_design(design) -> ComplianceSubject:
    """A design, resolved the same way the renderer resolves it.

    Uses the render pipeline's own resolver rather than reading the template,
    so what compliance sees is what will actually appear in the image —
    including locked elements the agent never touched.
    """
    from apps.templates.dimensions import DEFAULT_DIMENSION, get_dimension
    from apps.templates.html_builder import describe_design
    from apps.templates.render_context import build_context

    context = build_context(design)
    described = describe_design(design, context, get_dimension(DEFAULT_DIMENSION))

    blocks: dict[str, str] = {}
    for element in described["elements"]:
        if element.get("hidden"):
            continue
        content = element.get("content")
        # Images resolve to data URIs; including one would be megabytes of
        # base64 for a text check to wade through.
        if isinstance(content, str) and content and not content.startswith("data:"):
            blocks[element["key"]] = content

    listing = design.listing
    brokerage = design.agent.brokerage

    return ComplianceSubject(
        kind="design",
        label=design.name,
        text_blocks=blocks,
        fields={
            "brokerage_name": brokerage.name if brokerage else "",
            "brokerage_logo": bool(brokerage.logo) if brokerage else False,
            "required_disclaimer": brokerage.required_disclaimer if brokerage else "",
            "agent_name": design.agent.name,
            "agent_phone": design.agent.phone,
            "listing_price": listing.price if listing else None,
            "listing_address": listing.address if listing else "",
        },
        metadata={
            "design_id": design.pk,
            "template": design.template.slug,
            "listing_id": listing.pk if listing else None,
        },
        brokerage_id=brokerage.pk if brokerage else None,
    )


def from_listing(listing) -> ComplianceSubject:
    brokerage = listing.agent.brokerage
    return ComplianceSubject(
        kind="listing",
        label=listing.full_address or f"Listing {listing.pk}",
        text_blocks={
            "description": listing.description or "",
            "features": " ".join(listing.features or []),
        },
        fields={
            "brokerage_name": brokerage.name if brokerage else "",
            "required_disclaimer": brokerage.required_disclaimer if brokerage else "",
            "listing_price": listing.price,
            "listing_address": listing.address,
            "property_type": listing.property_type,
        },
        metadata={"listing_id": listing.pk},
        brokerage_id=brokerage.pk if brokerage else None,
    )
