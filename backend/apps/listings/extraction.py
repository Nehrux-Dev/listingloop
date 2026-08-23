"""Extract listing fields from a fetched HTML page.

=============================================================================
THE RULE: NEVER INVENT DATA
=============================================================================

Everything this module produces gets shown to an agent who is about to put
their name on it. A blank field is a small inconvenience; a *wrong* field that
looks confidently filled in is how a listing goes out with the wrong price.

So the extraction is deliberately conservative, in four tiers, most reliable
first:

  1. **JSON-LD / microdata** (schema.org) — the site explicitly telling us
     what the numbers mean. Trusted.
  2. **Embedded state** — the JSON a JavaScript-built site ships its own page
     data in (``__NEXT_DATA__``, ``window.__INITIAL_STATE__``, Rightmove's
     ``PAGE_MODEL``, Apollo caches). This is the very object the page renders
     from, so it is as explicit as JSON-LD — but its key names are the site's
     own, so only unambiguous keys are read, and a value is accepted only when
     every listing-shaped object on the page agrees about it. A page whose
     state describes many properties (search results, "similar homes") is
     left alone entirely.
  3. **Open Graph / meta tags** — also explicit, but coarser. Used for images
     and description.
  4. **Labelled text patterns** — only for bedrooms, bathrooms and floor area,
     and only where a number sits directly against an unambiguous label
     ("3 bedrooms"). If the page yields *conflicting* values for a field, the
     field is left blank and a warning is recorded. Guessing which of two
     numbers is right is exactly the failure this rule exists to prevent.

Price is never taken from loose text. A listing page is full of numbers that
look like prices — comparable sales, price history, mortgage estimates — and
picking one would be a coin flip. A price is accepted only where it is
*labelled as the price* in machine-readable form: schema.org data, embedded
state under an explicit price key, or a price meta tag. Anywhere else, it
stays blank.

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
    #: Whether the page actually declared a listing machine-readably (JSON-LD,
    #: microdata, or usable embedded state), as opposed to yielding only meta
    #: tags and text guesses. The import path uses this to decide whether
    #: re-fetching with a browser is worth the cost — and embedded state often
    #: answers it from the plain fetch, since a JS-built page ships its data
    #: island in the HTML even when the visible markup is an empty shell.
    structured: bool = False

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


def _apply_listing_node(result: ExtractionResult, node: dict, base_url: str) -> None:
    """Apply one schema.org listing node, whatever syntax it arrived in.

    JSON-LD and microdata are two spellings of the same vocabulary, so they
    converge here rather than growing a second set of field rules that would
    drift apart.
    """
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


def _apply_jsonld(result: ExtractionResult, soup: BeautifulSoup, base_url: str) -> bool:
    found_listing_node = False

    for node in _iter_jsonld(soup):
        if not _types_of(node) & LISTING_TYPES:
            continue
        found_listing_node = True
        _apply_listing_node(result, node, base_url)

    return found_listing_node


# ---------------------------------------------------------------------------
# Microdata (itemscope / itemprop)
# ---------------------------------------------------------------------------
#
# The same schema.org vocabulary written inline in the markup instead of in a
# script tag. Plenty of brokerage sites and CMS templates emit this and no
# JSON-LD at all, and ignoring it meant those pages imported as blank despite
# stating everything we needed, in a form that is just as explicit.


def _microdata_value(tag, base_url: str):
    """The value of one itemprop, read the way the spec says to."""
    if tag.has_attr("itemscope"):
        return _microdata_node(tag, base_url)

    name = tag.name
    if name == "meta":
        return (tag.get("content") or "").strip()
    if name in ("img", "audio", "video", "source", "embed", "iframe", "track"):
        src = tag.get("src")
        return urljoin(base_url, src) if src else ""
    if name in ("a", "area", "link"):
        href = tag.get("href")
        return urljoin(base_url, href) if href else ""
    if name in ("data", "meter"):
        return (tag.get("value") or tag.get_text(" ", strip=True)).strip()
    if name == "time":
        return (tag.get("datetime") or tag.get_text(" ", strip=True)).strip()
    if name == "object":
        return (tag.get("data") or "").strip()

    return tag.get_text(" ", strip=True)


def _microdata_node(scope, base_url: str) -> dict:
    """Turn one itemscope element into a JSON-LD-shaped dict."""
    node: dict = {}

    itemtype = scope.get("itemtype")
    if itemtype:
        types = itemtype if isinstance(itemtype, list) else [itemtype]
        # "https://schema.org/Apartment" -> "Apartment", matching JSON-LD.
        node["@type"] = [str(t).rstrip("/").rsplit("/", 1)[-1] for t in types]

    for prop in scope.find_all(attrs={"itemprop": True}):
        # Only direct properties: anything inside a nested itemscope belongs to
        # that nested item, and hoisting it here would attach a sub-object's
        # values to the listing.
        parent_scope = prop.find_parent(attrs={"itemscope": True})
        if parent_scope is not scope:
            continue

        names = prop.get("itemprop")
        value = _microdata_value(prop, base_url)
        if value in ("", None):
            continue

        for name in names if isinstance(names, list) else str(names).split():
            existing = node.get(name)
            if existing is None:
                node[name] = value
            elif isinstance(existing, list):
                existing.append(value)
            else:
                node[name] = [existing, value]

    return node


def _apply_microdata(result: ExtractionResult, soup: BeautifulSoup, base_url: str) -> bool:
    found_listing_node = False

    for scope in soup.find_all(attrs={"itemscope": True, "itemtype": True}):
        node = _microdata_node(scope, base_url)
        if not _types_of(node) & LISTING_TYPES:
            continue
        found_listing_node = True
        _apply_listing_node(result, node, base_url)

    return found_listing_node


# ---------------------------------------------------------------------------
# Embedded state (__NEXT_DATA__ and friends)
# ---------------------------------------------------------------------------
#
# A JavaScript-built listing page ships its data as JSON in the HTML — a
# Next.js data island, a `window.__INITIAL_STATE__` assignment, Rightmove's
# PAGE_MODEL — and renders the visible page *from* it. That JSON is therefore
# at least as authoritative as the rendered text, and it is present in the
# plain fetch, which means reading it here can save the whole browser
# re-fetch that exists for pages whose visible HTML is an empty shell.
#
# What makes it riskier than schema.org is that the key names are the site's
# own. Two rules keep the never-invent promise:
#
#   * Only unambiguous keys are read (`bedrooms`, `listPrice`,
#     `displayAddress`, ...). A key that merely might mean the right thing
#     (`area`, `size`) is ignored.
#   * The state routinely describes *other* properties too — search cards,
#     "similar homes", an entity cache with the neighbours in it. So a value
#     is used only when every listing-shaped object found agrees on it; an
#     array of several listing-shaped objects is treated as a card list and
#     skipped outright; and a page whose state is mostly other properties is
#     left alone with a warning.

#: Globals that sites assign their page state to. Matched as `NAME = {...}`
#: inside inline scripts; the JSON object is cut out by brace-matching and
#: parsed strictly — anything that is not valid JSON is skipped, never eval'd.
_STATE_ASSIGNMENT_RE = re.compile(
    r"(?:window\.|self\.|globalThis\.)?"
    r"(?:__NEXT_DATA__|__INITIAL_STATE__|__PRELOADED_STATE__|__APOLLO_STATE__|PAGE_MODEL)"
    r"\s*=\s*"
)

#: A single state blob past this size is an app bundle, not page data.
_MAX_STATE_BYTES = 2 * 1024 * 1024

#: Ceiling on JSON nodes walked per page. Bounds CPU on pathological blobs;
#: real page states are far smaller.
_MAX_STATE_NODES = 80_000

#: More listing-shaped objects than this means a search page. Nothing on such
#: a page can be attributed to "the" listing, so the tier withdraws.
_MAX_STATE_CANDIDATES = 8

#: A dict qualifies as listing-shaped when at least this many of the signal
#: groups below are present. High enough that a random config object cannot
#: qualify; low enough that a lean listing card still does.
_MIN_STATE_SIGNALS = 3

# Key synonyms, matched after lowercasing and stripping `_`/`-` so camelCase
# and snake_case spell the same thing. Every entry is a key whose meaning is
# not really in doubt; that is the admission test for this table.
_STATE_BEDROOM_KEYS = ("bedrooms", "beds", "numbedrooms", "bedroomcount", "numberofbedrooms")
_STATE_BATHROOM_KEYS = (
    "bathrooms",
    "baths",
    "numbathrooms",
    "bathroomcount",
    "numberofbathroomstotal",
    "bathroomstotal",
)
_STATE_PRICE_KEYS = ("price", "listprice", "askingprice", "listingprice", "prices")
_STATE_PRICE_INNER_KEYS = ("amount", "value", "price", "listprice", "primaryprice", "displayprice")
_STATE_ADDRESS_KEYS = ("address", "displayaddress", "fulladdress")
_STATE_STREET_KEYS = ("streetaddress", "street", "street1", "line1", "addressline1", "address1")
_STATE_CITY_KEYS = ("addresslocality", "city", "locality", "town", "suburb")
_STATE_REGION_KEYS = ("addressregion", "state", "region", "province", "county", "statecode")
_STATE_POSTCODE_KEYS = ("postalcode", "postcode", "zip", "zipcode")
_STATE_COUNTRY_KEYS = ("addresscountry", "country", "countrycode")
#: Keys that state the unit in their own name need no companion unit key.
_STATE_SQFT_KEYS = ("sqft", "squarefeet", "squarefootage", "floorareasqft")
#: `livingArea` alone could be either unit; it is read only when a unit key
#: sits beside it to say which.
_STATE_AREA_KEYS = ("livingarea", "livingareavalue")
_STATE_AREA_UNIT_KEYS = ("livingareaunits", "areaunits", "areaunit", "sizeunit", "unitofarea")
_STATE_TYPE_KEYS = ("propertytype", "hometype", "propertysubtype")
_STATE_PHOTO_KEYS = ("images", "photos", "media", "propertyimages", "photourls")
_STATE_PHOTO_INNER_KEYS = ("url", "src", "href", "srcurl", "imageurl", "mainimagesrc")

#: Site vocabularies mapped onto schema.org type names, which then go through
#: the same PROPERTY_TYPE_HINTS as everything else. Only spellings whose
#: meaning is obvious; anything absent stays unmapped on purpose.
_STATE_TYPE_ALIASES = {
    "singlefamily": "house",
    "singlefamilyhome": "house",
    "singlefamilyresidence": "house",
    "detached": "house",
    "detachedhouse": "house",
    "semidetached": "house",
    "semidetachedhouse": "house",
    "house": "house",
    "flat": "apartment",
    "apartment": "apartment",
    "condo": "condo",
    "condominium": "condo",
    "townhouse": "townhouse",
    "townhome": "townhouse",
    "duplex": "duplex",
    "land": "land",
    "lot": "land",
    "commercial": "commercial",
}


def _normalised_keys(node: dict) -> dict:
    """`{listPrice: 1} / {list_price: 1}` -> `{"listprice": 1}`, first wins."""
    out: dict = {}
    for key, value in node.items():
        normalised = str(key).lower().replace("_", "").replace("-", "")
        out.setdefault(normalised, value)
    return out


def _balanced_json_object(text: str, start: int) -> str | None:
    """The `{...}` starting at ``start``, honouring strings and escapes."""
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, min(len(text), start + _MAX_STATE_BYTES)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _iter_embedded_json(soup: BeautifulSoup):
    """Yield every parsed JSON state blob on the page."""
    for tag in soup.find_all("script"):
        script_type = (tag.get("type") or "").lower()
        if script_type == "application/ld+json":
            continue  # tier 1's territory
        raw = tag.string or tag.get_text() or ""
        if not raw or len(raw) > _MAX_STATE_BYTES:
            continue

        # Data islands: <script type="application/json"> is inert data by
        # definition — __NEXT_DATA__ is the famous one, but any island might
        # be the page's state, and parsing them all costs one json.loads each.
        if script_type == "application/json":
            try:
                yield json.loads(raw)
            except (ValueError, TypeError):
                pass
            continue

        # Inline assignments to the known globals.
        for match in _STATE_ASSIGNMENT_RE.finditer(raw):
            snippet = _balanced_json_object(raw, match.end())
            if snippet is None:
                continue
            try:
                yield json.loads(snippet)
            except (ValueError, TypeError):
                # Real JavaScript rather than serialised JSON. Not ours to
                # interpret — evaluating it would be running the site's code.
                continue


def _state_signals(node: dict) -> set[str]:
    """Which listing signals ``node`` carries, by unambiguous key alone."""
    lowered = _normalised_keys(node)

    def present(keys: tuple[str, ...]) -> bool:
        return any(lowered.get(key) not in (None, "", [], {}) for key in keys)

    signals = set()
    if present(_STATE_BEDROOM_KEYS):
        signals.add("bedrooms")
    if present(_STATE_BATHROOM_KEYS):
        signals.add("bathrooms")
    if present(_STATE_PRICE_KEYS):
        signals.add("price")
    if present(_STATE_ADDRESS_KEYS):
        signals.add("address")
    if present(_STATE_SQFT_KEYS) or present(_STATE_AREA_KEYS):
        signals.add("square_footage")
    if any(isinstance(lowered.get(key), str) and lowered[key].strip() for key in _STATE_TYPE_KEYS):
        signals.add("property_type")
    return signals


def _is_state_candidate(node) -> bool:
    return isinstance(node, dict) and len(_state_signals(node)) >= _MIN_STATE_SIGNALS


def _iter_state_candidates(root):
    """Yield listing-shaped dicts inside ``root``, skipping card lists.

    Iterative rather than recursive (state blobs nest deep), with a node
    budget. Two shapes are deliberately not yielded:

      * Items of an array that contains two or more listing-shaped objects.
        That is a search-result or "similar homes" strip, and every entry in
        it is somebody else's property.
      * Anything nested *inside* a yielded candidate — its interesting
        sub-objects (address, photos) are read through the candidate itself.
    """
    budget = _MAX_STATE_NODES
    stack = [root]
    while stack and budget > 0:
        budget -= 1
        node = stack.pop()
        if isinstance(node, dict):
            if _is_state_candidate(node):
                yield node
            else:
                stack.extend(node.values())
        elif isinstance(node, list):
            candidates_here = sum(1 for item in node if _is_state_candidate(item))
            if candidates_here >= 2:
                stack.extend(item for item in node if not _is_state_candidate(item))
            else:
                stack.extend(node)


def _state_price(value) -> Decimal | None:
    if isinstance(value, dict):
        lowered = _normalised_keys(value)
        for key in _STATE_PRICE_INNER_KEYS:
            if key in lowered:
                price = _to_decimal(lowered[key])
                if price:
                    return price
        return None
    return _to_decimal(value)


def _state_address(value):
    """An address value -> the shape ``_extract_address`` reads."""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return None

    lowered = _normalised_keys(value)

    def first(keys: tuple[str, ...]):
        for key in keys:
            if lowered.get(key) not in (None, ""):
                return lowered[key]
        return None

    schema_shaped = {
        "streetAddress": first(_STATE_STREET_KEYS),
        "addressLocality": first(_STATE_CITY_KEYS),
        "addressRegion": first(_STATE_REGION_KEYS),
        "postalCode": first(_STATE_POSTCODE_KEYS),
        "addressCountry": first(_STATE_COUNTRY_KEYS),
    }
    if any(schema_shaped.values()):
        return {key: value for key, value in schema_shaped.items() if value is not None}

    # No component keys, but a display string inside the object (Rightmove's
    # address.displayAddress). Kept whole, like any unstructured address.
    display = first(("displayaddress", "fulladdress"))
    return display if isinstance(display, str) else None


def _state_photos(value) -> list[str]:
    urls: list[str] = []
    items = value if isinstance(value, list) else [value]
    for item in items[: MAX_PHOTOS * 2]:
        if isinstance(item, str) and item.strip():
            urls.append(item.strip())
        elif isinstance(item, dict):
            lowered = _normalised_keys(item)
            for key in _STATE_PHOTO_INNER_KEYS:
                candidate = lowered.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    urls.append(candidate.strip())
                    break
    return urls


def _schema_node_from_state(node: dict) -> dict:
    """Translate one state candidate into a schema.org-shaped node.

    Translation rather than a second extractor: everything downstream —
    clamping, list-unwrapping, the m² conversion and its warning — already
    exists in ``_apply_listing_node``, and this keeps the state tier from
    growing field rules that drift away from the JSON-LD ones.
    """
    lowered = _normalised_keys(node)
    schema: dict = {}

    def first(keys: tuple[str, ...]):
        for key in keys:
            if lowered.get(key) not in (None, ""):
                return lowered[key]
        return None

    bedrooms = first(_STATE_BEDROOM_KEYS)
    if bedrooms is not None:
        schema["numberOfBedrooms"] = bedrooms
    bathrooms = first(_STATE_BATHROOM_KEYS)
    if bathrooms is not None:
        schema["numberOfBathroomsTotal"] = bathrooms

    price_raw = first(_STATE_PRICE_KEYS)
    if price_raw is not None:
        price = _state_price(price_raw)
        if price:
            schema["offers"] = {"price": price}

    address = _state_address(first(_STATE_ADDRESS_KEYS))
    if address is not None:
        schema["address"] = address

    sqft = first(_STATE_SQFT_KEYS)
    if sqft is not None:
        schema["floorSize"] = sqft
    else:
        area = first(_STATE_AREA_KEYS)
        unit = first(_STATE_AREA_UNIT_KEYS)
        if area is not None and isinstance(unit, str) and unit.strip():
            schema["floorSize"] = {"value": area, "unitText": unit}

    type_raw = first(_STATE_TYPE_KEYS)
    if isinstance(type_raw, str):
        alias = _STATE_TYPE_ALIASES.get(re.sub(r"[^a-z]", "", type_raw.lower()))
        if alias:
            schema["@type"] = [alias]

    description = lowered.get("description")
    # Short strings under a `description` key are routinely UI labels or SEO
    # stubs; a real listing description has some length to it.
    if isinstance(description, str) and len(description.strip()) >= 40:
        schema["description"] = description.strip()

    photos = _state_photos(first(_STATE_PHOTO_KEYS))
    if photos:
        schema["image"] = photos

    return schema


def _comparable(value) -> str:
    """A value as a string that makes duplicates equal across candidates."""
    if isinstance(value, Decimal):
        return str(value.normalize())
    return " ".join(str(value).lower().split())


def _apply_embedded_state(result: ExtractionResult, soup: BeautifulSoup, base_url: str) -> bool:
    """Read the page's embedded state. True when it yielded anything usable."""
    candidates: list[dict] = []
    for blob in _iter_embedded_json(soup):
        for node in _iter_state_candidates(blob):
            candidates.append(node)
            if len(candidates) > _MAX_STATE_CANDIDATES:
                result.warnings.append(
                    "The page's embedded data describes many properties, so "
                    "none of it was used."
                )
                return False
    if not candidates:
        return False

    # Each candidate is applied into its own scratch result, and a field only
    # reaches the real one where every candidate that states it agrees. The
    # entity-cache case — the page's own listing sitting beside its neighbours
    # in one dict — is exactly what this catches.
    scratches: list[ExtractionResult] = []
    for node in candidates:
        scratch = ExtractionResult()
        _apply_listing_node(scratch, _schema_node_from_state(node), base_url)
        if scratch.fields or scratch.photo_urls:
            result.warnings.extend(scratch.warnings)
            scratches.append(scratch)
    if not scratches:
        return False

    field_names = sorted(set().union(*(scratch.fields for scratch in scratches)))
    disputed: list[str] = []
    settled = 0
    for name in field_names:
        values = {
            _comparable(scratch.fields[name])
            for scratch in scratches
            if name in scratch.fields
        }
        if len(values) == 1:
            for scratch in scratches:
                if name in scratch.fields:
                    result.set(name, scratch.fields[name])
                    settled += 1
                    break
        else:
            disputed.append(name)

    if disputed:
        listed = ", ".join(field.replace("_", " ") for field in disputed)
        result.warnings.append(
            f"The page's embedded data gives conflicting values for {listed}, "
            "so they were left blank rather than guessed."
        )

    # Photos are only attributable to *the* listing when the candidates are
    # not disputing whose page this is.
    photos_added = 0
    if "address" not in disputed:
        for scratch in scratches:
            for url in scratch.photo_urls:
                absolute = urljoin(base_url, url)
                if absolute not in result.photo_urls:
                    result.photo_urls.append(absolute)
                    photos_added += 1

    return settled > 0 or photos_added > 0


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

    # JSON-LD first so it wins where both are present: `set()` keeps the first
    # value for a field, and a script block is less likely to have been
    # mangled by a CMS than inline attributes. Embedded state runs after the
    # schema.org tiers — it is the same data with the site's own key names, so
    # where both exist the spelled-out vocabulary is the better witness.
    had_structured_data = _apply_jsonld(result, soup, base_url)
    had_structured_data |= _apply_microdata(result, soup, base_url)
    had_structured_data |= _apply_embedded_state(result, soup, base_url)
    result.structured = had_structured_data
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
