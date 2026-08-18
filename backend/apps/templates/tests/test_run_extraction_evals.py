"""The extraction-eval runner's aggregation logic.

Only the pure pieces are tested here — the per-file pipeline run needs the
vision model or the renderer, which the eval command exists to exercise, not
these tests. The regression diff and the console table are what carry the
logic, so they are what get pinned down.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.templates.management.commands.run_extraction_evals import (
    compare_to_baseline,
    format_table,
)


def _row(file, elements=10, unclassified=0, fidelity=None, error="", path="structural"):
    return {
        "file": file,
        "path": path,
        "elements": elements,
        "unclassified": unclassified,
        "fidelity": fidelity,
        "error": error,
    }


class CompareToBaselineTestCase(SimpleTestCase):
    def test_a_dropped_fidelity_is_a_regression(self):
        base = [_row("a.pdf", fidelity=0.95)]
        now = [_row("a.pdf", fidelity=0.80)]
        self.assertEqual(len(compare_to_baseline(now, base)), 1)

    def test_a_tiny_fidelity_wobble_is_not_a_regression(self):
        base = [_row("a.pdf", fidelity=0.95)]
        now = [_row("a.pdf", fidelity=0.94)]  # within the noise threshold
        self.assertEqual(compare_to_baseline(now, base), [])

    def test_a_changed_element_count_is_a_regression(self):
        base = [_row("a.pdf", elements=12)]
        now = [_row("a.pdf", elements=9)]
        self.assertEqual(len(compare_to_baseline(now, base)), 1)

    def test_a_newly_failing_file_is_a_regression(self):
        base = [_row("a.pdf")]
        now = [_row("a.pdf", error="ValueError: boom")]
        self.assertEqual(len(compare_to_baseline(now, base)), 1)

    def test_a_new_file_with_no_baseline_is_not_a_regression(self):
        self.assertEqual(compare_to_baseline([_row("new.pdf")], []), [])


class FormatTableTestCase(SimpleTestCase):
    def test_it_renders_a_score_and_flags_an_error(self):
        text = format_table([_row("ok.pdf", fidelity=0.9), _row("bad.png", error="X")])
        self.assertIn("ok.pdf", text)
        self.assertIn("0.900", text)
        self.assertIn("ERROR X", text)
