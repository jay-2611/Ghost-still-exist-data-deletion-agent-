# Ghost Data Still Exists — Deletion-Audit Agent

## Problem Summary

This agent audits deletion requests for a commerce platform. For each request in `dataset/deletion_requests.csv` the agent:

1. Determines whether the `request_text` actually authorises deletion (any other intent → `NOT_APPLICABLE`).
2. Resolves **current** and **historical** identifiers for the subject (email, user_id, phone, email-hash) using `user_identities.csv` + `user_audit_log.csv`.
3. Reconstructs the state of every relevant resource **as of `audit_at`** from the provided evidence files.
4. Applies the policy rules from `dataset/deletion_rules.csv` — delete, redact, anonymise, retain, or preserve a tombstone.
5. Emits a concise, verifiable remediation plan when data is not fully deleted.

Final output is `output.csv` at the repo root:

```
case_id,deletion_status,steps_json
```

where `steps_json` is an ordered JSON array of step objects with `(step_no, phase, system_id, resource_id, operation, state, evidence_id)`.

---

## Architecture

```
Request CSV
    │
    ▼
Intent Classifier (code/intent.py)
    │  TEMPLATE / NEGATION / RULE_AFFIRM / LLM
    ▼
Identity Resolver (code/identity.py)
    │  user_identities.csv + user_audit_log.csv
    ▼
Evidence Ledger (code/ledger.py)
    │  Parsers: SQL, JSON, log, text, PDF, PNG
    ▼
State Builder (code/state.py)
    │  Latest fact ≤ audit_at per (system_id, resource_id)
    ▼
Policy Engine (code/policy.py)
    │  deletion_rules.csv → required treatment per category
    ▼
Steps Generator (code/steps.py)
    │  FINDING → REMEDIATION → VERIFICATION
    ▼
output.csv (repo root)
    │
    ▼
Validator (code/validate.py)
    Check 518 rows, schema, allowed ops/states, evidence IDs
```

### Component descriptions

| Component | File | Purpose |
|---|---|---|
| Parsers | `code/parsers/*.py` | Ingest CSV, JSON, log, SQL, PNG, PDF evidence files |
| Ledger | `code/ledger.py` | Unified fact store keyed by `(system_id, resource_id, timestamp)` |
| Identity resolver | `code/identity.py` | Maps historical identifiers to stable `user_id` via audit log |
| State builder | `code/state.py` | Selects the latest fact ≤ `audit_at` for each resource |
| Intent classifier | `code/intent.py` | Determines whether request authorises deletion |
| Policy engine | `code/policy.py` | Reads `deletion_rules.csv` and decides required treatment per category |
| Steps generator | `code/steps.py` | Builds ordered FINDING → REMEDIATION → VERIFICATION steps |
| Evaluator | `code/evaluate.py` | Compares output vs 32 labelled samples for accuracy metrics |
| Validator | `code/validate.py` | Validates output.csv schema and contract compliance |
| Usage tracker | `code/usage.py` | LLM client wrapper with token tracking and caching |

---

## Environment Variables

Create a `.env` file in the repo root (not committed):

```dotenv
# LLM API key — only needed if running WITH LLM (--no-llm skips this)
LLM_API_KEY=your_key_here
GEMINI_API_KEY=your_key_here
```

A `.env.example` file is provided as a template. The solution runs fully offline with `--no-llm` (zero API calls, zero cost).

---

## Setup and Execution

### Requirements

- Python 3.10 or later (tested on 3.14.4)
- pip packages in `requirements.txt`

### Install

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip3 install -r requirements.txt
```

### Run commands

```bash
# (Optional) Verify LLM connectivity
python code/main.py llmcheck

# Pre-build the evidence ledger cache (speeds up subsequent runs)
python code/main.py prefetch

# Evaluate against the 32 public labelled samples
python code/main.py --no-llm eval

# Full 518-case run → produces output.csv at repo root
python code/main.py --no-llm run

# Validate output.csv format
python code/main.py check
```

All runs are **deterministic** when `--no-llm` is supplied — no external API calls, zero token cost, byte-identical output across repeated runs.

To enable full LLM-powered evidence extraction (vision for PNGs, classification for ambiguous intents):

```bash
python code/main.py run
```

This requires valid `LLM_API_KEY` / `GEMINI_API_KEY` in `.env`.

### Expected runtimes

| Mode | Cold start | Warm cache |
|---|---|---|
| `--no-llm` | ~3 min | ~30 sec |
| With LLM | ~15-30 min | ~8 min |

---

## Repository Layout

```
hackerrank-orchestrate-october26/
├── code/                         # Source code (include in code.zip)
│   ├── main.py                   # Entry point
│   ├── evaluate.py               # Sample evaluation
│   ├── identity.py               # Identity resolution
│   ├── intent.py                 # Intent classification
│   ├── ledger.py                 # Evidence ledger
│   ├── loader.py                 # Dataset loading utilities
│   ├── policy.py                 # Deletion policy engine
│   ├── state.py                  # Resource state resolution
│   ├── steps.py                  # Step generation
│   ├── usage.py                  # LLM client + token tracking
│   ├── validate.py               # Output validation
│   ├── parsers/                  # Evidence parsers
│   │   ├── __init__.py
│   │   ├── csv.py
│   │   ├── image.py              # PNG (requires LLM)
│   │   ├── json.py
│   │   ├── log.py
│   │   ├── pdf.py
│   │   ├── sql.py
│   │   └── text.py
│   └── evaluation/               # Evaluation artefacts
│       ├── evaluation_report.md
│       └── usage_report.md
├── evaluation/                   # Top-level evaluation reports (also in code/)
│   ├── evaluation_report.md
│   └── usage_report.md
├── dataset/                      # Participant-facing data (DO NOT include in zip)
├── output.csv                    # Final predictions (submit separately)
├── .env.example                  # Placeholder env variables
├── requirements.txt              # Python dependencies
├── README.md                     # This file
└── log.txt                       # Agent session log (append-only)
```

---

## Known Limitations

- **Unlinked account IDs**: ~14 cases have resources with account-level IDs that cannot be matched to any user identifier in the ledger. Steps for these resources are omitted.
- **Image evidence without LLM**: 47 PNG evidence files are skipped in `--no-llm` mode. Enabling the LLM vision API improves recall for image-heavy cases.
- **Ambiguous intent phrasing**: Multi-language or indirect requests may be flagged `NEEDS_REVIEW` (6 cases). In `--no-llm` mode these default to TEMPLATE matching.
- **Replica detection**: Snapshot timestamps are compared across SQL files to detect replication drift, but multi-region consistency guarantees are not modelled.
- **Policy hypotheses**: Some "must retain" claims (e.g., audit logs within retention period) cannot be fully proved from the public evidence set; the agent assumes worst-case (retain) for safety.

---

## Submission

**Challenge page**: https://wwww.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists

The submission ZIP (`code.zip`) must contain:
- `code/` directory (all Python source files)
- `README.md`
- `requirements.txt`
- `.env.example`
- `evaluation/evaluation_report.md`
- `evaluation/usage_report.md`

Do **not** include: `dataset/`, `.cache/`, `.venv/`, `output.csv`, `.env`, `log.txt`, or nested archives.
