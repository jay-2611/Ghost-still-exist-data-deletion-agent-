"""Sample-citation coverage gate for the non-SQL evidence parsers."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from loader import DATASET_DIR, load_all  # noqa: E402
from parsers import ABSENT, UNKNOWN, parse_file  # noqa: E402


def test_json_txt_log_parsers_and_combined_citation_recall():
    ds = load_all(DATASET_DIR)
    files_by_id = {str(row.file_id): row for row in ds.evidence_files.itertuples(index=False)}
    file_types = {file_id: Path(row.file_path).suffix.lower().lstrip(".")
                  for file_id, row in files_by_id.items()}
    parsed = {}
    scopes = {}
    counts = Counter()
    for _, row in ds.evidence_files.iterrows():
        file_type = Path(row.file_path).suffix.lower().lstrip(".")
        if file_type not in {"sql", "json", "txt", "log"}:
            continue
        facts, scope = parse_file(row, DATASET_DIR)
        parsed[str(row["file_id"])] = facts
        scopes[str(row["file_id"])] = scope
        counts[file_type] += 1

    assert counts == Counter({"sql": 24, "json": 28, "log": 26, "txt": 1})

    requests = ds.sample_deletion_requests.set_index("case_id")
    expected_by_case = defaultdict(set)
    citations = {}
    for sample in ds.sample_output.itertuples(index=False):
        for step in json.loads(sample.steps_json):
            rid, system = step.get("resource_id"), step.get("system_id")
            if not rid or not system:
                continue
            triple = (str(sample.case_id), str(system), str(rid))
            expected_by_case[sample.case_id].add(triple)
            phase = "VERIFICATION" if sample.deletion_status == "COMPLETE" else "FINDING"
            evidence_id = str(step.get("evidence_id") or "").strip()
            if step.get("phase") == phase and evidence_id:
                citations[triple] = (evidence_id, str(step.get("state") or ""))

    expected_citations = {triple: value for triple, value in citations.items()
                          if file_types.get(value[0]) in {"sql", "json", "txt", "log"}}
    hits = Counter()
    totals = Counter()
    category_totals = Counter()
    category_hits = Counter()
    category_misses = defaultdict(list)
    for (case_id, system_id, resource_id), (evidence_id, expected_state) in expected_citations.items():
        file_type = file_types[evidence_id]
        totals[file_type] += 1
        facts = parsed.get(evidence_id, [])
        matching = [fact for fact in facts
                    if fact.system_id == system_id and fact.resource_id == resource_id]
        # A complete scoped snapshot is evidence for a requested ABSENT result
        # even though no row, and therefore no Fact, should be emitted.
        scope_absence = (expected_state == "ABSENT" and system_id in scopes.get(evidence_id, {}))
        category = matching[0].category if matching else next(
            (fact.category for fact in facts if fact.resource_id == resource_id), "UNKNOWN")
        category_totals[(file_type, category)] += 1
        if matching or scope_absence:
            hits[file_type] += 1
            category_hits[(file_type, category)] += 1
        else:
            category_misses[(file_type, category)].append(
                (case_id, system_id, resource_id, evidence_id, expected_state))

    combined_total = sum(totals.values())
    combined_hits = sum(hits.values())
    print("Parsed evidence files:", dict(counts))
    print("Citation recall by evidence type (resource Facts plus scoped ABSENT proof):")
    for file_type in ("sql", "json", "txt", "log"):
        print(f"  {file_type}: {hits[file_type]}/{totals[file_type]} "
              f"({hits[file_type] / totals[file_type]:.1%})")
    print(f"  combined: {combined_hits}/{combined_total} ({combined_hits / combined_total:.1%})")
    print("Per-category misses:")
    for key in sorted(category_totals):
        missed = category_misses[key]
        print(f"  {key[0]}/{key[1]}: {len(missed)}/{category_totals[key]} missed; {missed}")

    assert totals == Counter({"sql": 10, "json": 42, "txt": 7, "log": 15})
    assert combined_total == 74
    assert combined_hits / combined_total >= 0.90
    assert sum(len(items) for items in category_misses.values()) == combined_total - combined_hits


def test_lookup_start_is_context_not_a_present_record():
    ds = load_all(DATASET_DIR)
    row = ds.evidence_by_id("evidence_67").iloc[0]
    facts, _ = parse_file(row, DATASET_DIR)
    matched = [fact for fact in facts if fact.resource_id == "account_6523"]
    states = {json.loads(fact.raw_ref)["event"]: fact.state for fact in matched}

    assert states["profile_lookup_started"] == UNKNOWN
    assert states["profile_lookup_completed"] == ABSENT
