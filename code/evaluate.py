"""Evaluate deletion-audit predictions against the labeled sample cases."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

CODE_DIR = Path(__file__).resolve().parent
ROOT = CODE_DIR.parent
DEFAULT_CUSTOM_CASES = CODE_DIR / "evaluation" / "custom_cases"
DEFAULT_REPORT = CODE_DIR / "evaluation" / "evaluation_report.md"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from identity import resolve  # noqa: E402
from intent import classify_many  # noqa: E402
from ledger import Ledger  # noqa: E402
from loader import DATASET_DIR, load_all  # noqa: E402
from policy import decide  # noqa: E402
from state import link_identity_resources, resolve_states  # noqa: E402
from steps import Step, build, infer_status  # noqa: E402
from usage import LLMClient  # noqa: E402

STEP_FIELDS = ("phase", "system_id", "resource_id", "operation", "state", "evidence_id")
ROW_FIELDS = ("step_no", *STEP_FIELDS)
FAILURE_CAUSES = ("identity", "missing finding", "extra finding", "wrong evidence_id",
                  "wrong operation", "ordering", "scope")


def _steps(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, Step):
            result.append({name: getattr(item, name) for name in ROW_FIELDS})
        elif isinstance(item, dict):
            result.append(dict(item))
        else:
            result.append({"_invalid_step": repr(item)})
    return result


def _sig(step: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(step.get(field) for field in STEP_FIELDS)


def _rowsig(steps: list[dict[str, Any]]) -> tuple[Any, ...]:
    return tuple((tuple(step.get(field) for field in ROW_FIELDS),
                  tuple(sorted((str(k), repr(v)) for k, v in step.items() if k not in ROW_FIELDS)))
                 for step in steps)


def _fmt_sig(sig: tuple[Any, ...]) -> str:
    return " / ".join("" if value is None else str(value) for value in sig)


def load_predictions(path: str | Path) -> dict[str, dict[str, Any]]:
    """Read prediction CSV rows keyed by case_id."""
    result = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"case_id", "deletion_status", "steps_json"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError(f"Prediction CSV must contain {sorted(required)}")
        for row in reader:
            case = str(row.get("case_id") or "").strip()
            if case:
                result[case] = {"deletion_status": str(row.get("deletion_status") or "").strip(),
                                "steps": _steps(row.get("steps_json", ""))}
    return result


def load_custom_cases(directory: str | Path = DEFAULT_CUSTOM_CASES) -> list[dict[str, Any]]:
    """Load JSON and CSV custom evaluation cases recursively."""
    root = Path(directory)
    if not root.exists():
        return []
    cases = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".json", ".csv"}:
            continue
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                payload = payload.get("cases", payload.get("items", [payload]))
            if not isinstance(payload, list):
                raise ValueError(f"Custom JSON must contain a list of cases: {path}")
            rows = payload
        else:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
        for index, row in enumerate(rows, 1):
            if isinstance(row, dict):
                case = dict(row)
                case.setdefault("id", case.get("case_id") or f"{path.stem}_{index:03d}")
                case["_source_file"] = str(path.relative_to(root))
                cases.append(case)
    return cases


def _custom_results(cases: list[dict[str, Any]], ds: Any, llm: Any) -> list[dict[str, Any]]:
    relevant = [case for case in cases if str(case.get("request_text", "")).strip()]
    rows = [{"case_id": str(case.get("id", "")), "email": str(case.get("email", "") or ""),
             "audit_at": case.get("audit_at"), "request_text": str(case.get("request_text", ""))}
            for case in relevant]
    outcomes = classify_many(rows, ds, llm) if rows else []
    result = []
    for case, (deletion, source, reason) in zip(relevant, outcomes):
        expected = str(case.get("expected", case.get("expected_status", ""))).strip().upper()
        if expected in {"NOT_APPLICABLE", "NON_DELETION"}:
            correct = not deletion
        elif expected in {"DELETION", "DELETION_REQUESTED", "COMPLETE_OR_INCOMPLETE_DELETION"}:
            correct = deletion
        else:
            correct = None
        result.append({"id": str(case.get("id", "")), "expected": expected,
                       "predicted": "DELETION_REQUESTED" if deletion else "NOT_APPLICABLE",
                       "source": source, "reason": reason, "correct": correct,
                       "request_text": str(case.get("request_text", ""))})
    return result


def _sample_predictions(ds: Any, dataset_dir: str | Path, llm: Any,
                       account_guess: bool = False, intent_mode: str = "classified"
                       ) -> tuple[dict[str, dict[str, Any]], dict[str, Any], Counter[str], int]:
    if intent_mode not in {"classified", "assume-deletion"}:
        raise ValueError("intent_mode must be 'classified' or 'assume-deletion'")
    ledger = Ledger.build(ds, dataset_dir, llm=llm)
    requests = list(ds.sample_deletion_requests.itertuples(index=False))
    intents = classify_many(requests, ds, llm)
    all_facts = {(f.system_id, f.resource_id.casefold()) for f in ledger.facts}
    activity = getattr(ds, "system_activity", pd.DataFrame())
    all_activity = set()
    if {"target_system", "resource_id"}.issubset(activity.columns):
        all_activity = {(str(row.target_system), str(row.resource_id).strip().casefold())
                        for row in activity.itertuples(index=False) if str(row.resource_id).strip()}
    predictions, contexts = {}, {}
    forced_count = 0
    policy_case_count = 0
    facts_by_pair = _facts_by_pair(ledger, pd.Timestamp.max.tz_localize("UTC"))
    resource_systems: dict[str, set[str]] = defaultdict(set)
    for system, rid in all_facts:
        resource_systems[rid].add(system)
    for request, intent in zip(requests, intents):
        case_id = str(request.case_id)
        identity = resolve(request.email, ds, request.audit_at)
        intent, forced = _apply_intent_mode(intent, intent_mode)
        if forced:
            forced_count += 1
        if intent[0]:
            policy_case_count += 1
        cutoff = pd.to_datetime(request.audit_at, errors="coerce", utc=True)
        matched_facts = [f for f in ledger.query(identity)
                         if pd.to_datetime(f.observed_at, errors="coerce", utc=True) <= cutoff]
        matched = {(f.system_id, f.resource_id.casefold()) for f in matched_facts}
        future = {(f.system_id, f.resource_id.casefold()) for f in ledger.facts
                  if pd.to_datetime(f.observed_at, errors="coerce", utc=True) > cutoff}
        states = resolve_states(identity, ledger, ds, request.audit_at, account_guess=account_guess)
        state_pairs = {(s.system_id, s.resource_id.casefold()) for s in states}
        state_by_pair = {(s.system_id, s.resource_id.casefold()): s for s in states}
        # A resource qualifies for linked-only scoring only when a parsed Fact
        # carries this identity or an explicit/evidence-adjacent identity link
        # ties it to the user. BOUND_BY_TIME alone does not qualify.
        linked_pairs = set(matched)
        for rid in identity.linked_resources:
            lower_rid = str(rid).strip().casefold()
            for system in resource_systems.get(lower_rid, set()):
                linked_pairs.add((system, lower_rid))
            prefixes = getattr(ds, "PREFIX_TO_SYSTEM", {}) or {}
            matches = [prefix for prefix in prefixes if lower_rid.startswith(prefix.lower())]
            if matches:
                linked_pairs.add((prefixes[max(matches, key=len)], lower_rid))
        for rid, link in link_identity_resources(identity, ledger, ds, request.audit_at).items():
            system = link.get("system_id")
            if system:
                linked_pairs.add((system, rid.casefold()))
            else:
                prefixes = getattr(ds, "PREFIX_TO_SYSTEM", {}) or {}
                matches = [prefix for prefix in prefixes if rid.casefold().startswith(prefix.lower())]
                if matches:
                    linked_pairs.add((prefixes[max(matches, key=len)], rid.casefold()))
        decisions = [d for state in states if (d := decide(state, request.audit_at)) is not None]
        steps = build(intent, decisions)
        predictions[case_id] = {
            "deletion_status": infer_status(intent, decisions),
            "steps": [{name: getattr(step, name) for name in ROW_FIELDS} for step in steps],
        }
        contexts[case_id] = {"matched_pairs": matched, "state_pairs": state_pairs,
                             "linked_pairs": linked_pairs,
                             "identity_resolved": bool(identity.user_ids),
                             "identity": identity, "facts_by_pair": facts_by_pair,
                             "state_by_pair": state_by_pair, "ledger": ledger,
                             "audit_at": cutoff,
                             "all_fact_pairs": all_facts, "future_fact_pairs": future,
                             "all_activity_pairs": all_activity}
    return predictions, contexts, Counter(src for _, src, _ in intents), forced_count, policy_case_count


def _apply_intent_mode(intent: tuple[bool, str, str], intent_mode: str
                       ) -> tuple[tuple[bool, str, str], bool]:
    """Apply the evaluator-only override without weakening events or hard negation."""
    if intent_mode not in {"classified", "assume-deletion"}:
        raise ValueError("intent_mode must be 'classified' or 'assume-deletion'")
    deletion, source, reason = intent
    hard_negation = source == "NEGATION" and "explicit negation" in reason.casefold()
    if intent_mode == "assume-deletion" and source != "EVENT" and not hard_negation:
        return (True, "DEV_ASSUME_DELETION", "Forced by eval-only assume-deletion mode."), True
    return intent, False


def _facts_by_pair(ledger: Any, cutoff: Any) -> dict[tuple[str, str], list[Any]]:
    facts: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for fact in ledger.facts:
        observed = pd.to_datetime(fact.observed_at, errors="coerce", utc=True)
        if pd.isna(observed) or observed > cutoff:
            continue
        facts[(fact.system_id, fact.resource_id.casefold())].append(fact)
    return dict(facts)


def _resource_cause(case_id: str, pair: tuple[str, str], contexts: dict[str, Any]) -> str:
    context = contexts.get(case_id, {})
    if pair in context.get("matched_pairs", set()) or pair in context.get("state_pairs", set()):
        return "scope"
    if pair in context.get("future_fact_pairs", set()):
        return "scope"
    if pair in context.get("all_fact_pairs", set()) or pair in context.get("all_activity_pairs", set()):
        return "identity"
    return "identity"


def _case_diff(case_id: str, gold: dict[str, Any], prediction: dict[str, Any] | None,
               contexts: dict[str, Any]) -> dict[str, Any]:
    prediction = prediction or {"deletion_status": "<MISSING>", "steps": []}
    gold_steps = _steps(gold.get("steps_json", gold.get("steps", [])))
    pred_steps = _steps(prediction.get("steps_json", prediction.get("steps", [])))
    gold_sig, pred_sig = [_sig(x) for x in gold_steps], [_sig(x) for x in pred_steps]
    gold_set, pred_set = set(gold_sig), set(pred_sig)
    missing = [x for x in gold_steps if _sig(x) not in pred_set]
    extra = [x for x in pred_steps if _sig(x) not in gold_set]
    gold_status, pred_status = str(gold.get("deletion_status", "")), str(prediction.get("deletion_status", ""))
    exact = gold_status == pred_status and _rowsig(gold_steps) == _rowsig(pred_steps)
    causes: set[str] = set()
    details = []
    if any(x.get("phase") == "FINDING" for x in missing):
        causes.add("missing finding")
    if any(x.get("phase") == "FINDING" for x in extra):
        causes.add("extra finding")

    def evidence_key(step: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(step.get(field) for field in STEP_FIELDS[:-1])
    ge, pe = defaultdict(list), defaultdict(list)
    for step in gold_steps:
        ge[evidence_key(step)].append(str(step.get("evidence_id", "")))
    for step in pred_steps:
        pe[evidence_key(step)].append(str(step.get("evidence_id", "")))
    for key in ge.keys() & pe.keys():
        if Counter(ge[key]) != Counter(pe[key]):
            causes.add("wrong evidence_id")
            details.append(f"evidence_id differs for {key}")
            break

    go, po = defaultdict(set), defaultdict(set)
    for step in gold_steps:
        go[(step.get("phase"), step.get("system_id"), step.get("resource_id"))].add(step.get("operation"))
    for step in pred_steps:
        po[(step.get("phase"), step.get("system_id"), step.get("resource_id"))].add(step.get("operation"))
    for key in go.keys() & po.keys():
        if go[key] != po[key]:
            causes.add("wrong operation")
            details.append(f"operation differs for {key}: expected {sorted(map(str, go[key]))}; predicted {sorted(map(str, po[key]))}")
            break

    shared_gold = [sig for sig in gold_sig if sig in pred_set]
    shared_pred = [sig for sig in pred_sig if sig in gold_set]
    if shared_gold != shared_pred:
        causes.add("ordering")
        details.append("shared steps occur in a different order")

    gold_resources = {(str(x.get("system_id", "")), str(x.get("resource_id", "")).casefold()) for x in gold_steps}
    pred_resources = {(str(x.get("system_id", "")), str(x.get("resource_id", "")).casefold()) for x in pred_steps}
    missing_resources, extra_resources = gold_resources - pred_resources, pred_resources - gold_resources
    if missing_resources or extra_resources:
        for pair in sorted(missing_resources):
            cause = _resource_cause(case_id, pair, contexts)
            causes.add(cause)
            details.append(f"missing resource {pair[0]}/{pair[1]} ({cause})")
        for pair in sorted(extra_resources):
            causes.add("scope")
            details.append(f"extra resource {pair[0]}/{pair[1]} (scope over-inclusion)")
    for step in missing:
        if step.get("phase") != "FINDING":
            pair = (str(step.get("system_id", "")), str(step.get("resource_id", "")).casefold())
            causes.add(_resource_cause(case_id, pair, contexts))
    details.extend("missing step: " + _fmt_sig(_sig(x)) for x in missing)
    details.extend("extra step: " + _fmt_sig(_sig(x)) for x in extra)
    if gold_status != pred_status and not causes:
        causes.add("scope")
        details.append(f"status differs: expected {gold_status}, predicted {pred_status}")
    if not exact and not causes:
        causes.add("scope")
    return {"case_id": case_id, "gold_status": gold_status, "predicted_status": pred_status,
            "gold_steps": gold_steps, "predicted_steps": pred_steps,
            "gold_signatures": gold_sig, "predicted_signatures": pred_sig,
            "missing_steps": missing, "extra_steps": extra, "row_exact": exact,
            "status_correct": gold_status == pred_status, "step_tp": len(gold_set & pred_set),
            "step_union": len(gold_set | pred_set), "sequence_correct": gold_sig == pred_sig,
            "causes": sorted(causes), "details": details}


def score_predictions(predictions: dict[str, dict[str, Any]], sample_output: pd.DataFrame,
                      contexts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compute the five scores, field accuracy, and cause-grouped case diffs."""
    contexts = contexts or {}
    gold = {str(row.case_id): {"deletion_status": str(row.deletion_status),
                               "steps_json": row.steps_json}
            for row in sample_output.itertuples(index=False)}
    diffs = [_case_diff(case, row, predictions.get(case), contexts) for case, row in gold.items()]
    n = len(diffs)
    status_correct = sum(d["status_correct"] for d in diffs)
    row_correct = sum(d["row_exact"] for d in diffs)
    sequence_correct = sum(d["sequence_correct"] for d in diffs)
    tp, union = sum(d["step_tp"] for d in diffs), sum(d["step_union"] for d in diffs)

    fields = ("step_no", *STEP_FIELDS)
    counts = {field: [0, 0] for field in fields}
    for diff in diffs:
        expected, actual = diff["gold_steps"], diff["predicted_steps"]
        for index in range(max(len(expected), len(actual))):
            for field in fields:
                counts[field][1] += 1
                if index < len(expected) and index < len(actual) and expected[index].get(field) == actual[index].get(field):
                    counts[field][0] += 1
    counts["deletion_status"] = [status_correct, n]
    field_accuracy = {field: {"correct": correct, "total": total,
                              "accuracy": correct / total if total else 1.0}
                      for field, (correct, total) in counts.items()}
    macro = sum(item["accuracy"] for item in field_accuracy.values()) / len(field_accuracy) if field_accuracy else 1.0
    cause_cases = {cause: [d["case_id"] for d in diffs if cause in d["causes"]]
                   for cause in FAILURE_CAUSES}
    return {
        "cases": n, "status_correct": status_correct,
        "status_accuracy": status_correct / n if n else 1.0,
        "row_exact_correct": row_correct, "row_exact_accuracy": row_correct / n if n else 1.0,
        "step_true_positive": tp, "step_union": union,
        "step_level_accuracy": tp / union if union else 1.0,
        "sequence_correct": sequence_correct,
        "sequence_accuracy": sequence_correct / n if n else 1.0,
        "field_accuracy": field_accuracy, "field_level_accuracy": macro,
        "failure_cause_cases": cause_cases,
        "failure_cause_counts": {cause: len(ids) for cause, ids in cause_cases.items()},
        "case_diffs": diffs,
    }


def _score_signatures(gold_by_case: dict[str, list[tuple[Any, ...]]],
                      pred_by_case: dict[str, list[tuple[Any, ...]]]) -> dict[str, Any]:
    true_positive = union = sequence_correct = 0
    for case_id, gold in gold_by_case.items():
        pred = pred_by_case.get(case_id, [])
        gold_set, pred_set = set(gold), set(pred)
        true_positive += len(gold_set & pred_set)
        union += len(gold_set | pred_set)
        sequence_correct += gold == pred
    return {"true_positive": true_positive, "union": union,
            "step_set_accuracy": true_positive / union if union else 1.0,
            "sequence_correct": sequence_correct,
            "sequence_accuracy": sequence_correct / len(gold_by_case) if gold_by_case else 1.0}


def _resource_key(step: dict[str, Any]) -> tuple[str, str]:
    return str(step.get("system_id", "")), str(step.get("resource_id", "")).casefold()


def _field_breakdown_shared_resources(diffs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    fields = STEP_FIELDS
    counts = {field: [0, 0] for field in fields}
    for diff in diffs:
        gold_resources = {_resource_key(step) for step in diff["gold_steps"]}
        pred_resources = {_resource_key(step) for step in diff["predicted_steps"]}
        shared = gold_resources & pred_resources
        for resource in shared:
            expected = [step for step in diff["gold_steps"] if _resource_key(step) == resource]
            actual = [step for step in diff["predicted_steps"] if _resource_key(step) == resource]
            for index in range(max(len(expected), len(actual))):
                for field in fields:
                    counts[field][1] += 1
                    if (index < len(expected) and index < len(actual)
                            and expected[index].get(field) == actual[index].get(field)):
                        counts[field][0] += 1
    return {field: {"correct": good, "total": total,
                    "accuracy": good / total if total else 1.0}
            for field, (good, total) in counts.items()}


def supplemental_views(metrics: dict[str, Any], predictions: dict[str, dict[str, Any]],
                       sample_output: pd.DataFrame,
                       contexts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compute evidence-free, linked-only, status-class, and diagnostic views."""
    contexts = contexts or {}
    gold_by_case = {str(row.case_id): {
        "deletion_status": str(row.deletion_status), "steps": _steps(row.steps_json),
    } for row in sample_output.itertuples(index=False)}
    pred_by_case = {case_id: _steps(row.get("steps", []))
                    for case_id, row in predictions.items()}
    all_cases = list(gold_by_case)

    no_evidence_gold = {case: [tuple(step.get(field) for field in STEP_FIELDS[:-1])
                               for step in gold_by_case[case]["steps"]]
                        for case in all_cases}
    no_evidence_pred = {case: [tuple(step.get(field) for field in STEP_FIELDS[:-1])
                               for step in pred_by_case.get(case, [])]
                        for case in all_cases}
    ignore_evidence = _score_signatures(no_evidence_gold, no_evidence_pred)

    linked_gold: dict[str, list[dict[str, Any]]] = {}
    linked_pred: dict[str, list[dict[str, Any]]] = {}
    fully_linked_cases: list[str] = []
    for case in all_cases:
        linked = contexts.get(case, {}).get("linked_pairs", set())
        expected = [step for step in gold_by_case[case]["steps"] if _resource_key(step) in linked]
        actual = [step for step in pred_by_case.get(case, []) if _resource_key(step) in linked]
        linked_gold[case], linked_pred[case] = expected, actual
        expected_resources = {_resource_key(step) for step in gold_by_case[case]["steps"]}
        if expected_resources.issubset(linked):
            fully_linked_cases.append(case)
    linked_step_scores = _score_signatures(
        {case: [_sig(step) for step in linked_gold[case]] for case in all_cases},
        {case: [_sig(step) for step in linked_pred[case]] for case in all_cases},
    )

    exact_linked_cases = 0
    for case in fully_linked_cases:
        status = str(predictions.get(case, {}).get("deletion_status", "<MISSING>"))
        expected_status = gold_by_case[case]["deletion_status"]
        # Renumber after filtering so removed unlinked steps don't create artificial
        # step_no mismatches in the linked-only row comparison.
        expected_rows = [{**step, "step_no": index}
                         for index, step in enumerate(linked_gold[case], 1)]
        predicted_rows = [{**step, "step_no": index}
                          for index, step in enumerate(linked_pred[case], 1)]
        exact_linked_cases += status == expected_status and _rowsig(expected_rows) == _rowsig(predicted_rows)

    status_split = {}
    confusion = {expected: {predicted: 0 for predicted in ("COMPLETE", "INCOMPLETE")}
                 for expected in ("COMPLETE", "INCOMPLETE")}
    predicted_na = []
    for expected_status in ("COMPLETE", "INCOMPLETE"):
        group = [case for case in all_cases if gold_by_case[case]["deletion_status"] == expected_status]
        correct = sum(str(predictions.get(case, {}).get("deletion_status", "")) == expected_status
                      for case in group)
        status_split[expected_status] = {"correct": correct, "total": len(group),
                                         "accuracy": correct / len(group) if group else 1.0}
    for case in all_cases:
        expected_status = gold_by_case[case]["deletion_status"]
        predicted_status = str(predictions.get(case, {}).get("deletion_status", "<MISSING>"))
        if expected_status in confusion:
            if predicted_status in {"COMPLETE", "INCOMPLETE"}:
                confusion[expected_status][predicted_status] += 1
            else:
                predicted_na.append(case)

    wrong_status = [diff for diff in metrics["case_diffs"] if not diff["status_correct"]]
    diagnostics = []
    for diff in metrics["case_diffs"]:
        expected_findings = [step for step in diff["gold_steps"] if step.get("phase") == "FINDING"]
        predicted_findings = [step for step in diff["predicted_steps"] if step.get("phase") == "FINDING"]
        detail = None
        if not diff["status_correct"]:
            detail = _diagnose_wrong_status(diff["case_id"], expected_findings,
                                            predicted_findings, contexts.get(diff["case_id"], {}))
        diagnostics.append({"case_id": diff["case_id"],
                            "expected_status": diff["gold_status"],
                            "predicted_status": diff["predicted_status"],
                            "expected_findings": len(expected_findings),
                            "predicted_findings": len(predicted_findings),
                            "wrong_status": detail})
    return {
        "ignore_evidence": ignore_evidence,
        "linked_only": {**linked_step_scores,
                        "fully_linked_case_count": len(fully_linked_cases),
                        "exact_correct": exact_linked_cases,
                        "exact_total": len(fully_linked_cases),
                        "exact_accuracy": exact_linked_cases / len(fully_linked_cases)
                        if fully_linked_cases else 1.0,
                        "linked_resources_per_case": {case: len({ _resource_key(s) for s in linked_gold[case]})
                                                       for case in all_cases}},
        "status_split": status_split,
        "status_confusion": confusion,
        "predicted_not_applicable_cases": predicted_na,
        "shared_resource_field_accuracy": _field_breakdown_shared_resources(metrics["case_diffs"]),
        "diagnostic_cases": diagnostics,
        "wrong_status_diagnostics": [item for item in diagnostics if item["wrong_status"] is not None],
    }


def _fact_matches_identity(fact: Any, identity: Any) -> bool:
    return bool(
        {str(v).casefold() for v in fact.emails} & {str(v).casefold() for v in identity.emails}
        or {str(v).casefold() for v in fact.hashes} & {str(v).casefold() for v in identity.hashes}
        or set(fact.phones) & set(identity.phones)
        or {str(v).casefold() for v in fact.user_ids} & {str(v).casefold() for v in identity.user_ids}
    )


def _fact_label(fact: Any) -> str:
    return f"{fact.file_id}@{fact.observed_at.isoformat()} state={fact.state}"


def _expected_missed_cause(step: dict[str, Any], context: dict[str, Any]) -> tuple[str, str]:
    pair = _resource_key(step)
    identity = context.get("identity")
    if not identity or not identity.user_ids:
        return "identity not resolved", "case identity has no resolved user_id"
    facts = context.get("facts_by_pair", {}).get(pair, [])
    cited_file = str(step.get("evidence_id", ""))
    cited_facts = [fact for fact in facts if fact.file_id == cited_file]
    matched_facts = [fact for fact in facts if _fact_matches_identity(fact, identity)]
    state = context.get("state_by_pair", {}).get(pair)
    if not facts:
        return "resource not in ledger", f"no parsed Fact exists for {pair[0]}/{pair[1]} at audit_at"
    if not matched_facts and pair not in context.get("linked_pairs", set()):
        return "identity not resolved", "ledger has this resource but no Fact or identity link matches this case"
    if cited_facts and state is not None and state.evidence_id != cited_file:
        return "snapshot selection", f"expected cited file {cited_file}, resolver selected {state.evidence_id}"
    if state is not None and state.state in {"ABSENT", "UNKNOWN"}:
        return f"state resolved {state.state} wrongly", f"resolver selected {state.state} from {state.evidence_id or 'no evidence'}"
    if state is None:
        return "snapshot selection", "matching Fact/link exists, but resolve_states emitted no resource state"
    decision = decide(state, context.get("audit_at"))
    if decision is None or not decision.finding_op:
        return "policy mapping", f"resolved {state.category}/{state.state} produced no finding"
    if decision.finding_op != step.get("operation"):
        return "policy mapping", f"resolved finding {decision.finding_op} differs from expected {step.get('operation')}"
    return "snapshot selection", f"resolved Fact/evidence {state.evidence_id} differs from expected {cited_file}"


def _false_finding_causes(step: dict[str, Any], findings: list[dict[str, Any]],
                          context: dict[str, Any]) -> tuple[list[str], list[str]]:
    pair = _resource_key(step)
    state = context.get("state_by_pair", {}).get(pair)
    causes: list[str] = []
    details: list[str] = []
    if state is None:
        causes.append("out-of-scope system")
    else:
        flags = {str(flag).upper() for flag in state.flags}
        if "OUT_OF_SCOPE" in flags:
            causes.append("out-of-scope system")
        facts = context.get("facts_by_pair", {}).get(pair, [])
        used = [fact for fact in facts if fact.file_id == state.evidence_id]
        used_fact = max(used, key=lambda f: f.observed_at) if used else None
        cutoff = context.get("audit_at")
        if used_fact and cutoff is not None:
            later = [fact for fact in facts if fact.observed_at > used_fact.observed_at
                     and fact.observed_at <= cutoff]
            if later:
                causes.append("older snapshot treated as current at audit_at")
                details.append("newer eligible Fact: " + _fact_label(max(later, key=lambda f: f.observed_at)))
        if "REPLICA_DRIFT" in flags:
            causes.append("replica drift flagged wrongly")
        operation = str(step.get("operation", ""))
        category = str(state.category).upper()
        expected_categories = {
            "REPORT_REMAINING_RECORD": {"USER_PROFILE", "SECONDARY_IDENTIFIER", "SEARCH_INDEX_ENTRY",
                                        "CACHE_ENTRY", "USER_EXPORT", "MARKETING_PROFILE",
                                        "SUPPORT_ATTACHMENT"},
            "REPORT_EXPOSED_PII": {"ANALYTICS_PROFILE", "PRODUCT_TELEMETRY", "SUPPORT_MESSAGE",
                                   "EMAIL_DELIVERY_LOG", "ACCOUNT_TOMBSTONE"},
            "REPORT_ACTIVE_DATA_FLOW": {"DATA_FLOW"},
            "REPORT_RESTORE_RISK": {"BACKUP_ARCHIVE"},
        }
        if category not in expected_categories.get(operation, set()):
            causes.append("wrong category")
        same_resource = [item for item in findings
                         if _resource_key(item) == pair]
        if len(same_resource) > 1:
            causes.append("duplicate resource")
    if not causes:
        causes.append("wrong category")
        details.append("predicted finding does not correspond to an expected finding or known false-positive condition")
    if state is not None:
        facts = context.get("facts_by_pair", {}).get(pair, [])
        cited = [fact for fact in facts if fact.file_id == state.evidence_id]
        if cited:
            details.append("trigger Fact: " + _fact_label(max(cited, key=lambda fact: fact.observed_at)))
        else:
            details.append(f"trigger state: {state.evidence_id or 'no Fact'} state={state.state}; flags={','.join(state.flags)}")
    else:
        details.append("trigger Fact: no in-scope ResourceState; out of scope")
    return list(dict.fromkeys(causes)), details


def _diagnose_wrong_status(case_id: str, expected: list[dict[str, Any]],
                           predicted: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    def find_key(step: dict[str, Any]) -> tuple[str, str, str]:
        return (*_resource_key(step), str(step.get("operation", "")))
    expected_keys = {find_key(step) for step in expected}
    predicted_keys = {find_key(step) for step in predicted}
    missed = []
    for step in expected:
        if find_key(step) in predicted_keys:
            continue
        cause, rationale = _expected_missed_cause(step, context)
        missed.append({"system_id": step.get("system_id"), "resource_id": step.get("resource_id"),
                       "operation": step.get("operation"), "evidence_id": step.get("evidence_id"),
                       "cause": cause, "rationale": rationale})
    false = []
    for step in predicted:
        if find_key(step) in expected_keys:
            continue
        causes, details = _false_finding_causes(step, predicted, context)
        false.append({"system_id": step.get("system_id"), "resource_id": step.get("resource_id"),
                      "operation": step.get("operation"), "evidence_id": step.get("evidence_id"),
                      "causes": causes, "details": details})
    return {"missed_findings": missed, "false_findings": false}


def _format_steps(steps: list[dict[str, Any]]) -> str:
    return "; ".join(_fmt_sig(_sig(step)) for step in steps) if steps else "(none)"


def render_report(metrics: dict[str, Any], custom_results: list[dict[str, Any]],
                  source: str, intent_sources: Counter[str] | None = None,
                  *, intent_mode: str = "classified", forced_intents: int = 0) -> str:
    lines = [
        "# Evaluation Report", "", "## Run configuration", "",
        f"- Prediction source: `{source}`.",
        f"- Evaluation intent mode: `{intent_mode}` (forced deletion decisions: {forced_intents}; cases reaching policy: {metrics.get('policy_case_count', 'n/a')}).",
        "- The assume-deletion override is implemented only by this evaluator; it is not wired into the run command.",
        "", "## a) Full metrics", "",
        f"- Case status accuracy: **{metrics['status_correct']}/{metrics['cases']} ({metrics['status_accuracy']:.1%})**.",
        f"- Exact row accuracy: **{metrics['row_exact_correct']}/{metrics['cases']} ({metrics['row_exact_accuracy']:.1%})**.",
        f"- Step-set accuracy (Jaccard, including evidence_id): **{metrics['step_true_positive']}/{metrics['step_union']} ({metrics['step_level_accuracy']:.1%})**.",
        f"- Field macro accuracy: **{metrics['field_level_accuracy']:.1%}**.",
        f"- Sequence accuracy: **{metrics['sequence_correct']}/{metrics['cases']} ({metrics['sequence_accuracy']:.1%})**.",
        "", "## b) Ignoring evidence_id", "",
        f"- Step-set accuracy: **{metrics['ignore_evidence']['true_positive']}/{metrics['ignore_evidence']['union']} ({metrics['ignore_evidence']['step_set_accuracy']:.1%})**.",
        f"- Sequence accuracy: **{metrics['ignore_evidence']['sequence_correct']}/{metrics['cases']} ({metrics['ignore_evidence']['sequence_accuracy']:.1%})**.",
        "", "## c) Linked-only view", "",
        "Expected steps are retained only when the resource has an identity-matched parsed Fact or an explicit/evidence-adjacent identity link; timestamp-only anchors do not qualify.",
        f"- Linked-only step-set accuracy: **{metrics['linked_only']['true_positive']}/{metrics['linked_only']['union']} ({metrics['linked_only']['step_set_accuracy']:.1%})**.",
        f"- Linked-only sequence accuracy: **{metrics['linked_only']['sequence_correct']}/{metrics['cases']} ({metrics['linked_only']['sequence_accuracy']:.1%})**.",
        f"- Exact rows among cases whose expected resources are all linked: **{metrics['linked_only']['exact_correct']}/{metrics['linked_only']['exact_total']} ({metrics['linked_only']['exact_accuracy']:.1%})**.",
        "", "## d) Status accuracy and confusion", "",
        "| Expected status | Correct | Cases | Accuracy |", "|---|---:|---:|---:|",
    ]
    for status, item in metrics["status_split"].items():
        lines.append(f"| {status} | {item['correct']} | {item['total']} | {item['accuracy']:.1%} |")
    lines += ["", "### 2×2 expected-vs-predicted confusion table", "",
              "| Expected \\ Predicted | COMPLETE | INCOMPLETE |", "|---|---:|---:|"]
    for expected in ("COMPLETE", "INCOMPLETE"):
        row = metrics["status_confusion"][expected]
        lines.append(f"| {expected} | {row['COMPLETE']} | {row['INCOMPLETE']} |")
    lines.append(f"- Predicted NOT_APPLICABLE or missing status outside the 2×2: {len(metrics['predicted_not_applicable_cases'])} ({', '.join(metrics['predicted_not_applicable_cases']) or 'none'}).")
    lines += ["", "## Field breakdown on shared resources", "",
              "Only resources present in both expected and predicted step lists are compared. Steps are aligned in local sequence order within each resource; unmatched positions count incorrect.",
              "", "| Field | Correct | Compared | Accuracy |", "|---|---:|---:|---:|"]
    for field, item in metrics["shared_resource_field_accuracy"].items():
        lines.append(f"| `{field}` | {item['correct']} | {item['total']} | {item['accuracy']:.1%} |")
    lines += ["", "## Per-case diagnostic table", "",
              "| Case | Expected status | Predicted status | Expected findings | Predicted findings |", "|---|---|---|---:|---:|"]
    for item in metrics["diagnostic_cases"]:
        lines.append(f"| {item['case_id']} | {item['expected_status']} | {item['predicted_status']} | {item['expected_findings']} | {item['predicted_findings']} |")
    lines += ["", "### Findings diagnostics for wrong-status cases", ""]
    for item in metrics["wrong_status_diagnostics"]:
        lines.append(f"#### {item['case_id']} — expected {item['expected_status']}, predicted {item['predicted_status']}")
        detail = item["wrong_status"] or {}
        lines.append("- MISSED FINDINGS:")
        if detail.get("missed_findings"):
            for finding in detail["missed_findings"]:
                lines.append(f"  - `{finding['system_id']}/{finding['resource_id']}` {finding['operation']} (evidence `{finding['evidence_id']}`): **{finding['cause']}** — {finding['rationale']}.")
        else:
            lines.append("  - none")
        lines.append("- FALSE FINDINGS:")
        if detail.get("false_findings"):
            for finding in detail["false_findings"]:
                lines.append(f"  - `{finding['system_id']}/{finding['resource_id']}` {finding['operation']} (evidence `{finding['evidence_id']}`): **{', '.join(finding['causes'])}**.")
                lines.extend(f"    - {fact}" for fact in finding["details"])
        else:
            lines.append("  - none")
        lines.append("")
    lines += ["## Failure causes", "", "| Cause | Cases | Case IDs |", "|---|---:|---|"]
    for cause in FAILURE_CAUSES:
        ids = metrics["failure_cause_cases"].get(cause, [])
        lines.append(f"| {cause} | {len(ids)} | {', '.join(ids) if ids else '—'} |")
    lines += ["", "## Custom evaluation cases", ""]
    if custom_results:
        scored = [item for item in custom_results if item["correct"] is not None]
        correct = sum(item["correct"] is True for item in scored)
        lines.append(f"- Intent accuracy: {correct}/{len(scored)} ({correct / len(scored):.1%})." if scored
                     else "- No custom case has a supported expected label.")
        lines += ["", "| ID | Expected | Predicted | Source | Result |", "|---|---|---|---|---|"]
        for item in custom_results:
            outcome = "PASS" if item["correct"] is True else "FAIL" if item["correct"] is False else "UNSCORED"
            lines.append(f"| {item['id']} | {item['expected'] or '—'} | {item['predicted']} | {item['source']} | {outcome} |")
    else:
        lines.append("- No custom cases were found.")
    if intent_sources:
        lines += ["", "### Intent sources before evaluation override", ""]
        lines.extend(f"- {key}: {value}" for key, value in sorted(intent_sources.items()))
    lines += ["", "## Metric definitions", "",
              "Full step-set is a micro Jaccard score over per-case sets of (phase, system_id, resource_id, operation, state, evidence_id). The evidence-free view removes evidence_id from those tuples. Sequence uses ordered tuples and excludes step_no. Full field macro averages positional accuracy for each serialized field plus deletion_status; the shared-resource breakdown compares fields only on resource keys appearing on both sides. Linked-only exact rows filter both step arrays to linked resources and renumber the filtered arrays. Status confusion lists COMPLETE/INCOMPLETE; predicted NOT_APPLICABLE and missing statuses are enumerated separately.", ""]
    return "\n".join(lines)


def evaluate(dataset_dir: str | Path = DATASET_DIR, predictions_path: str | Path | None = None,
             *, llm: Any = None, no_llm: bool = False,
             custom_cases_dir: str | Path = DEFAULT_CUSTOM_CASES,
             report_path: str | Path = DEFAULT_REPORT,
             account_guess: bool = False,
             intent_mode: str = "classified",
             generate_sample: bool = False) -> dict[str, Any]:
    """Evaluate a supplied prediction file, or generate predictions for sample rows."""
    if intent_mode not in {"classified", "assume-deletion"}:
        raise ValueError("intent_mode must be 'classified' or 'assume-deletion'")
    ds = load_all(dataset_dir)
    client = llm if llm is not None else LLMClient(no_llm=no_llm)
    contexts, intent_sources, forced_count, policy_case_count = {}, None, 0, 0
    if predictions_path is None and not generate_sample:
        default_path = Path(dataset_dir).resolve().parent / "output.csv"
        if default_path.is_file() and default_path.stat().st_size:
            predictions_path = default_path
    if predictions_path is None:
        predictions, contexts, intent_sources, forced_count, policy_case_count = _sample_predictions(
            ds, dataset_dir, client, account_guess=account_guess, intent_mode=intent_mode)
        source = f"generated sample pipeline ({'no-LLM' if no_llm else 'configured LLM'})"
    else:
        if intent_mode == "assume-deletion":
            raise ValueError("--intent-mode assume-deletion applies only when eval generates sample predictions")
        predictions, source = load_predictions(predictions_path), str(Path(predictions_path))
        # Build identity/resource context for the linked-only and diagnostic views
        # without substituting these generated predictions for the supplied file.
        _, contexts, intent_sources, _, _ = _sample_predictions(
            ds, dataset_dir, client, account_guess=account_guess, intent_mode="classified")
    metrics = score_predictions(predictions, ds.sample_output, contexts)
    metrics.update(supplemental_views(metrics, predictions, ds.sample_output, contexts))
    custom_cases = load_custom_cases(custom_cases_dir)
    custom_results = _custom_results(custom_cases, ds, client)
    metrics.update({"prediction_source": source, "custom_results": custom_results,
                    "custom_case_count": len(custom_cases), "intent_mode": intent_mode,
                    "forced_intents": forced_count, "policy_case_count": policy_case_count})
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_report(metrics, custom_results, source, intent_sources,
                                    intent_mode=intent_mode, forced_intents=forced_count),
                      encoding="utf-8")
    return metrics


def print_metrics(metrics: dict[str, Any], report_path: str | Path = DEFAULT_REPORT) -> None:
    print(f"intent mode: {metrics.get('intent_mode', 'classified')}; forced deletions: {metrics.get('forced_intents', 0)}; "
          f"cases reaching policy: {metrics.get('policy_case_count', 'n/a')}")
    print("a) full")
    print(f"cases: {metrics['cases']}")
    print(f"case status accuracy: {metrics['status_correct']}/{metrics['cases']} ({metrics['status_accuracy']:.1%})")
    print(f"row exact-match accuracy: {metrics['row_exact_correct']}/{metrics['cases']} ({metrics['row_exact_accuracy']:.1%})")
    print(f"step-level set accuracy: {metrics['step_true_positive']}/{metrics['step_union']} ({metrics['step_level_accuracy']:.1%})")
    print(f"field-level macro accuracy: {metrics['field_level_accuracy']:.1%}")
    for field, item in metrics["field_accuracy"].items():
        print(f"  {field}: {item['correct']}/{item['total']} ({item['accuracy']:.1%})")
    print(f"sequence accuracy: {metrics['sequence_correct']}/{metrics['cases']} ({metrics['sequence_accuracy']:.1%})")
    print("b) ignoring evidence_id")
    print(f"step-set accuracy: {metrics['ignore_evidence']['true_positive']}/{metrics['ignore_evidence']['union']} ({metrics['ignore_evidence']['step_set_accuracy']:.1%})")
    print(f"sequence accuracy: {metrics['ignore_evidence']['sequence_correct']}/{metrics['cases']} ({metrics['ignore_evidence']['sequence_accuracy']:.1%})")
    print("c) linked-only")
    linked = metrics['linked_only']
    print(f"step-set accuracy: {linked['true_positive']}/{linked['union']} ({linked['step_set_accuracy']:.1%})")
    print(f"sequence accuracy: {linked['sequence_correct']}/{metrics['cases']} ({linked['sequence_accuracy']:.1%})")
    print(f"exact rows for fully linked expected cases: {linked['exact_correct']}/{linked['exact_total']} ({linked['exact_accuracy']:.1%})")
    print("d) status split")
    for expected, item in metrics["status_split"].items():
        print(f"  {expected}: {item['correct']}/{item['total']} ({item['accuracy']:.1%})")
    print("  confusion matrix: expected rows COMPLETE, INCOMPLETE; predicted columns COMPLETE, INCOMPLETE")
    print(f"    COMPLETE: {metrics['status_confusion']['COMPLETE']['COMPLETE']}, {metrics['status_confusion']['COMPLETE']['INCOMPLETE']}")
    print(f"    INCOMPLETE: {metrics['status_confusion']['INCOMPLETE']['COMPLETE']}, {metrics['status_confusion']['INCOMPLETE']['INCOMPLETE']}")
    print(f"  predicted NOT_APPLICABLE/missing: {', '.join(metrics['predicted_not_applicable_cases']) or 'none'}")
    print("shared-resource field breakdown:")
    for field, item in metrics["shared_resource_field_accuracy"].items():
        print(f"  {field}: {item['correct']}/{item['total']} ({item['accuracy']:.1%})")
    print("failure causes:")
    for cause, count in metrics["failure_cause_counts"].items():
        if count:
            print(f"  {cause}: {count} cases ({', '.join(metrics['failure_cause_cases'][cause])})")
    print("per-case diffs:")
    for diff in metrics["case_diffs"]:
        if diff["row_exact"]:
            print(f"  {diff['case_id']}: MATCH")
        else:
            print(f"  {diff['case_id']}: expected {diff['gold_status']}, got {diff['predicted_status']}; "
                  f"steps {len(diff['gold_steps'])}->{len(diff['predicted_steps'])}; "
                  f"causes={', '.join(diff['causes']) or 'field difference'}")
            for detail in diff["details"]:
                print(f"    {detail}")
    print("per-case diagnostic table:")
    for item in metrics["diagnostic_cases"]:
        print(f"  {item['case_id']}: expected={item['expected_status']} predicted={item['predicted_status']} "
              f"findings={item['expected_findings']}->{item['predicted_findings']}")
        if item["wrong_status"]:
            for finding in item["wrong_status"]["missed_findings"]:
                print(f"    MISSED {finding['system_id']}/{finding['resource_id']} {finding['operation']}: {finding['cause']} ({finding['rationale']})")
            for finding in item["wrong_status"]["false_findings"]:
                print(f"    FALSE {finding['system_id']}/{finding['resource_id']} {finding['operation']}: {', '.join(finding['causes'])}")
                for detail in finding["details"]:
                    print(f"      {detail}")
    if metrics.get("custom_case_count"):
        scored = [item for item in metrics["custom_results"] if item["correct"] is not None]
        correct = sum(item["correct"] is True for item in scored)
        print(f"custom intent cases: {correct}/{len(scored)} scored; loaded={metrics['custom_case_count']}")
    print(f"report: {report_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    parser.add_argument("--predictions", type=Path, default=None,
                        help="prediction CSV; defaults to root output.csv if present, otherwise runs sample pipeline")
    parser.add_argument("--custom-cases", type=Path, default=DEFAULT_CUSTOM_CASES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--no-llm", action="store_true",
                        help="use cached evidence and fail-closed intent fallback")
    parser.add_argument("--intent-mode", choices=("classified", "assume-deletion"), default="classified",
                        help="evaluation-only intent override; assume-deletion preserves linked events and hard negations")
    parser.add_argument("--account-guess", action="store_true",
                        help="pass opt-in account guessing through to state resolution")
    args = parser.parse_args(argv)
    metrics = evaluate(args.dataset_dir, args.predictions, no_llm=args.no_llm,
                       custom_cases_dir=args.custom_cases, report_path=args.report,
                       account_guess=args.account_guess, intent_mode=args.intent_mode)
    print_metrics(metrics, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

