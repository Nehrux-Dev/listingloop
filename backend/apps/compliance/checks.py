"""Check-type implementations.

Each check is a small pure function: given a rule and a subject, did it pass,
and what should the agent be told? No check reaches into the database or knows
anything about listings, designs or AI content — that translation happens in
``subjects.py``, so a check works the same wherever the text came from.

=============================================================================
"custom" DOES NOT IMPORT ANYTHING FROM THE DATABASE
=============================================================================

The obvious implementation of a custom check is ``import_string(rule_data
["handler"])``. That would be remote code execution by configuration: anyone
who can edit a rule in the admin — a non-engineer, by design — could name any
importable path and have it imported and called.

So ``custom`` resolves against ``CUSTOM_HANDLERS``, a registry populated in
code at import time. A name that is not registered produces a clearly reported
error result, never an import.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

MAX_EVIDENCE = 5


@dataclass
class CheckOutcome:
    passed: bool
    message: str
    evidence: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


#: check_type -> handler
CHECKS: dict[str, Callable[[Any, Any], CheckOutcome]] = {}
#: check_type -> validator for rule_data
VALIDATORS: dict[str, Callable[[dict], list[str]]] = {}
#: name -> callable, for the `custom` check type. Populated in code only.
CUSTOM_HANDLERS: dict[str, Callable[[Any, Any], CheckOutcome]] = {}


def register(check_type: str, validator: Callable[[dict], list[str]] | None = None):
    def decorator(func):
        CHECKS[check_type] = func
        if validator is not None:
            VALIDATORS[check_type] = validator
        return func

    return decorator


def register_custom_handler(name: str):
    """Register a code-defined check that data alone cannot express.

    Anything registered here can be selected by name from the admin. Keep the
    set small: every handler is business logic that a rule editor cannot see
    or change, which is the thing this app exists to avoid.
    """

    def decorator(func):
        CUSTOM_HANDLERS[name] = func
        return func

    return decorator


def normalise(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation that varies.

    Disclaimers get re-typed, re-wrapped and smart-quoted on their way through
    a CMS. Comparing raw strings would fail on a curly apostrophe, which is not
    a compliance failure.
    """
    text = (text or "").lower()
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _phrase_pattern(phrase: str, whole_word: bool) -> re.Pattern[str]:
    escaped = re.escape(normalise(phrase))
    # Let a multi-word phrase match across any whitespace run.
    escaped = escaped.replace(r"\ ", r"\s+")
    if whole_word:
        escaped = rf"\b{escaped}\b"
    return re.compile(escaped, re.IGNORECASE)


# ---------------------------------------------------------------------------
# required_field_present
# ---------------------------------------------------------------------------


def _validate_required_field(data: dict) -> list[str]:
    if not data.get("field"):
        return ["'field' is required, e.g. {\"field\": \"brokerage_name\"}."]
    return []


@register("required_field_present", _validate_required_field)
def check_required_field_present(rule, subject) -> CheckOutcome:
    name = rule.rule_data.get("field", "")
    label = rule.rule_data.get("label") or name.replace("_", " ")

    if name not in subject.fields:
        # The subject does not carry this field at all — that is a rule/subject
        # mismatch, not a compliance failure, and saying so is more useful than
        # a failure the agent cannot act on.
        return CheckOutcome(
            passed=True,
            message=f"“{label}” is not applicable to this content.",
            details={"skipped": True, "reason": "field_not_on_subject"},
        )

    value = subject.fields.get(name)
    present = bool(str(value).strip()) if value is not None else False

    return CheckOutcome(
        passed=present,
        message=(
            f"“{label}” is present." if present else f"“{label}” is required and is empty."
        ),
        details={"field": name},
    )


# ---------------------------------------------------------------------------
# disclaimer_present
# ---------------------------------------------------------------------------


def _validate_disclaimer(data: dict) -> list[str]:
    errors = []
    if not (data.get("text") or "").strip():
        errors.append("'text' is required — the disclaimer wording to look for.")
    match = data.get("match", "normalised")
    if match not in ("normalised", "exact", "all_words"):
        errors.append("'match' must be one of: normalised, exact, all_words.")
    return errors


@register("disclaimer_present", _validate_disclaimer)
def check_disclaimer_present(rule, subject) -> CheckOutcome:
    required = rule.rule_data.get("text", "")
    mode = rule.rule_data.get("match", "normalised")
    haystack = subject.combined_text

    if mode == "exact":
        found = required in haystack
    elif mode == "all_words":
        # Tolerant: the disclaimer may be reflowed or split across elements, so
        # every significant word must appear, not the exact run.
        words = [word for word in normalise(required).split() if len(word) > 2]
        normalised_haystack = normalise(haystack)
        found = all(word in normalised_haystack for word in words)
    else:
        found = normalise(required) in normalise(haystack)

    return CheckOutcome(
        passed=found,
        message=(
            "The required disclaimer is present."
            if found
            else "The required disclaimer is missing."
        ),
        evidence=[] if found else [required[:160]],
        details={"match": mode},
    )


# ---------------------------------------------------------------------------
# prohibited_phrase
# ---------------------------------------------------------------------------


def _validate_phrases(data: dict) -> list[str]:
    phrases = data.get("phrases")
    if not isinstance(phrases, list) or not phrases:
        return ['\'phrases\' must be a non-empty list, e.g. {"phrases": ["guaranteed return"]}.']
    if any(not isinstance(item, str) or not item.strip() for item in phrases):
        return ["Every entry in 'phrases' must be a non-empty string."]
    return []


@register("prohibited_phrase", _validate_phrases)
def check_prohibited_phrase(rule, subject) -> CheckOutcome:
    phrases = rule.rule_data.get("phrases", [])
    whole_word = bool(rule.rule_data.get("whole_word", True))
    haystack = normalise(subject.combined_text)

    hits = [
        phrase
        for phrase in phrases
        if _phrase_pattern(phrase, whole_word).search(haystack)
    ]

    return CheckOutcome(
        passed=not hits,
        message=(
            "No prohibited phrases found."
            if not hits
            else "Contains phrasing that is not allowed: "
            + ", ".join(f"“{hit}”" for hit in hits[:MAX_EVIDENCE])
        ),
        evidence=hits[:MAX_EVIDENCE],
        details={"checked": len(phrases)},
    )


# ---------------------------------------------------------------------------
# required_phrase
# ---------------------------------------------------------------------------


def _validate_required_phrase(data: dict) -> list[str]:
    errors = _validate_phrases(data)
    if data.get("mode", "any") not in ("any", "all"):
        errors.append("'mode' must be 'any' or 'all'.")
    return errors


@register("required_phrase", _validate_required_phrase)
def check_required_phrase(rule, subject) -> CheckOutcome:
    phrases = rule.rule_data.get("phrases", [])
    mode = rule.rule_data.get("mode", "any")
    whole_word = bool(rule.rule_data.get("whole_word", True))
    haystack = normalise(subject.combined_text)

    missing = [
        phrase
        for phrase in phrases
        if not _phrase_pattern(phrase, whole_word).search(haystack)
    ]
    passed = (len(missing) < len(phrases)) if mode == "any" else not missing

    if passed:
        message = "The required wording is present."
    elif mode == "any":
        message = "None of the required phrases appear: " + ", ".join(
            f"“{phrase}”" for phrase in phrases[:MAX_EVIDENCE]
        )
    else:
        message = "Required wording is missing: " + ", ".join(
            f"“{phrase}”" for phrase in missing[:MAX_EVIDENCE]
        )

    return CheckOutcome(
        passed=passed, message=message, evidence=missing[:MAX_EVIDENCE], details={"mode": mode}
    )


# ---------------------------------------------------------------------------
# prohibited_pattern
# ---------------------------------------------------------------------------


def _validate_pattern(data: dict) -> list[str]:
    pattern = data.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        return ["'pattern' is required and must be a regular expression."]
    try:
        re.compile(pattern)
    except re.error as exc:
        return [f"'pattern' is not a valid regular expression: {exc}"]
    return []


@register("prohibited_pattern", _validate_pattern)
def check_prohibited_pattern(rule, subject) -> CheckOutcome:
    pattern = rule.rule_data.get("pattern", "")
    flags = re.IGNORECASE if "i" in str(rule.rule_data.get("flags", "i")) else 0

    # Compiled here rather than trusted: a rule row is user input, and an
    # invalid expression must report a rule problem, not raise into the caller.
    try:
        compiled = re.compile(pattern, flags)
    except re.error as exc:
        return CheckOutcome(
            passed=True,
            message=f"This rule's pattern is invalid and was not applied ({exc}).",
            details={"rule_error": True},
        )

    hits = [match.group(0) for match in compiled.finditer(subject.combined_text)]

    return CheckOutcome(
        passed=not hits,
        message=(
            "No prohibited patterns found."
            if not hits
            else "Contains wording that is not allowed: "
            + ", ".join(f"“{hit}”" for hit in hits[:MAX_EVIDENCE])
        ),
        evidence=hits[:MAX_EVIDENCE],
    )


# ---------------------------------------------------------------------------
# length_limit
# ---------------------------------------------------------------------------


def _validate_length(data: dict) -> list[str]:
    if "max" not in data and "min" not in data:
        return ["At least one of 'max' or 'min' is required."]
    for key in ("max", "min"):
        if key in data and not isinstance(data[key], int):
            return [f"'{key}' must be a whole number."]
    return []


@register("length_limit", _validate_length)
def check_length_limit(rule, subject) -> CheckOutcome:
    field_name = rule.rule_data.get("field")
    if field_name:
        if field_name not in subject.text_blocks:
            return CheckOutcome(
                passed=True,
                message=f"“{field_name}” is not part of this content.",
                details={"skipped": True, "reason": "block_not_on_subject"},
            )
        text = subject.text_blocks[field_name]
        label = field_name.replace("_", " ")
    else:
        text = subject.combined_text
        label = "content"

    length = len(text)
    maximum = rule.rule_data.get("max")
    minimum = rule.rule_data.get("min")

    if maximum is not None and length > maximum:
        return CheckOutcome(
            passed=False,
            message=f"The {label} is {length} characters; the limit is {maximum}.",
            details={"length": length, "max": maximum},
        )
    if minimum is not None and length < minimum:
        return CheckOutcome(
            passed=False,
            message=f"The {label} is {length} characters; at least {minimum} is required.",
            details={"length": length, "min": minimum},
        )

    return CheckOutcome(
        passed=True,
        message=f"The {label} length is within limits.",
        details={"length": length},
    )


# ---------------------------------------------------------------------------
# custom
# ---------------------------------------------------------------------------


def _validate_custom(data: dict) -> list[str]:
    handler = data.get("handler")
    if not handler:
        return ["'handler' is required — the name of a registered handler."]
    if handler not in CUSTOM_HANDLERS:
        return [
            f"No handler named '{handler}' is registered. Available: "
            + (", ".join(sorted(CUSTOM_HANDLERS)) or "(none)")
        ]
    return []


@register("custom", _validate_custom)
def check_custom(rule, subject) -> CheckOutcome:
    name = rule.rule_data.get("handler", "")
    handler = CUSTOM_HANDLERS.get(name)

    if handler is None:
        # Reported, never imported. See the module docstring.
        return CheckOutcome(
            passed=True,
            message=(
                f"This rule refers to a handler named '{name}', which is not "
                f"registered. The rule was skipped — ask an engineer to add it."
            ),
            details={"rule_error": True, "handler": name},
        )

    return handler(rule, subject)


# ---------------------------------------------------------------------------
# Example custom handler
# ---------------------------------------------------------------------------


@register_custom_handler("example_price_needs_qualifier")
def example_price_needs_qualifier(rule, subject) -> CheckOutcome:
    """EXAMPLE ONLY — demonstrates the registry; not a real requirement.

    Flags a bare dollar figure that is not accompanied by a qualifying word.
    Included so there is a working reference for adding a real one, and named
    'example_' so nobody mistakes it for an approved rule.
    """
    qualifiers = rule.rule_data.get(
        "qualifiers", ["guide", "guided", "offers", "from", "circa", "price"]
    )
    text = normalise(subject.combined_text)
    prices = re.findall(r"\$\s?[\d,]+(?:\.\d+)?[km]?", text)
    if not prices:
        return CheckOutcome(True, "No price figures to qualify.")

    qualified = any(re.search(rf"\b{re.escape(word)}\b", text) for word in qualifiers)
    return CheckOutcome(
        passed=qualified,
        message=(
            "Price figures carry a qualifying word."
            if qualified
            else "A price is stated without a qualifier such as “guide” or “offers”."
        ),
        evidence=prices[:MAX_EVIDENCE],
    )


def validate_rule_data(check_type: str, rule_data: dict) -> list[str]:
    """Validate a rule's data. Used by the model's ``clean()``."""
    if check_type not in CHECKS:
        return [f"Unknown check type '{check_type}'."]
    if not isinstance(rule_data, dict):
        return ["Rule data must be a JSON object."]
    validator = VALIDATORS.get(check_type)
    return validator(rule_data) if validator else []


def available_check_types() -> list[str]:
    return sorted(CHECKS)


def available_custom_handlers() -> list[str]:
    return sorted(CUSTOM_HANDLERS)
