from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from evaluate import (_apply_intent_mode, load_custom_cases, score_predictions,
                      supplemental_views)  # noqa: E402


def test_perfect_sample_row_scores_all_five_metrics_as_one():
    step = {
        "step_no": 1, "phase": "VERIFICATION", "system_id": "account_service",
        "resource_id": "account_1", "operation": "VERIFY_RECORD_ABSENT",
        "state": "ABSENT", "evidence_id": "evidence_1",
    }
    gold = pd.DataFrame([{
        "case_id": "case_1", "deletion_status": "COMPLETE",
        "steps_json": json.dumps([step]),
    }])
    prediction = {"case_1": {"deletion_status": "COMPLETE", "steps": [step]}}

    metrics = score_predictions(prediction, gold)

    assert metrics["status_accuracy"] == 1.0
    assert metrics["row_exact_accuracy"] == 1.0
    assert metrics["step_level_accuracy"] == 1.0
    assert metrics["field_level_accuracy"] == 1.0
    assert metrics["sequence_accuracy"] == 1.0


def test_mismatch_is_reported_by_evidence_cause():
    gold_step = {
        "step_no": 1, "phase": "VERIFICATION", "system_id": "account_service",
        "resource_id": "account_1", "operation": "VERIFY_RECORD_ABSENT",
        "state": "ABSENT", "evidence_id": "evidence_1",
    }
    predicted_step = {**gold_step, "evidence_id": "evidence_2"}
    gold = pd.DataFrame([{
        "case_id": "case_1", "deletion_status": "COMPLETE",
        "steps_json": json.dumps([gold_step]),
    }])

    metrics = score_predictions(
        {"case_1": {"deletion_status": "COMPLETE", "steps": [predicted_step]}}, gold)

    assert metrics["failure_cause_counts"]["wrong evidence_id"] == 1
    assert metrics["step_level_accuracy"] == 0.0
    assert metrics["sequence_accuracy"] == 0.0


def test_custom_case_loader_reads_existing_json_corpus():
    cases = load_custom_cases(ROOT / "code" / "evaluation" / "custom_cases")
    assert len(cases) == 20
    assert all(case.get("request_text") and case.get("expected") for case in cases)


def test_assume_deletion_mode_preserves_events_and_hard_negations():
    forced, forced_flag = _apply_intent_mode((False, "LLM", "uncertain"), "assume-deletion")
    event, event_flag = _apply_intent_mode((False, "EVENT", "linked event"), "assume-deletion")
    negation, negation_flag = _apply_intent_mode(
        (False, "NEGATION", "Non-deletion or limiting phrase (English explicit negation: do not delete)."),
        "assume-deletion",
    )

    assert forced[0] is True and forced_flag is True
    assert event[0] is False and event_flag is False
    assert negation[0] is False and negation_flag is False


def test_assume_deletion_mode_does_not_preserve_soft_limits():
    result, forced = _apply_intent_mode(
        (False, "NEGATION", "Non-deletion or limiting phrase (English retain or limit: only)."),
        "assume-deletion",
    )

    assert result[0] is True and forced is True


def test_supplemental_views_separate_evidence_and_linked_resources():
    step = {
        "step_no": 1, "phase": "VERIFICATION", "system_id": "account_service",
        "resource_id": "account_1", "operation": "VERIFY_RECORD_ABSENT",
        "state": "ABSENT", "evidence_id": "evidence_gold",
    }
    gold = pd.DataFrame([{
        "case_id": "case_1", "deletion_status": "COMPLETE",
        "steps_json": json.dumps([step]),
    }])
    prediction_step = {**step, "evidence_id": "evidence_other"}
    predictions = {"case_1": {"deletion_status": "COMPLETE", "steps": [prediction_step]}}
    metrics = score_predictions(predictions, gold)

    views = supplemental_views(metrics, predictions, gold, {
        "case_1": {"linked_pairs": {("account_service", "account_1")}},
    })

    assert metrics["step_level_accuracy"] == 0.0
    assert views["ignore_evidence"]["step_set_accuracy"] == 1.0
    assert views["ignore_evidence"]["sequence_accuracy"] == 1.0
    assert views["linked_only"]["step_set_accuracy"] == 0.0
    assert views["linked_only"]["exact_total"] == 1
    assert views["shared_resource_field_accuracy"]["evidence_id"]["accuracy"] == 0.0

