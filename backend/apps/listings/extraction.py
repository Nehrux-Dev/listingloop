"""Extract listing fields from a fetched HTML page.

=============================================================================
THE RULE: NEVER INVENT DATA
=============================================================================

Everything this module produces gets shown to an agent who is about to put
their name on it. A blank field is a small inconvenience; a *wrong* field that
looks confidently filled in is how a listing goes out with the wrong price.

So the extraction is deliberately conservative, in three tiers, most reliable
first:

  1. **JSON-LD** (schema.org) — the site explicitly telling us what the
     numbers mean. Trusted.
  2. **Open Graph / meta tags** — also explicit, but coarser. Used for images
     and description.
  3. **Labelled text patterns** — only for bedrooms, bathrooms and floor area,
     and only where a number sits directly against an unambiguous label
     ("3 bedrooms"). If the page yields *conflicting* values for a field, the
     field is left blank and a warning is recorded. Guessing which of two
     numbers is right is exactly the failure this rule exists to prevent.

Price is never taken from loose text. A listing page is full of numbers that
look like prices — comparable sales, price history, mortgage estimates — and
picking one would be a coin flip. If structured data does not state the price,
it stays blank.

Every field that is populated is named in ``extracted_fields``, and everything
that could not be found produces a warning. The agent therefore sees exactly
what came from the page and what still needs typing in — and nothing is
verified until they say so.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from apps.listings.models import PropertyType

logger = logging.getLogger(__name__)

MAX_PHOTOS = 8

#: schema.org types that describe something we can treat as a listing.
LISTING_TYPES = {
    "realestatelisting",
    "singlefamilyresidence",
    "house",
    "apartment",
    "residence",
    "accommodation",
    "product",
    "offer",
    "place",
}

#: schema.org / free-text property descriptions mapped onto our choices.
PROPERTY_TYPE_HINTS = {
    "singlefamilyresidence": PropertyType.HOUSE,
    "house": PropertyType.HOUSE,
    "apartment": PropertyType.APARTMENT,
    "apartmentcomplex": PropertyType.APARTMENT,
    "townhouse": PropertyType.TOWNHOUSE,
    "condominium": PropertyType.CONDO,
    "condo": PropertyType.CONDO,
    "duplex": PropertyType.DUPLEX,
    "land": PropertyType.LAND,
    "commercial": PropertyType.COMMERCIAL,
}

_BEDROOM_RE = re.compile(r"(\d{1,2})\s*(?:bed(?:room)?s?)\b", re.IGNORECASE)
_BATHROOM_RE = re.compile(r"(\d{1,2}(?:\.\d)?)\s*(?:bath(?:room)?s?)\b", re.IGNORECASE)
_SQFT_RE = re.compile(
    r"([\d,]{2,12})\s*(?:sq\.?\s*(?:ft|feet)|square\s+f(?:ee)?t|sqft)\b",
    re.IGNORECASE,
)

#: Fields the importer knows how to look for. Anything not in here is always
#: left to the agent.
SUPPORTED_FIELDS = (
    "address",
    "city",
    "state",
    "postcode",
    "country",
    "price",
    "bedrooms",
    "bathrooms",
    "square_footage",
    "property_type",
    "description",
)


@dataclass
class ExtractionResult:
    fields: dict = field(default_factory=dict)
    photo_urls: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def extracted_fields(self) -> list[str]:
        return sorted(self.fields)

    def set(self, name: str, value) -> None:
        """Record a value, ignoring empties so nothing blank is 'extracted'."""
        if value is None or value == "" or name in self.fields:
            return
        self.fields[name] = value


# ---------------------------------------------------------------------------
# JSON-LD
# ---------------------------------------------------------------------------


def _iter_jsonld(soup: BeautifulSoup):
    """Yield every JSON-LD object on the page, flattening @graph and lists."""
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            # Malformed JSON-LD is common in the wild; skip it rather than
            # failing the whole import.
            continue

        stack = [parsed]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                yield node
                if "@graph" in node:
                    stack.append(node["@graph"])


def _types_of(node: dict) -> set[str]:
    raw = node.get("@type") or node.get("type") or []
    values = raw if isinstance(raw, list) else [raw]
    return {str(value).lower() for value in values}


def _first_scalar(value):
    """schema.org values are routinely wrapped in lists or objects."""
    if isinstance(value, list):
        return _first_scalar(value[0]) if value else None
    if isinstance(value, dict):
        return value.get("value") or value.get("@value") or value.get("name")
    return value


def _to_decimal(value) -> Decimal | None:
    scalar = _first_scalar(value)
    if scalar is None:
        return None
    text = re.sub(r"[^\d.]", "", str(scalar))
    if not text or text.count(".") > 1:
        return None
    try:
        result = Decimal(text)
    except InvalidOperation:
        return None
    return result if result > 0 else None


def _to_int(value) -> int | None:
    number = _to_decimal(value)
    return int(number) if number is not None else None


def _extract_address(result: ExtractionResult, node: dict) -> None:
    address = node.get("address")
    if isinstance(address, list):
        address = address[0] if address else None

    if isinstance(address, str):
        # An unstructured address string: keep it whole rather than trying to
        # split it into components we cannot verify.
        result.set("address", address.strip()[:255])
        return

    if not isinstance(address, dict):
        return

    result.set("address", (_first_scalar(address.get("streetAddress")) or "").strip()[:255])
    result.set("city", (_first_scalar(address.get("addressLocality")) or "").strip()[:120])
    result.set("state", (_first_scalar(address.get("addressRegion")) or "").strip()[:120])
    result.set("postcode", (_first_scalar(address.get("postalCode")) or "").strip()[:20])

    country = _first_scalar(address.get("addressCountry"))
    if isinstance(country, dict):
        country = country.get("name")
    result.set("country", (str(country).strip()[:120] if country else ""))


def _extract_floor_size(result: ExtractionResult, node: dict) -> None:
    floor_size = node.get("floorSize")
    if isinstance(floor_size, list):
        floor_size = floor_size[0] if floor_size else None
    if not isinstance(floor_size, dict):
        value = _to_int(floor_size)
        if value:
            result.set("square_footage", value)
        return

    value = _to_int(floor_size.get("value"))
    if not value:
        return

    unit = str(
        floor_size.get("unitCode") or floor_size.get("unitText") or ""
    ).strip().upper()

    if unit in {"MTK", "M2", "SQM", "SQUARE METRE", "SQUARE METER"}:
        # A unit conversion is arithmetic, not a guess — but it is recorded so
        # the agent knows the number was transformed.
        converted = int(round(value * 10.7639))
        result.set("square_footage", converted)
        result.warnings.append(
            f"Floor area was published as {value} m² and converted to "
            f"{converted} sq ft — please check it."
        )
        return

    result.set("square_footage", value)


def _extract_price(result: ExtractionResult, node: dict) -> None:
    for candidate in (node.get("offers"), node):
        if isinstance(candidate, list):
            candidate = candidate[0] if candidate else None
        if not isinstance(candidate, dict):
            continue
        price = _to_decimal(candidate.get("price") or candidate.get("lowPrice"))
        if price:
            result.set("price", price)
            return


def _extract_property_type(result: ExtractionResult, node: dict) -> None:
    for type_name in _types_of(node):
        if type_name in PROPERTY_TYPE_HINTS:
            result.set("property_type", PROPERTY_TYPE_HINTS[type_name])
            return


def _extract_photos(result: ExtractionResult, node: dict, base_url: str) -> None:
    images = node.get("image") or node.get("photo")
    if images is None:
        return
    if not isinstance(images, list):
        images = [images]

    for image in images:
        url = image.get("url") if isinstance(image, dict) else image
        if isinstance(url, str) and url.strip():
            absolute = urljoin(base_url, url.strip())
            if absolute not in result.photo_urls:
                result.photo_urls.append(absolute)


def _apply_jsonld(result: ExtractionResult, soup: BeautifulSoup, base_url: str) -> bool:
    found_listing_node = False

    for node in _iter_jsonld(soup):
        if not _types_of(node) & LISTING_TYPES:
            continue
        found_listing_node = True

        _extract_address(result, node)
        _extract_price(result, node)
        _extract_property_type(result, node)
        _extract_floor_size(result, node)
        _extract_photos(result, node, base_url)

        result.set("bedrooms", _to_int(node.get("numberOfBedrooms")))
        bathrooms = _to_decimal(
            node.get("numberOfBathroomsTotal")
            or node.get("numberOfBathrooms")
            or node.get("numberOfFullBathrooms")
        )
        result.set("bathrooms", bathrooms)

        description = _first_scalar(node.get("description"))
        if isinstance(description, str):
            result.set("description", description.strip())

    return found_listing_node


# ---------------------------------------------------------------------------
# Open Graph / meta
# ---------------------------------------------------------------------------


def _meta_content(soup: BeautifulSoup, **attrs) -> str | None:
    tag = soup.find("meta", attrs=attrs)
    if tag is None:
        return None
    content = tag.get("content")
    return content.strip() if isinstance(content, str) and content.strip() else None


def _apply_meta(result: ExtractionResult, soup: BeautifulSoup, base_url: str) -> None:
    description = _meta_content(soup, property="og:description") or _meta_content(
        soup, attrs={"name": "description"}
    )
    if description:
        result.set("description", description)

    price = _meta_content(soup, property="product:price:amount") or _meta_content(
        soup, property="og:price:amount"
    )
    if price:
        result.set("price", _to_decimal(price))

    for tag in soup.find_all("meta", attrs={"property": "og:image"}):
        content = tag.get("content")
        if isinstance(content, str) and content.strip():
            absolute = urljoin(base_url, content.strip())
            if absolute not in result.photo_urls:
                result.photo_urls.append(absolute)


# ---------------------------------------------------------------------------
# Conservative text heuristics
# ---------------------------------------------------------------------------


def _single_match(pattern: re.Pattern[str], text: str, cast):
    """Return the value only when the page agrees with itself.

    Multiple different values for the same attribute means the page is talking
    about more than one property (search results, "similar homes"), or we have
    matched something unrelated. Either way the honest answer is "don't know".
    """
    values = set()
    for raw in pattern.findall(text):
        try:
            value = cast(str(raw).replace(",", ""))
        except (ValueError, InvalidOperation):
            continue
        values.add(value)

    if len(values) == 1:
        return values.pop()
    return None if not values else _AMBIGUOUS


class _Ambiguous:
    """Sentinel: matches were found but disagreed."""


_AMBIGUOUS = _Ambiguous()


def _apply_text_heuristics(result: ExtractionResult, soup: BeautifulSoup) -> None:
    # Ignore script/style content, which is full of numbers.
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())[:200_000]

    checks = (
        ("bedrooms", _BEDROOM_RE, int),
        ("bathrooms", _BATHROOM_RE, Decimal),
        ("square_footage", _SQFT_RE, int),
    )

    for name, pattern, cast in checks:
        if name in result.fields:
            continue
        value = _single_match(pattern, text, cast)
        if value is _AMBIGUOUS:
            result.warnings.append(
                f"The page mentions several different values for {name}, so it "
                f"was left blank rather than guessed."
            )
        elif value is not None:
            result.set(name, value)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def extract_listing_data(html: str, base_url: str) -> ExtractionResult:
    """Pull whatever can be established from ``html``. Never guesses."""
    result = ExtractionResult()

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # pragma: no cover - parser is very tolerant
        logger.warning("Could not parse HTML from %r", base_url, exc_info=True)
        result.warnings.append("The page could not be parsed as HTML.")
        return result

    had_structured_data = _apply_jsonld(result, soup, base_url)
    _apply_meta(result, soup, base_url)
    # Run last: structured data always wins, and `set()` ignores repeats.
    _apply_text_heuristics(result, soup)

    if not had_structured_data:
        result.warnings.append(
            "The page has no structured listing data, so only basic details "
            "could be read. Please check every field."
        )

    if "price" not in result.fields:
        result.warnings.append(
            "No price was published in a machine-readable form. Prices are "
            "never read from page text, because listing pages contain many "
            "numbers that look like prices — please enter it manually."
        )

    for name in SUPPORTED_FIELDS:
        if name not in result.fields and name != "price":
            result.warnings.append(f"Could not read {name.replace('_', ' ')}.")

    result.photo_urls = result.photo_urls[:MAX_PHOTOS]
    if not result.photo_urls:
        result.warnings.append("No photos could be found on the page.")

    return result
