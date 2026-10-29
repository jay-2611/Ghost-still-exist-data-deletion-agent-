from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from policy import Decision  # noqa: E402
from steps import build  # noqa: E402
from validate import validate_output  # noqa: E402


def test_build_handles_intent_deduplication_and_numeric_sort_hypothesis():
    decision_10 = Decision(
        "search_service", "search_10", "SEARCH_INDEX_ENTRY",
        "REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT",
        "ABSENT", "evidence_10",
    )
    decision_2 = Decision(
        "search_service", "search_2", "SEARCH_INDEX_ENTRY",
        "REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT",
        "ABSENT", "evidence_2",
    )

    assert build(False, [decision_10]) == []
    lexical = build(True, [decision_2, decision_10, decision_10], resource_sort="lexical")
    natural = build(True, [decision_2, decision_10], resource_sort="natural")

    assert len(lexical) == 6
    assert [step.step_no for step in lexical] == list(range(1, 7))
    assert [step.resource_id for step in lexical if step.phase == "FINDING"] == ["search_10", "search_2"]
    assert [step.resource_id for step in natural if step.phase == "FINDING"] == ["search_2", "search_10"]
    assert all(step.evidence_id == "" for step in lexical if step.phase != "FINDING")


def test_sample_output_passes_validator():
    assert validate_output(ROOT / "dataset" / "sample_output.csv") == []

