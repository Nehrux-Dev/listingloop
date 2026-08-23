# Extraction golden set

Real flyer files the extraction pipeline is scored against, by
`python manage.py run_extraction_evals`.

## What to put here

Drop representative uploads straight into this folder — `.pdf`, `.png`, `.jpg`,
`.webp`. Aim for **20–50 files**, split roughly:

- **40–60% core cases** — ordinary flyers you expect to work well (a clean
  Canva export PDF, a standard listing image).
- **15–25% edge cases** — the hard ones: a scan, a photo-of-a-flyer, angled
  photo cuts, dotted grounds, a design with a big price, multi-column features.
- **Every past failure** — when a real import comes back wrong (e.g. the clipped
  `$1,300,00` price), add that exact file here so the bug can never silently
  return.

## Notes

- Text PDFs score offline and for free (structural path). Images call the vision
  model, so scoring those needs `OPENAI_*` configured.
- `--validate` additionally renders each result and scores fidelity; that needs
  the renderer service running.
- Generated reports go to `../reports/` and are git-ignored. To lock in a
  baseline for regression checks, copy a good report to
  `../reports/baseline.json` and commit it.
- Be mindful of licensing before committing third-party artwork; use files you
  own or have the right to store.
