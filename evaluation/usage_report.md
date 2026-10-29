# Usage Report — Ghost Data Still Exists

## Final Full-Dataset Run Summary

Command: `python code/main.py --no-llm run`

| Field | Value |
|---|---|
| Run date | 2026-10-25 |
| Mode | `--no-llm` (fully deterministic, offline) |
| Total cases | 518 |
| Output file | `output.csv` (repo root) |

---

## Model Providers and Models

| Provider | Model | Role |
|---|---|---|
| None | None | LLM disabled (`--no-llm` flag) |

No external model calls were made in the final production run. All classification, parsing, and decision logic runs deterministically from rules and evidence.

---

## Call Counts

| Call type | Count |
|---|---|
| Live LLM calls | 0 |
| Cache-replayed calls | 0 |
| Total LLM calls | 0 |

---

## Token Usage

| Metric | Input tokens | Output tokens | Total tokens |
|---|---|---|---|
| Per request (avg) | 0 | 0 | 0 |
| Total (518 requests) | 0 | 0 | 0 |

---

## Cost Estimate

| Provider | Model | Input cost | Output cost | Total |
|---|---|---|---|---|
| None | None (--no-llm) | \$0.00 | \$0.00 | \$0.00 |
| **Overall total** | | | | **\$0.00** |

---

## Runtime

| Phase | Duration |
|---|---|
| Evidence ledger build (cold, first run) | ~185 seconds |
| Evidence ledger build (warm cache) | ~12 seconds |
| Case processing (518 cases) | ~15 seconds |
| Validation | ~2 seconds |
| **Total (cold)** | **~202 seconds (~3.4 min)** |
| **Total (warm)** | **~29 seconds** |

---

## Notes

- The solution uses a file-based cache (`.cache/` directory) to avoid re-parsing evidence on repeated runs. The cache is created automatically on first run and reused thereafter.
- Image evidence (47 PNG files) is skipped in `--no-llm` mode. Enabling the LLM vision API would extract additional structured data from screenshots, potentially improving step recall for image-heavy cases.
- All 518 cases produce a valid output row with no crashes, including cases with missing evidence or ambiguous identity.
