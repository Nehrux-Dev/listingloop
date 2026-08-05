"""Fact-check an AI response against the listing it was generated from.

WHY THIS EXISTS EVEN THOUGH THE PROMPT SAYS ALL OF THIS
------------------------------------------------------
The prompt tells the model not to invent numbers, features, locations, or
investment claims. Models mostly comply. "Mostly" is not a standard you can
publish under a real estate licence, and the failure mode is the dangerous kind:
output that reads perfectly and contains one plausible invented number.

So nothing the model returns is trusted. Every claim is checked against the
same verified facts the prompt was built from, by rules that do not involve a
model and cannot be talked out of anything.

WHAT IT CHECKS
--------------
  numbers    every numeric token in the output must trace to a listing field
  features   feature vocabulary that appears in the copy but not in the listing
  claims     investment, financial, legal and planning assertions
  locations  place names that are not the listing's own
  hashtags   the same rules, applied to tags

SEVERITY
--------
  error    -> the whole response is REJECTED and never lands in `caption`
  warning  -> stored, but FLAGGED for the agent to look at

Errors are reserved for things that are unambiguously wrong (a number that
appears nowhere in the listing, an explicit yield claim). Heuristics that can
misfire — capitalised words, say — produce warnings, because an agent ignoring
a warning is a smaller problem than a validator that cries wolf and gets
switched off.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Iterable

from apps.ai_content.models import ValidationStatus


@dataclass
class ValidationIssue:
    code: str
    severity: str  # "error" | "warning"
    message: str
    evidence: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class ValidationReport:
    status: str = ValidationStatus.PASSED
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def rejected(self) -> bool:
        return self.status == ValidationStatus.REJECTED

    def add(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)

    def finalise(self) -> "ValidationReport":
        if self.errors:
            self.status = ValidationStatus.REJECTED
        elif self.warnings:
            self.status = ValidationStatus.FLAGGED
        else:
            self.status = ValidationStatus.PASSED
        return self

    def as_list(self) -> list[dict[str, str]]:
        return [issue.as_dict() for issue in self.issues]


# ---------------------------------------------------------------------------
# Claim patterns
# ---------------------------------------------------------------------------

#: Investment / financial assertions. These are regulated speech in most
#: jurisdictions and are never derivable from a listing's fields.
INVESTMENT_PATTERNS: list[tuple[str, str]] = [
    (r"\b(?:great|solid|smart|excellent|strong|sound)\s+investment\b", "investment endorsement"),
    (r"\binvestment\s+(?:opportunity|potential|grade)\b", "investment claim"),
    (r"\b(?:rental|gross|net)?\s*yield\b", "yield claim"),
    (r"\breturn\s+on\s+investment\b|\bROI\b", "return claim"),
    (r"\bcapital\s+(?:growth|gains?)\b", "capital growth claim"),
    (r"\b(?:will|guaranteed to|set to|bound to)\s+(?:appreciate|grow|rise|increase)\b", "appreciation claim"),
    (r"\bguaranteed\s+(?:return|income|rent|profit)\b", "guaranteed return claim"),
    (r"\bpositively?\s+geared\b|\bnegatively?\s+geared\b", "gearing claim"),
    (r"\bcash\s*flow\s+positive\b", "cash flow claim"),
    (r"\bbelow\s+market\s+value\b|\bunder\s+market\b", "valuation claim"),
    (r"\bwill\s+(?:rent|lease)\s+for\b", "rental income claim"),
]

#: Legal, planning and regulatory assertions.
LEGAL_PATTERNS: list[tuple[str, str]] = [
    (r"\b(?:council|da|development)\s+approved\b", "planning approval claim"),
    (r"\bplanning\s+permission\b|\bbuilding\s+permit\b", "permit claim"),
    (r"\bzoned?\s+(?:for|as)\b|\brezoning\b", "zoning claim"),
    (r"\bsubdivision\s+potential\b|\bsubdividable\b", "subdivision claim"),
    (r"\bstrata\s+approved\b|\bbody\s+corporate\s+approved\b", "strata approval claim"),
    (r"\bcertified\b|\bcompliance\s+certificate\b", "certification claim"),
    (r"\bfreehold\b|\bleasehold\b|\btorrens\s+title\b", "title claim"),
    (r"\bheritage\s+listed\b", "heritage claim"),
    (r"\bpest\s+and\s+building\s+(?:clear|passed)\b", "inspection claim"),
]

#: Comparative superlatives that assert a checkable fact about other property.
SUPERLATIVE_PATTERNS: list[tuple[str, str]] = [
    (r"\bbest\s+(?:in|on)\s+the\s+(?:street|suburb|area|block|building)\b", "comparative superlative"),
    (r"\b(?:largest|biggest|cheapest|only)\s+\w+\s+(?:in|on)\s+the\s+\w+\b", "comparative superlative"),
    (r"\bunbeatable\b|\bunrivalled\b|\bunrivaled\b", "unverifiable superlative"),
    (r"\bmost\s+(?:sought[- ]after|desirable|exclusive)\b", "unverifiable superlative"),
]

#: Feature vocabulary. If one of these appears in the copy and nowhere in the
#: listing, the model has furnished the house for us.
FEATURE_VOCABULARY: list[tuple[str, str]] = [
    (r"\bswimming\s+pool\b|\bpool\b", "pool"),
    (r"\bspa\b|\bjacuzzi\b", "spa"),
    (r"\btennis\s+court\b", "tennis court"),
    (r"\bgarage\b|\bcarport\b", "garage or carport"),
    (r"\boff[- ]street\s+parking\b", "off-street parking"),
    (r"\bocean\s+views?\b|\bsea\s+views?\b|\bwater\s+views?\b", "water views"),
    (r"\bcity\s+views?\b|\bskyline\s+views?\b", "city views"),
    (r"\bmountain\s+views?\b", "mountain views"),
    (r"\bfireplace\b|\bwood\s+heater\b", "fireplace"),
    (r"\bair\s*conditioning\b|\bducted\s+(?:heating|cooling)\b|\breverse\s+cycle\b", "climate control"),
    (r"\bsolar\s+(?:panels?|power|system)\b", "solar"),
    (r"\bbalcony\b|\bterrace\b|\bveranda(?:h)?\b", "balcony or terrace"),
    (r"\bcourtyard\b", "courtyard"),
    (r"\bgarden\b|\bbackyard\b|\byard\b", "garden"),
    (r"\bwalk[- ]in\s+(?:robe|wardrobe|closet)\b", "walk-in robe"),
    (r"\bensuite\b", "ensuite"),
    (r"\bstudy\b|\bhome\s+office\b", "study"),
    (r"\bbasement\b|\bcellar\b", "basement"),
    (r"\bgym\b|\bfitness\s+(?:room|centre|center)\b", "gym"),
    (r"\bconcierge\b|\bdoorman\b", "concierge"),
    (r"\blift\b|\belevator\b", "lift"),
    (r"\bstone\s+bench(?:top)?s?\b|\bmarble\s+bench(?:top)?s?\b", "stone benchtops"),
    (r"\bhardwood\s+floors?\b|\btimber\s+floors?\b", "timber floors"),
    (r"\bnew(?:ly)?\s+renovated\b|\brenovated\b|\brefurbished\b", "renovation"),
    (r"\bbrand\s+new\b|\bnewly\s+built\b", "new build"),
    (r"\bwaterfront\b|\bbeachfront\b|\babsolute\s+beachfront\b", "waterfront position"),
    (r"\bcul[- ]de[- ]sac\b", "cul-de-sac"),
    (r"\bschool\s+catchment\b|\bwalk\s+to\s+school\b", "school catchment"),
    (r"\bpublic\s+transport\b|\btrain\s+station\b|\bbus\s+stop\b|\bmetro\b", "transport proximity"),
    (r"\bshops?\s+(?:nearby|close)\b|\bwalk\s+to\s+shops\b", "shop proximity"),
]

#: Words that look like numbers. Written-out counts are checked too, because
#: "four bedrooms" is exactly as much a claim as "4 bedrooms".
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
HASHTAG_RE = re.compile(r"^#[A-Za-z0-9]+$")

#: Matched as bare substrings inside a hashtag, where word boundaries do not
#: exist. Kept short and unambiguous on purpose: these are words that carry a
#: regulated claim no matter what they are glued to.
HIGH_RISK_TAG_KEYWORDS: tuple[str, ...] = (
    "yield",
    "roi",
    "investment",
    "guaranteed",
    "geared",
    "approved",
    "zoned",
    "subdivid",
    "freehold",
    "leasehold",
)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _numeric_variants(value: Any) -> set[str]:
    """Every plausible way a number could legitimately be written."""
    variants: set[str] = set()
    if value is None:
        return variants

    if isinstance(value, str):
        # Recurse with a Decimal, never with another string: a string always
        # re-matches its own digits, which recurses until the stack gives out.
        for match in NUMBER_RE.findall(value):
            cleaned = match.replace(",", "")
            variants.add(cleaned)
            variants.add(match)
            try:
                variants |= _numeric_variants(Decimal(cleaned))
            except Exception:
                continue
        return variants

    try:
        number = Decimal(str(value))
    except Exception:
        return variants

    plain = format(number.normalize(), "f")
    variants.add(plain)
    variants.add(plain.replace(".", ""))

    if number == number.to_integral_value():
        as_int = int(number)
        variants.add(str(as_int))
        variants.add(f"{as_int:,}")
        # Prices are routinely written short: 1850000 -> 1.85m, 1,850k
        if as_int >= 1000:
            variants.add(f"{as_int // 1000}")
            variants.add(f"{as_int / 1000:.0f}")
        if as_int >= 100000:
            millions = Decimal(as_int) / Decimal(1000000)
            variants.add(format(millions.normalize(), "f"))
            variants.add(f"{millions:.1f}".rstrip("0").rstrip("."))
            variants.add(f"{millions:.2f}".rstrip("0").rstrip("."))
    return {variant for variant in variants if variant}


def allowed_numbers(facts: dict[str, Any], listing) -> set[str]:
    """Every numeric string the copy is permitted to contain."""
    allowed: set[str] = set()

    for value in facts.values():
        if isinstance(value, list):
            for item in value:
                allowed |= _numeric_variants(item)
        else:
            allowed |= _numeric_variants(value)

    # Raw model values as well as the formatted ones in `facts`.
    for value in (
        listing.price,
        listing.bedrooms,
        listing.bathrooms,
        listing.square_footage,
        listing.postcode,
    ):
        allowed |= _numeric_variants(value)

    # Numbers appearing in the agent's own verified description or features are
    # verified data too.
    allowed |= _numeric_variants(listing.description or "")
    for feature in listing.features or []:
        allowed |= _numeric_variants(feature)

    return allowed


def _listing_haystack(listing, facts: dict[str, Any]) -> str:
    """Everything the listing legitimately says, for substring checks."""
    parts: list[str] = [
        listing.description or "",
        listing.address or "",
        listing.city or "",
        listing.state or "",
        listing.country or "",
        listing.get_property_type_display() if listing.property_type else "",
        *(listing.features or []),
        *(str(value) for value in facts.values() if not isinstance(value, list)),
    ]
    return _normalise(" ".join(parts))


def _check_numbers(text: str, allowed: set[str], report: ValidationReport, where: str) -> None:
    for raw in NUMBER_RE.findall(text):
        cleaned = raw.replace(",", "")
        candidates = {raw, cleaned, cleaned.rstrip("0").rstrip(".") if "." in cleaned else cleaned}
        if candidates & allowed:
            continue
        report.add(
            ValidationIssue(
                code="unverified_number",
                severity="error",
                message=(
                    f"The {where} contains the number “{raw}”, which does not appear "
                    f"anywhere in the verified listing data."
                ),
                evidence=raw,
            )
        )


def _check_number_words(text: str, allowed: set[str], report: ValidationReport) -> None:
    for word, value in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", text) and str(value) not in allowed:
            report.add(
                ValidationIssue(
                    code="unverified_number_word",
                    severity="warning",
                    message=(
                        f"The caption says “{word}”, and {value} is not a verified "
                        f"figure for this listing. Check it is not a room count."
                    ),
                    evidence=word,
                )
            )


def _check_patterns(
    text: str,
    patterns: Iterable[tuple[str, str]],
    code: str,
    severity: str,
    report: ValidationReport,
    template: str,
) -> None:
    for pattern, label in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            report.add(
                ValidationIssue(
                    code=code,
                    severity=severity,
                    message=template.format(label=label, text=match.group(0)),
                    evidence=match.group(0),
                )
            )


def _check_features(text: str, haystack: str, report: ValidationReport) -> None:
    for pattern, label in FEATURE_VOCABULARY:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        # Present in the copy — is it present in the listing?
        if re.search(pattern, haystack, re.IGNORECASE):
            continue
        report.add(
            ValidationIssue(
                code="unverified_feature",
                severity="error",
                message=(
                    f"The caption mentions {label} (“{match.group(0)}”), which is not "
                    f"in this listing's features or description."
                ),
                evidence=match.group(0),
            )
        )


def _check_locations(text: str, listing, haystack: str, report: ValidationReport) -> None:
    """Flag capitalised place-like phrases that are not the listing's own.

    A warning, not an error: capitalisation is a weak signal, and a validator
    that blocks output over "Saturday" would be turned off within a week.
    """
    known = {
        _normalise(part)
        for part in (
            listing.city,
            listing.state,
            listing.country,
            listing.postcode,
            listing.address,
        )
        if part
    }
    known_words = {word for part in known for word in part.split()}

    # Capitalised runs that are not at the start of a sentence.
    for match in re.finditer(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*)\b", text):
        phrase = match.group(1)
        lowered = _normalise(phrase)
        if lowered in known or lowered in haystack:
            continue
        if all(word in known_words for word in lowered.split()):
            continue
        report.add(
            ValidationIssue(
                code="possible_unverified_place",
                severity="warning",
                message=(
                    f"“{phrase}” looks like a place or proper noun that is not in the "
                    f"listing. Check it was not invented."
                ),
                evidence=phrase,
            )
        )


def _check_hashtags(hashtags: list[str], report: ValidationReport) -> None:
    if not isinstance(hashtags, list):
        report.add(
            ValidationIssue("malformed_hashtags", "error", "Hashtags were not a list.")
        )
        return

    if not 1 <= len(hashtags) <= 15:
        report.add(
            ValidationIssue(
                "hashtag_count",
                "warning",
                f"Expected between 4 and 10 hashtags, got {len(hashtags)}.",
            )
        )

    for tag in hashtags:
        if not isinstance(tag, str) or not HASHTAG_RE.match(tag):
            report.add(
                ValidationIssue(
                    "malformed_hashtag",
                    "warning",
                    f"“{tag}” is not a well-formed hashtag.",
                    evidence=str(tag),
                )
            )


#: Length above which a variant gets a "this is long" warning. Per format,
#: because a property-page description is meant to be longer than a text
#: message and warning about it would be noise.
MAX_LENGTHS: dict[str, int] = {
    "instagram_caption": 900,
    "facebook_caption": 1200,
    "linkedin_caption": 1200,
    "sharing_message": 400,
    "property_description": 2500,
}


def validate_text(
    text: str,
    listing,
    facts: dict[str, Any],
    *,
    label: str = "caption",
    max_length: int | None = None,
) -> ValidationReport:
    """Run every fact check over one block of prose.

    The single entry point for prose, whichever variant it is. Applying one
    function to all of them is what stops a rule being enforced on the
    Instagram caption and quietly forgotten on the property description — which
    is the longest variant and therefore the one with the most room to invent.
    """
    report = ValidationReport()

    if not isinstance(text, str) or not text.strip():
        report.add(
            ValidationIssue(
                "empty_text", "error", f"The response contained no {label.replace('_', ' ')}."
            )
        )
        return report.finalise()

    limit = max_length or MAX_LENGTHS.get(label, 1200)
    if len(text) > limit:
        report.add(
            ValidationIssue(
                "text_too_long",
                "warning",
                f"This is {len(text)} characters, which is long for a "
                f"{label.replace('_', ' ')} (guide: {limit}).",
            )
        )

    haystack = _listing_haystack(listing, facts)
    allowed = allowed_numbers(facts, listing)

    _check_numbers(text, allowed, report, label.replace("_", " "))
    _check_number_words(_normalise(text), allowed, report)

    _check_patterns(
        text, INVESTMENT_PATTERNS, "investment_claim", "error", report,
        "The copy makes an investment claim ({label}): “{text}”. "
        "Investment claims cannot be derived from listing data.",
    )
    _check_patterns(
        text, LEGAL_PATTERNS, "legal_claim", "error", report,
        "The copy makes a legal or planning claim ({label}): “{text}”. "
        "These cannot be derived from listing data.",
    )
    _check_patterns(
        text, SUPERLATIVE_PATTERNS, "unverifiable_superlative", "warning", report,
        "The copy makes a comparative claim ({label}): “{text}”, which cannot be "
        "checked against the listing.",
    )

    _check_features(text, haystack, report)
    _check_locations(text, listing, haystack, report)

    return report.finalise()


def validate_hashtags(hashtags: Any, listing, facts: dict[str, Any]) -> ValidationReport:
    """The same checks, applied to the hashtag set.

    Hashtags get validated too because "#8percentyield" is exactly as much a
    claim as writing it in a sentence, and it is easier to overlook.
    """
    report = ValidationReport()

    if not isinstance(hashtags, list):
        report.add(ValidationIssue("malformed_hashtags", "error", "Hashtags were not a list."))
        return report.finalise()

    if not hashtags:
        report.add(ValidationIssue("empty_hashtags", "error", "No hashtags were returned."))
        return report.finalise()

    tag_text = " ".join(tag for tag in hashtags if isinstance(tag, str))
    # Split camel-case so "#OceanViewPool" is checked word by word rather than
    # sailing through as one unrecognised token.
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", tag_text).replace("#", " ")

    # Camel-case splitting does not help an all-lowercase tag: "#7percentyield"
    # has no word boundary before "yield", so the \b-anchored claim patterns
    # miss it entirely. Hashtags are exactly where copy gets compressed into
    # one token, so high-risk words are also matched as bare substrings.
    for tag in hashtags:
        if not isinstance(tag, str):
            continue
        lowered = tag.lower().lstrip("#")
        for keyword in HIGH_RISK_TAG_KEYWORDS:
            if keyword in lowered:
                report.add(
                    ValidationIssue(
                        code="high_risk_hashtag",
                        severity="error",
                        message=(
                            f"The hashtag “{tag}” contains “{keyword}”, which makes "
                            f"a claim that cannot be derived from listing data."
                        ),
                        evidence=tag,
                    )
                )
                break

    haystack = _listing_haystack(listing, facts)
    allowed = allowed_numbers(facts, listing)

    _check_numbers(tag_text, allowed, report, "hashtags")
    _check_patterns(
        spaced, INVESTMENT_PATTERNS, "investment_claim", "error", report,
        "A hashtag makes an investment claim ({label}): “{text}”.",
    )
    _check_patterns(
        spaced, LEGAL_PATTERNS, "legal_claim", "error", report,
        "A hashtag makes a legal or planning claim ({label}): “{text}”.",
    )
    _check_features(spaced, haystack, report)
    _check_hashtags(hashtags, report)

    return report.finalise()


def validate_generation(payload: dict[str, Any], listing, facts: dict[str, Any]) -> ValidationReport:
    """Check a single caption + hashtags response.

    Kept for the single-caption path and for callers that want one combined
    report; the multi-variant pipeline validates each variant separately so an
    agent can see which one is at fault.
    """
    report = validate_text(
        payload.get("caption"), listing, facts, label="caption", max_length=1200
    )
    if report.issues and any(issue.code == "empty_text" for issue in report.issues):
        # Preserve the original code so existing callers keep matching on it.
        for issue in report.issues:
            if issue.code == "empty_text":
                issue.code = "empty_caption"
                issue.message = "The response contained no caption."
        return report

    hashtag_report = validate_hashtags(payload.get("hashtags", []), listing, facts)
    for issue in hashtag_report.issues:
        report.add(issue)

    return report.finalise()
