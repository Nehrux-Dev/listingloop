"""Supported output languages, and how much fact-checking each one gets.

=============================================================================
THE VALIDATOR IS ENGLISH. SAYING SO IS THE WHOLE POINT OF THIS FILE.
=============================================================================

The fact-check built in Step 6 is English-specific in three of its five rules:
the investment/legal claim patterns, the feature vocabulary, and the written-out
number words are all English strings. Point it at Spanish output and it finds
nothing — not because the copy is clean, but because it cannot read it.

That failure mode is worse than having no validator at all, because the report
would come back "passed" and an agent would reasonably believe the copy had
been checked.

So coverage is declared per language, and the checks split into two kinds:

  LANGUAGE-AGNOSTIC — numbers, hashtag shape, link counts. Digits are digits in
  every language, and an invented price is the single most dangerous error, so
  this runs everywhere and is where most of the protection actually lives.

  LANGUAGE-SPECIFIC — claim phrases, feature vocabulary, number words. Only run
  where a vocabulary exists.

A language with partial coverage can never come back PASSED. It is FLAGGED,
with an explicit issue saying which checks did not run and that a human has to
read it. That is a smaller lie than a green tick.

ADDING A LANGUAGE PROPERLY means adding its vocabulary in
``apps.ai_content.vocabularies``, not just adding it to this list.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.conf import settings


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    #: What the model is told to write in. Spelled out because "write in ZH" is
    #: not an instruction a model follows reliably.
    prompt_name: str
    #: Right-to-left scripts need the UI to say so.
    rtl: bool = False
    #: Checks that have a vocabulary for this language. Anything not listed
    #: does not run, and its absence is reported.
    covered_checks: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_fully_covered(self) -> bool:
        return self.covered_checks >= LANGUAGE_SPECIFIC_CHECKS

    @property
    def missing_checks(self) -> list[str]:
        return sorted(LANGUAGE_SPECIFIC_CHECKS - self.covered_checks)


#: The checks that need to know the language to work at all.
LANGUAGE_SPECIFIC_CHECKS = frozenset(
    {"investment_claims", "legal_claims", "feature_vocabulary", "number_words"}
)

#: Checks that work regardless of language. Note that this is where the
#: highest-value protection sits — an invented price is caught in every
#: language, because a digit is a digit.
LANGUAGE_AGNOSTIC_CHECKS = frozenset({"numbers", "hashtags", "links", "length"})

FULL_COVERAGE = LANGUAGE_SPECIFIC_CHECKS

#: Every language the system knows how to ask for. Which of these are actually
#: offered is controlled by AI_CONTENT_LANGUAGES in settings — the launch set
#: is a business decision, not a code change.
KNOWN_LANGUAGES: dict[str, Language] = {
    "en": Language("en", "English", "English", covered_checks=FULL_COVERAGE),
    "fr": Language("fr", "French", "French"),
    "es": Language("es", "Spanish", "Spanish"),
    "pt": Language("pt", "Portuguese", "Portuguese"),
    "de": Language("de", "German", "German"),
    "it": Language("it", "Italian", "Italian"),
    "zh-hans": Language("zh-hans", "Chinese (Simplified)", "Simplified Chinese"),
    "zh-hant": Language("zh-hant", "Chinese (Traditional)", "Traditional Chinese"),
    "hi": Language("hi", "Hindi", "Hindi"),
    "pa": Language("pa", "Punjabi", "Punjabi (Gurmukhi script)"),
    "ar": Language("ar", "Arabic", "Arabic", rtl=True),
    "vi": Language("vi", "Vietnamese", "Vietnamese"),
    "tl": Language("tl", "Tagalog", "Tagalog"),
    "ko": Language("ko", "Korean", "Korean"),
    "ja": Language("ja", "Japanese", "Japanese"),
}

#: English is always available: it is the language the validator actually
#: speaks, and the one the source facts are written in.
SOURCE_LANGUAGE = "en"


def enabled_languages() -> list[Language]:
    """The languages this deployment offers, in configured order."""
    codes = getattr(settings, "AI_CONTENT_LANGUAGES", [SOURCE_LANGUAGE])
    languages = []
    seen = set()
    for code in codes:
        language = KNOWN_LANGUAGES.get(code)
        if language and code not in seen:
            languages.append(language)
            seen.add(code)
    if SOURCE_LANGUAGE not in seen:
        languages.insert(0, KNOWN_LANGUAGES[SOURCE_LANGUAGE])
    return languages


def enabled_codes() -> list[str]:
    return [language.code for language in enabled_languages()]


def get_language(code: str) -> Language:
    language = KNOWN_LANGUAGES.get(code)
    if language is None:
        raise ValueError(
            f"Unknown language '{code}'. Known: {', '.join(sorted(KNOWN_LANGUAGES))}"
        )
    return language


def is_enabled(code: str) -> bool:
    return code in enabled_codes()
