"""Social media output dimensions.

One template renders at all of these. Element geometry is stored as fractions
of the canvas, so changing the canvas is all it takes — there is no second
layout to maintain per platform.

``safe_inset`` is the fraction of the canvas kept clear at top and bottom for
formats where platform chrome overlays the image (Story especially). The HTML
builder maps element geometry into the area between the insets rather than the
raw canvas, so a design does not end up with its price behind a profile bubble.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str
    width: int
    height: int
    safe_inset_top: float = 0.0
    safe_inset_bottom: float = 0.0

    @property
    def aspect(self) -> float:
        return self.width / self.height


SOCIAL_DIMENSIONS: dict[str, Dimension] = {
    "instagram_post": Dimension("instagram_post", "Instagram Post", 1080, 1080),
    "instagram_story": Dimension(
        "instagram_story",
        "Instagram Story",
        1080,
        1920,
        # Story UI covers roughly the top and bottom eighth.
        safe_inset_top=0.12,
        safe_inset_bottom=0.14,
    ),
    "facebook": Dimension("facebook", "Facebook", 1200, 630),
    "linkedin": Dimension("linkedin", "LinkedIn", 1200, 627),
}

DEFAULT_DIMENSION = "instagram_post"


def get_dimension(key: str) -> Dimension:
    try:
        return SOCIAL_DIMENSIONS[key]
    except KeyError as exc:
        raise ValueError(
            f"Unknown dimension '{key}'. Available: {', '.join(SOCIAL_DIMENSIONS)}"
        ) from exc
