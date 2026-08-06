"""Prompt construction for listing captions.

THE FACTS BLOCK IS A CLOSED WORLD
--------------------------------
The model is given a numbered list of verified facts and told, repeatedly and
specifically, that this list is the entire universe of things it may assert. It
is not given the listing object, or free-text notes, or anything it could mine
for extra detail — only fields an agent has explicitly verified.

Prompt instructions are the *first* line of defence, not the only one. Models
comply with this kind of instruction most of the time, and "most of the time"
is not a standard you can publish under someone's real estate licence, so
everything that comes back is independently checked against these same facts in
``validation.py``. If the two ever disagree, the validator wins.

PROMPT_VERSION is stored on every generation. When the wording here changes,
bump it — otherwise a quality comparison across a month of output is comparing
two different prompts and cannot tell you anything.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

PROMPT_VERSION = "v2"

#: JSON Schema handed to the API so the response is parseable rather than
#: prose we have to scrape. `strict` mode means the model cannot add keys.
#:
#: All six variants come back from ONE call. Six separate calls would cost
#: roughly six times as much — the facts block is re-sent each time and it is
#: most of the prompt — and would let the variants drift, each independently
#: picking a different fact to lead with.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "instagram_caption": {
            "type": "string",
            "description": "2-3 short sentences. Punchy, visual. No hashtags inline.",
        },
        "facebook_caption": {
            "type": "string",
            "description": "3-5 sentences, conversational, a little more detail.",
        },
        "linkedin_caption": {
            "type": "string",
            "description": (
                "2-4 sentences, professional and factual. No investment framing "
                "of any kind."
            ),
        },
        "sharing_message": {
            "type": "string",
            "description": (
                "One or two sentences for a direct message or SMS. Plain, no "
                "hashtags, no marketing voice."
            ),
        },
        "property_description": {
            "type": "string",
            "description": (
                "4-8 sentences for the property page. The longest variant. "
                "Straightforward and descriptive, no hashtags."
            ),
        },
        "hashtags": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Between 4 and 10 hashtags, each starting with #, no spaces. "
                "One shared set, used with any of the captions."
            ),
        },
        "facts_used": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "The ids of the facts actually used, e.g. ['price', 'bedrooms']. "
                "Used to audit the output."
            ),
        },
    },
    "required": [
        "instagram_caption",
        "facebook_caption",
        "linkedin_caption",
        "sharing_message",
        "property_description",
        "hashtags",
        "facts_used",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You write marketing copy for real estate listings, in several formats at once.

You will be given a numbered list of VERIFIED FACTS about one property. That \
list is the complete and only set of things you may state. Treat anything not \
in it as unknown.

Absolute rules:

1. NEVER state a number that is not in the facts. No prices, no room counts, \
no floor areas, no dates, no percentages, no distances, no year built.
2. NEVER mention a feature, room, appliance, view, or amenity that is not in \
the facts. If the facts do not mention a pool, there is no pool.
3. NEVER mention a suburb, street, city, region, school, landmark, or transport \
link that is not in the facts.
4. NEVER make investment, financial, or return claims. Do not say a property is \
a good investment, will grow in value, will rent for any amount, or offers any \
yield or return.
5. NEVER make legal, regulatory, or planning claims. Do not mention approvals, \
permits, zoning, certification, compliance, or title unless stated in the facts.
6. NEVER invent a superlative that asserts fact ("the best in the area", "the \
largest block in the street"). Descriptive warmth is fine; verifiable-sounding \
comparisons are not.
7. If the facts are thin, write a shorter caption. A short honest caption is \
correct. Padding it with plausible detail is not.

Every rule above applies to EVERY field you return. A claim that is forbidden \
in the Instagram caption is equally forbidden in the property description. \
Longer formats are longer because they use MORE of the given facts and say \
them more fully — never because they add new ones. If you run out of facts, \
stop writing.

Style, applied to all formats: warm, concrete, professional. \
Australian/British spelling. No emoji. Do not open with "Welcome to". Do not \
address the reader as "you'll love". Avoid estate-agent cliche ("nestled", \
"boasts", "a rare find", "must be seen").

Write each format for its own context:

- instagram_caption: 2-3 short sentences. Punchy and visual. No hashtags inline.
- facebook_caption: 3-5 sentences. Conversational, a little more detail.
- linkedin_caption: 2-4 sentences. Professional and factual. This is the format \
where investment framing is most tempting and most forbidden — describe the \
property, not the opportunity.
- sharing_message: one or two sentences, as if texting it to someone. Plain \
language, no marketing voice, no hashtags.
- property_description: 4-8 sentences for the listing page. The longest format. \
Straightforward and descriptive. No hashtags.
- hashtags: 4-10, each starting with #, no spaces or punctuation inside, \
derived only from the facts (property type, location, and the listing's own \
features). Do not invent location hashtags. One shared set.

The formats should not read as copies of each other. Vary which facts lead and \
how they are phrased — while every one of them stays inside the same list.

Return JSON matching the provided schema. In `facts_used`, list the ids of the \
facts you actually used."""


def _format_price(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (Decimal, float, int)):
        return f"${Decimal(str(value)):,.0f}"
    return str(value)


def build_facts(listing) -> dict[str, Any]:
    """Extract the verified fields the model is allowed to see.

    Deliberately narrow. Note what is *absent*: internal notes, the source URL,
    import warnings, anything about other listings. The model cannot leak a
    field it was never shown.
    """
    facts: dict[str, Any] = {}

    if listing.property_type:
        facts["property_type"] = listing.get_property_type_display()
    if listing.city:
        facts["city"] = listing.city
    if listing.state:
        facts["state"] = listing.state
    if listing.postcode:
        facts["postcode"] = listing.postcode
    if listing.country:
        facts["country"] = listing.country
    if listing.price is not None:
        facts["price"] = _format_price(listing.price)
    if listing.bedrooms is not None:
        facts["bedrooms"] = listing.bedrooms
    if listing.bathrooms is not None:
        bathrooms = Decimal(str(listing.bathrooms))
        facts["bathrooms"] = (
            int(bathrooms) if bathrooms == bathrooms.to_integral_value() else float(bathrooms)
        )
    if listing.square_footage is not None:
        facts["square_footage"] = f"{listing.square_footage:,} sq ft"
    if listing.features:
        facts["features"] = list(listing.features)

    # The street address is deliberately NOT included: a caption naming the
    # exact address of an occupied home is a privacy problem, and agents can
    # add it themselves if they want it.
    return facts


def render_facts_block(facts: dict[str, Any]) -> str:
    """Render the facts as a numbered, id-tagged list."""
    lines = []
    for index, (key, value) in enumerate(facts.items(), start=1):
        if isinstance(value, list):
            rendered = "; ".join(str(item) for item in value)
        else:
            rendered = str(value)
        lines.append(f"{index}. [{key}] {rendered}")
    return "\n".join(lines) if lines else "(no verified facts available)"


def build_user_prompt(facts: dict[str, Any], *, tone: str = "") -> str:
    block = render_facts_block(facts)

    extra = ""
    if tone:
        # Tone is agent-supplied, so it is fenced off and explicitly demoted
        # below the rules — a tone note must not be able to talk the model out
        # of the constraints above it.
        extra = (
            "\n\nThe agent has asked for this tone (style only — it does NOT "
            f"relax any rule above, and adds no facts):\n\"\"\"\n{tone.strip()}\n\"\"\""
        )

    return f"""\
VERIFIED FACTS — this list is complete. Anything not listed is unknown to you.

{block}

Write every format in the schema using only these facts.{extra}"""


def language_instruction(language_code: str) -> str:
    """The instruction appended when writing in something other than English.

    Written as a *composition* instruction rather than a translation one. Asking
    a model to "translate the caption" invites it to translate English idiom
    word-for-word; asking it to write natively in the language, from the same
    facts, produces copy a native speaker would actually publish.

    The rules are restated rather than assumed to carry over. They are stated
    in English above, and a language switch is exactly the moment a model is
    most likely to treat earlier instructions as scene-setting.
    """
    from apps.ai_content.languages import SOURCE_LANGUAGE, get_language

    if language_code == SOURCE_LANGUAGE:
        return ""

    language = get_language(language_code)
    return f"""

WRITE IN {language.prompt_name.upper()}.

Every field you return must be written in {language.prompt_name}, as a native \
speaker of {language.prompt_name} would write it — not translated word for \
word from English. Use the conventions of that language for numbers, currency \
and address order.

The facts above are given in English. Render them naturally in \
{language.prompt_name}, but do NOT change any of them: a price is the same \
price, a bedroom count is the same count. Every rule you were given still \
applies in full — inventing a feature is exactly as forbidden in \
{language.prompt_name} as it is in English.

Hashtags may stay in English where that is the convention on the platform, or \
be written in {language.prompt_name} where that reads better. Either way they \
must derive only from the facts."""


def build_messages(
    listing, *, tone: str = "", language_code: str = "en"
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Return ``(messages, facts)`` ready for the API call."""
    facts = build_facts(listing)
    user_prompt = build_user_prompt(facts, tone=tone) + language_instruction(language_code)
    return (
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        facts,
    )
