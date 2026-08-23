"""Score the extraction pipeline over a folder of real flyers.

WHY THIS EXISTS
------------------------------------------------------------------------------
The extraction pipeline is an AI feature, and AI features regress silently — no
stack trace, just a layout that quietly comes back looking wronger than it did
last week. Judging that by opening one flyer at a time does not scale and does
not catch regressions. This runs the whole pipeline over a *golden set* of real
uploads and reports a number per file, so a change that makes extraction worse
shows up as a dropped score rather than a support ticket.

    python manage.py run_extraction_evals                 # score the golden set
    python manage.py run_extraction_evals --validate      # also render-and-compare
    python manage.py run_extraction_evals --baseline eval/reports/baseline.json \
        --fail-on-regression                              # gate a CI job

WHAT IT DOES AND DOES NOT NEED
------------------------------------------------------------------------------
A text PDF runs the free structural path — no API key, no browser. An image
runs the vision model, which needs the key. ``--validate`` additionally renders
each result through the renderer service to produce a fidelity score, so it
needs the renderer reachable. Without ``--validate`` the report is structural
(element count, unclassified fills) and entirely offline for PDFs.

Nothing here is destructive: it builds no templates and writes only a JSON
report. Per-file failures are caught and recorded, so one unreadable flyer does
not abandon the run.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.templates.importing import (
    TemplateImportError,
    bake_assets,
    extract_page,
    normalise_elements,
    rasterise,
)
from apps.templates.serializers import _WARNING_TEXT

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}

#: A fidelity drop larger than this against the baseline is a regression. Small
#: wobble is expected — the vision path is not perfectly deterministic — so the
#: threshold is above the noise floor.
_FIDELITY_REGRESSION = 0.03


def evaluate_file(path: Path, validate: bool) -> dict:
    """Run one flyer through the pipeline and return a summary row.

    Never raises: a file the pipeline cannot handle is exactly what the eval is
    meant to surface, so the failure is recorded as the row's ``error`` rather
    than thrown.
    """
    row: dict = {
        "file": path.name,
        "path": "",
        "elements": 0,
        "unclassified": 0,
        "fidelity": None,
        "error": "",
    }
    try:
        data = path.read_bytes()
        page = rasterise(data, path.name)
        result = extract_page(data, page)
        elements = normalise_elements(result.payload, page)
        bake_assets(elements, page)
    except (TemplateImportError, Exception) as exc:  # noqa: BLE001 - reported, not raised
        row["error"] = f"{type(exc).__name__}: {exc}"
        return row

    row["path"] = "structural" if result.model == "pdf-structure" else result.model
    row["elements"] = len(elements)
    row["unclassified"] = sum(
        1
        for element in elements
        if str((element.style_properties or {}).get("fill_type", "")) in _WARNING_TEXT
    )

    if validate:
        from apps.templates.extraction_validation import validate_extraction

        background = (result.payload.get("page", {}) or {}).get("background_color") or "#FFFFFF"
        outcome = validate_extraction(elements, page, background)
        row["fidelity"] = outcome.score if outcome.ok else None
    return row


def compare_to_baseline(rows: list[dict], baseline: list[dict]) -> list[str]:
    """Regressions of ``rows`` against a previous run. Pure; unit-tested.

    Two kinds are reported: an element count that changed (the extractor now
    sees a different number of things on a page it saw before), and a fidelity
    score that dropped past the threshold. A file that is new, or that has no
    baseline, is not a regression — there is nothing to regress from.
    """
    by_name = {row["file"]: row for row in baseline}
    regressions: list[str] = []
    for row in rows:
        prior = by_name.get(row["file"])
        if prior is None:
            continue
        if row.get("error") and not prior.get("error"):
            regressions.append(f"{row['file']}: now errors ({row['error']})")
            continue
        if row["elements"] != prior.get("elements"):
            regressions.append(
                f"{row['file']}: element count {prior.get('elements')} -> {row['elements']}"
            )
        now, then = row.get("fidelity"), prior.get("fidelity")
        if isinstance(now, (int, float)) and isinstance(then, (int, float)):
            if then - now > _FIDELITY_REGRESSION:
                regressions.append(
                    f"{row['file']}: fidelity {then:.3f} -> {now:.3f}"
                )
    return regressions


def format_table(rows: list[dict]) -> str:
    """A fixed-width table of the rows for the console. Pure; unit-tested."""
    header = f"{'file':32} {'path':14} {'elems':>5} {'unclf':>5} {'fidelity':>8}"
    lines = [header, "-" * len(header)]
    for row in rows:
        fidelity = row.get("fidelity")
        fidelity_text = f"{fidelity:.3f}" if isinstance(fidelity, (int, float)) else "-"
        note = f"  ERROR {row['error']}" if row.get("error") else ""
        lines.append(
            f"{row['file'][:32]:32} {str(row['path'])[:14]:14} "
            f"{row['elements']:>5} {row['unclassified']:>5} {fidelity_text:>8}{note}"
        )
    return "\n".join(lines)


class Command(BaseCommand):
    help = "Score the extraction pipeline over a folder of golden-set flyers."

    def add_arguments(self, parser):
        default_dir = Path(settings.BASE_DIR) / "eval" / "golden"
        parser.add_argument(
            "--dir", default=str(default_dir),
            help="Folder of flyer files to evaluate (default: backend/eval/golden).",
        )
        parser.add_argument(
            "--validate", action="store_true",
            help="Also render each result and score it against the source (needs the renderer).",
        )
        parser.add_argument(
            "--baseline", default="",
            help="A prior report JSON to diff against for regressions.",
        )
        parser.add_argument(
            "--out", default="",
            help="Where to write the report JSON (default: <dir>/../reports/latest.json).",
        )
        parser.add_argument(
            "--fail-on-regression", action="store_true",
            help="Exit non-zero if any file regressed against the baseline (for CI).",
        )

    def handle(self, *args, **options):
        source_dir = Path(options["dir"])
        if not source_dir.is_dir():
            raise CommandError(
                f"No golden-set folder at {source_dir}. Create it and add flyer "
                f"files (PDF/PNG/JPG/WebP), or pass --dir."
            )

        files = sorted(
            p for p in source_dir.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        )
        if not files:
            raise CommandError(f"No supported files in {source_dir}.")

        self.stdout.write(f"Evaluating {len(files)} file(s) from {source_dir}...")
        rows = [evaluate_file(path, options["validate"]) for path in files]

        self.stdout.write("")
        self.stdout.write(format_table(rows))
        self.stdout.write("")

        errored = [r for r in rows if r["error"]]
        scored = [r["fidelity"] for r in rows if isinstance(r["fidelity"], (int, float))]
        if scored:
            self.stdout.write(f"Mean fidelity: {sum(scored) / len(scored):.3f} over {len(scored)} file(s)")
        if errored:
            self.stdout.write(self.style.WARNING(f"{len(errored)} file(s) errored"))

        out_path = Path(options["out"]) if options["out"] else source_dir.parent / "reports" / "latest.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(f"Report written to {out_path}")

        if options["baseline"]:
            baseline_path = Path(options["baseline"])
            if not baseline_path.is_file():
                raise CommandError(f"Baseline not found: {baseline_path}")
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            regressions = compare_to_baseline(rows, baseline)
            if regressions:
                self.stdout.write(self.style.ERROR("\nRegressions vs baseline:"))
                for line in regressions:
                    self.stdout.write(self.style.ERROR(f"  - {line}"))
                if options["fail_on_regression"]:
                    raise CommandError(f"{len(regressions)} regression(s) against baseline.")
            else:
                self.stdout.write(self.style.SUCCESS("\nNo regressions against baseline."))
