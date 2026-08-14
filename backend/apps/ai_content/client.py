"""OpenAI client wrapper.

THE API KEY NEVER LEAVES THE BACKEND
------------------------------------
It is read from ``OPENAI_API_KEY`` in the environment, used here, and appears
in no serializer, no template, no log line and no error message returned to a
client. The frontend never talks to OpenAI — it talks to our API, which talks
to OpenAI. That is the only arrangement where the key cannot be extracted from
a browser.

STRUCTURED OUTPUT, NOT PROSE
----------------------------
The call requests a JSON schema with ``strict`` mode, so the response is a
parseable object rather than free text we would have to scrape with regexes.
Scraping prose is how a caption ends up half-parsed and a hashtag ends up in
the caption body.

Everything the API returns is still treated as untrusted input: schema
compliance says the shape is right, not that the contents are true. That is
``validation.py``'s job.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)


class AIConfigurationError(RuntimeError):
    """The integration is not configured (missing key, missing package)."""


class AIGenerationError(RuntimeError):
    """The API call failed, or returned something unusable."""


@dataclass
class CompletionResult:
    payload: dict[str, Any]
    raw_text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    duration_ms: int

    @property
    def estimated_cost_usd(self) -> Decimal:
        return estimate_cost(self.model, self.prompt_tokens, self.completion_tokens)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    """Estimated USD cost for one call.

    Prices are per million tokens and configured in settings, because they
    change and because hardcoding them means the stored cost silently becomes
    wrong. An unknown model costs 0 rather than a guess — a zero is obviously
    missing data, whereas a plausible wrong number is not.
    """
    pricing = settings.OPENAI_PRICING.get(model)
    if not pricing:
        logger.info("No pricing configured for model %r; storing 0 cost.", model)
        return Decimal("0")

    input_price = Decimal(str(pricing.get("input", 0)))
    output_price = Decimal(str(pricing.get("output", 0)))
    million = Decimal("1000000")

    cost = (Decimal(prompt_tokens) / million) * input_price + (
        Decimal(completion_tokens) / million
    ) * output_price
    return cost.quantize(Decimal("0.000001"))


#: Shown to API clients when the integration is not set up. Deliberately says
#: nothing about *how* it is configured: the operator detail goes to the log,
#: which is where an operator is, and naming internal environment variables in
#: a response body is a habit that eventually leaks something that matters.
NOT_CONFIGURED_MESSAGE = (
    "Content generation is not configured on this server. Contact your "
    "administrator."
)


def _build_client():
    if not settings.OPENAI_API_KEY:
        logger.error(
            "OPENAI_API_KEY is empty — content generation is disabled. Set it in "
            ".env and restart the backend and worker."
        )
        raise AIConfigurationError(NOT_CONFIGURED_MESSAGE)
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        logger.error("The `openai` package is not installed; rebuild the backend image.")
        raise AIConfigurationError(NOT_CONFIGURED_MESSAGE) from exc

    return OpenAI(
        api_key=settings.OPENAI_API_KEY,
        timeout=settings.OPENAI_TIMEOUT_SECONDS,
        max_retries=settings.OPENAI_MAX_RETRIES,
    )


def complete_json(
    messages: list[dict[str, Any]],
    schema: dict[str, Any],
    *,
    schema_name: str = "listing_caption",
    model: str | None = None,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    timeout: float | None = None,
) -> CompletionResult:
    """Call the API and return the parsed JSON object plus usage.

    ``messages`` follows the provider's own shape, so a message's ``content``
    may be a plain string or a list of parts — which is how an image is
    attached. See ``image_part``.

    ``max_output_tokens`` and ``timeout`` default to the caption-sized settings.
    They are arguments rather than fixed reads because the jobs sharing this
    function are not the same size: a caption is a paragraph, a template
    extraction is several hundred numbers, and one budget cannot be right for
    both without being wrong for one of them.
    """
    client = _build_client()
    model = model or settings.OPENAI_MODEL
    if timeout is not None:
        # `with_options` returns a configured copy; mutating the shared client
        # would leak a long timeout into every later caption call.
        client = client.with_options(timeout=timeout)

    started = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=(
                settings.OPENAI_TEMPERATURE if temperature is None else temperature
            ),
            max_tokens=max_output_tokens or settings.OPENAI_MAX_OUTPUT_TOKENS,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": schema,
                    # The model cannot add keys or omit required ones.
                    "strict": True,
                },
            },
        )
    except Exception as exc:
        # Deliberately not re-raising the provider exception: its string can
        # contain request details, and this message travels to an API client.
        logger.warning("OpenAI call failed: %s", exc, exc_info=True)
        raise AIGenerationError(f"The content service call failed: {type(exc).__name__}") from exc

    duration_ms = int((time.monotonic() - started) * 1000)

    choice = response.choices[0] if response.choices else None
    if choice is None or not getattr(choice.message, "content", None):
        raise AIGenerationError("The content service returned an empty response.")

    if getattr(choice, "finish_reason", None) == "length":
        # Truncated JSON parses as garbage or, worse, as a half-sentence
        # caption. Better to fail loudly.
        raise AIGenerationError(
            "The response was cut off before it finished. Try again, or raise "
            "OPENAI_MAX_OUTPUT_TOKENS."
        )

    raw_text = choice.message.content
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AIGenerationError("The content service returned malformed JSON.") from exc

    if not isinstance(payload, dict):
        raise AIGenerationError("The content service returned an unexpected shape.")

    usage = getattr(response, "usage", None)
    return CompletionResult(
        payload=payload,
        raw_text=raw_text,
        model=getattr(response, "model", model),
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
        duration_ms=duration_ms,
    )


def image_part(png_bytes: bytes, *, detail: str = "high") -> dict[str, Any]:
    """One image, as a message content part.

    Inlined as a data URI rather than passed as a URL. A URL would mean the
    provider fetching from us, which requires the file to be publicly reachable
    — and template artwork sits behind the same auth as everything else. The
    bytes go out over the same TLS connection as the prompt instead.

    ``detail="high"`` is not the default for a cost reason on the provider's
    side, and is non-negotiable here: at low detail the image is downsampled to
    a thumbnail, and a model asked to measure element geometry against a
    thumbnail returns numbers that look precise and are not.
    """
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{encoded}", "detail": detail},
    }
