from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from intent import classify, classify_many  # noqa: E402
from ledger import Ledger  # noqa: E402
from loader import DATASET_DIR, load_all  # noqa: E402
from usage import LLMClient  # noqa: E402


class MockBatchLLM:
    def __init__(self, decision: bool = True, *, fail: bool = False):
        self.decision = decision
        self.fail = fail
        self.calls = []

    def generate_json(self, prompt, schema, file=None):
        self.calls.append((prompt, schema, file))
        if self.fail:
            raise ConnectionError("network unavailable")
        ids = schema["properties"]["items"]["items"]["properties"]["id"]["enum"]
        return {"items": [{"id": item_id, "deletion_requested": self.decision,
                            "reason": "mocked deterministic test response"} for item_id in ids]}


def _custom_cases():
    path = ROOT / "code" / "evaluation" / "custom_cases" / "intent_cases.json"
    return json.loads(path.read_text(encoding="utf-8-sig"))


def test_custom_explicit_non_deletion_and_negation_corpus():
    ds = load_all(DATASET_DIR)
    cases = _custom_cases()
    rows = [{"case_id": item["id"], "email": "", "audit_at": None,
             "request_text": item["request_text"]} for item in cases]
    results = classify_many(rows, ds, None)
    for item, result in zip(cases, results):
        if item["expected"] == "NOT_APPLICABLE":
            assert result[0] is False, item["id"]
        else:
            assert result[0] is True, item["id"]
    assert all(result[1] != "LLM" for result in results)


def test_ambiguous_text_fails_closed_with_review_flag():
    ds = load_all(DATASET_DIR)
    case = {"case_id": "custom", "email": "", "audit_at": None,
            "request_text": "Please assess the account situation."}
    decision, source, reason = classify(case, ds, None)
    assert (decision, source) == (False, "LLM")
    assert "NEEDS_REVIEW" in reason


def test_ambiguous_requests_are_sent_in_batches_of_at_most_40_unique_texts():
    ds = load_all(DATASET_DIR)
    rows = [{"case_id": str(index), "email": "", "audit_at": None,
             "request_text": f"Please assess request number {index} and advise."}
            for index in range(85)]
    rows += [dict(rows[0])]  # repeated text is sent once, then reused
    llm = MockBatchLLM()
    results = classify_many(rows, ds, llm)
    assert len(results) == len(rows)
    assert len(llm.calls) == 3
    assert all(result[0] for result in results)
    for _, schema, _ in llm.calls:
        assert len(schema["properties"]["items"]["items"]["properties"]["id"]["enum"]) <= 40


def test_dataset_gate_all_requests_samples_and_event_order():
    ds = load_all(DATASET_DIR)
    ds.ledger = Ledger.build(ds, DATASET_DIR, llm=LLMClient(no_llm=True))
    requests = list(ds.deletion_requests.itertuples(index=False))
    llm = MockBatchLLM(True)
    results = classify_many(requests, ds, llm)
    assert len(results) == 518
    counts = Counter(source for _, source, _ in results)
    assert counts["EVENT"] == 1
    assert counts["NEGATION"] == 9
    assert counts["TEMPLATE"] + counts["LLM"] == 508
    assert sum(not decision for decision, _, _ in results) == 10
    assert sum(decision for decision, _, _ in results) == 508
    assert 1 <= len(llm.calls) <= 3
    assert all(decision for decision, source, _reason in results if source == "TEMPLATE")

    samples = list(ds.sample_deletion_requests.itertuples(index=False))
    sample_results = classify_many(samples, ds, MockBatchLLM(True))
    assert len(sample_results) == 32
    assert all(decision for decision, _, _ in sample_results)
    assert sum(source == "LLM" for _, source, _ in sample_results) <= 32

    linked = [(row.case_id, result) for row, result in zip(requests, results) if result[1] == "EVENT"]
    assert len(linked) == 1
    assert linked[0][1][0] is False
