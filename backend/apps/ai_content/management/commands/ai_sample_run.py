"""Run the generation pipeline over sample listings and write the output to a file.

This is NOT a pass/fail test. It exists so a human can read fifteen captions in
one sitting and judge whether the prompt is any good — which is not something a
test can tell you.

    docker compose exec backend python manage.py ai_sample_run
    docker compose exec backend python manage.py ai_sample_run --offline

``--offline`` substitutes a canned response so the plumbing can be exercised
without a key or a bill. It tells you nothing about caption quality; use it to
check the harness, then run for real.

The sample listings are created inside a transaction that is rolled back, so a
review run leaves no rows behind.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import AgentProfile, Brokerage, Role, User
from apps.ai_content.client import CompletionResult
from apps.ai_content.models import ValidationStatus
from apps.ai_content.prompts import PROMPT_VERSION, build_messages
from apps.ai_content.sample_listings import SAMPLE_LISTINGS
from apps.ai_content.services import generate_for_listing
from apps.listings.models import Listing, VerificationStatus


def _offline_completion(messages, schema):
    """A canned, deliberately imperfect response.

    It quotes one figure from the prompt and otherwise stays vague, so an
    offline run exercises both the parser and the validator without pretending
    to be a real sample of model quality.
    """
    import re

    user_message = messages[-1]["content"]

    # Read the tagged fact lines rather than the first number in the text —
    # the facts block is itself numbered, so "1." would otherwise be picked up
    # as a price and every sample would be (correctly) rejected for it.
    def fact(name: str) -> str:
        match = re.search(rf"^\d+\.\s*\[{name}\]\s*(.+)$", user_message, re.MULTILINE)
        return match.group(1).strip() if match else ""

    price = fact("price")
    city = fact("city")

    caption = "A considered home in a location worth knowing. "
    if city:
        caption = f"A considered home in {city}. "
    if price:
        caption += f"Guided at {price}. "
    caption += "Enquiries welcome."

    payload = {
        "caption": caption,
        "hashtags": ["#realestate", "#property", "#forsale", "#home"],
        "facts_used": [name for name in ("city", "price") if fact(name)],
    }
    return CompletionResult(
        payload=payload,
        raw_text=json.dumps(payload),
        model="offline-stub",
        prompt_tokens=len(user_message.split()),
        completion_tokens=len(caption.split()),
        total_tokens=len(user_message.split()) + len(caption.split()),
        duration_ms=1,
    )


class Command(BaseCommand):
    help = "Generate captions for sample listings and write them to a file for review."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--offline",
            action="store_true",
            help="Use a canned response instead of calling OpenAI (harness check only).",
        )
        parser.add_argument(
            "--out",
            default="/app/ai_sample_run.md",
            help="Where to write the review file.",
        )
        parser.add_argument("--limit", type=int, default=0, help="Only run the first N samples.")

    def handle(self, *args, **options) -> None:
        offline = options["offline"]
        limit = options["limit"]
        out_path = Path(options["out"])

        from django.conf import settings

        # A management command IS the operator context, so naming the variable
        # here is right — unlike in an API response.
        if not offline and not settings.OPENAI_API_KEY:
            raise CommandError(
                "OPENAI_API_KEY is not set. Add it to .env and restart the backend, "
                "or pass --offline to check the harness without calling the API."
            )

        samples = SAMPLE_LISTINGS[:limit] if limit else SAMPLE_LISTINGS
        completion_fn = _offline_completion if offline else None

        rows = []
        started = time.monotonic()

        # Everything below happens inside a transaction that is rolled back, so
        # a review run never leaves sample listings in the database.
        try:
            with transaction.atomic():
                agent_profile, user = self._scratch_agent()

                for index, spec in enumerate(samples, start=1):
                    note = spec.pop("_note", "")
                    listing = self._scratch_listing(agent_profile, spec)
                    spec["_note"] = note

                    self.stdout.write(f"  [{index}/{len(samples)}] {listing.city or 'unknown'}…")

                    kwargs = {"completion_fn": completion_fn} if completion_fn else {}
                    generation = generate_for_listing(listing, user, **kwargs)

                    messages, facts = build_messages(listing)
                    rows.append(
                        {
                            "index": index,
                            "note": note,
                            "facts": facts,
                            "generation": generation,
                            "listing": listing,
                        }
                    )

                raise _Rollback()
        except _Rollback:
            pass

        elapsed = time.monotonic() - started
        report = self._render(rows, offline=offline, elapsed=elapsed)
        out_path.write_text(report, encoding="utf-8")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Wrote {out_path} ({len(rows)} samples)."))
        self._summarise(rows)

    # -- scratch fixtures ---------------------------------------------------

    def _scratch_agent(self):
        user, _ = User.objects.get_or_create(
            email="ai-sample-run@nehrux.invalid",
            defaults={"role": Role.AGENT, "full_name": "Sample Run"},
        )
        brokerage, _ = Brokerage.objects.get_or_create(
            name="Sample Run Brokerage",
            defaults={"required_disclaimer": "Sample data. Not a real listing."},
        )
        profile, _ = AgentProfile.objects.get_or_create(user=user)
        profile.brokerage = brokerage
        profile.save()
        return profile, user

    def _scratch_listing(self, agent_profile, spec: dict) -> Listing:
        data = {key: value for key, value in spec.items() if not key.startswith("_")}
        listing = Listing.objects.create(
            agent=agent_profile,
            # Verified on purpose: only verified listings may be generated
            # from, and the sample run must exercise the real path.
            verification_status=VerificationStatus.VERIFIED,
            **data,
        )
        return listing

    # -- reporting ----------------------------------------------------------

    def _render(self, rows, *, offline: bool, elapsed: float) -> str:
        stamp = datetime.now(dt_timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines: list[str] = []

        lines.append("# Caption quality review")
        lines.append("")
        lines.append(
            f"Generated {stamp} | prompt `{PROMPT_VERSION}` | {len(rows)} samples | {elapsed:.1f}s"
        )
        if offline:
            lines.append("")
            lines.append(
                "> **OFFLINE RUN.** These captions come from a canned stub, not from "
                "the model. They tell you the harness works and nothing about quality. "
                "Re-run without `--offline` to judge the prompt."
            )
        lines.append("")
        lines.append("Read for: invented numbers, features the listing does not have, "
                     "investment or legal claims, and whether the sparse listings stay short.")
        lines.append("")
        lines.append("---")
        lines.append("")

        for row in rows:
            generation = row["generation"]
            lines.append(f"## {row['index']}. {row['listing'].full_address or 'Unnamed listing'}")
            lines.append("")
            if row["note"]:
                lines.append(f"*Why this sample:* {row['note']}")
                lines.append("")

            lines.append("**Facts given to the model**")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(row["facts"], indent=2, default=str))
            lines.append("```")
            lines.append("")

            if generation.job_status != "ready":
                lines.append(f"**FAILED:** {generation.error_message}")
                lines.append("")
                lines.append("---")
                lines.append("")
                continue

            badge = {
                ValidationStatus.PASSED: "PASSED",
                ValidationStatus.FLAGGED: "FLAGGED",
                ValidationStatus.REJECTED: "REJECTED",
            }.get(generation.validation_status, generation.validation_status)

            lines.append(f"**Validation: {badge}**")
            lines.append("")

            caption = generation.caption or (generation.rejected_output or {}).get("caption", "")
            hashtags = generation.hashtags or (generation.rejected_output or {}).get("hashtags", [])

            if generation.validation_status == ValidationStatus.REJECTED:
                lines.append("> Rejected copy, shown only for review — not stored as usable:")
                lines.append("")

            lines.append("**Caption**")
            lines.append("")
            lines.append(f"> {caption or '(empty)'}")
            lines.append("")
            lines.append(f"**Hashtags:** {' '.join(hashtags) if hashtags else '(none)'}")
            lines.append("")

            if generation.validation_issues:
                lines.append("**Validation issues**")
                lines.append("")
                for issue in generation.validation_issues:
                    lines.append(
                        f"- `{issue['severity']}` **{issue['code']}** — {issue['message']}"
                    )
                lines.append("")

            lines.append(
                f"*{generation.model_name} | {generation.total_tokens} tokens "
                f"(prompt {generation.prompt_tokens} / completion {generation.completion_tokens}) "
                f"| ${generation.estimated_cost_usd} | {generation.duration_ms} ms*"
            )
            lines.append("")
            lines.append("---")
            lines.append("")

        ready = [row["generation"] for row in rows if row["generation"].job_status == "ready"]
        total_cost = sum(g.estimated_cost_usd for g in ready)
        total_tokens = sum(g.total_tokens for g in ready)

        lines.append("## Totals")
        lines.append("")
        lines.append(f"- Samples: {len(rows)} ({len(ready)} completed)")
        lines.append(
            f"- Validation: "
            f"{sum(1 for g in ready if g.validation_status == ValidationStatus.PASSED)} passed, "
            f"{sum(1 for g in ready if g.validation_status == ValidationStatus.FLAGGED)} flagged, "
            f"{sum(1 for g in ready if g.validation_status == ValidationStatus.REJECTED)} rejected"
        )
        lines.append(f"- Tokens: {total_tokens:,}")
        lines.append(f"- Estimated cost: ${total_cost}")
        lines.append("")

        return "\n".join(lines)

    def _summarise(self, rows) -> None:
        ready = [row["generation"] for row in rows if row["generation"].job_status == "ready"]
        counts = {status: 0 for status in (ValidationStatus.PASSED, ValidationStatus.FLAGGED, ValidationStatus.REJECTED)}
        for generation in ready:
            counts[generation.validation_status] = counts.get(generation.validation_status, 0) + 1

        self.stdout.write(
            f"  passed {counts[ValidationStatus.PASSED]} | "
            f"flagged {counts[ValidationStatus.FLAGGED]} | "
            f"rejected {counts[ValidationStatus.REJECTED]}"
        )
        self.stdout.write(
            f"  {sum(g.total_tokens for g in ready):,} tokens | "
            f"${sum(g.estimated_cost_usd for g in ready)} estimated"
        )


class _Rollback(Exception):
    """Signals the atomic block to roll the sample data back."""
