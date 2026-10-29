"""Validate the serialized audit output against the project contract."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from loader import DATASET_DIR, load_all
from steps import OPERATION_ORDER, OPERATION_STATES, PHASE_ORDER


HEADER = ("case_id", "deletion_status", "steps_json")
STEP_FIELDS = {"step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"}
ALLOWED_STATUSES = {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}
_REMEDIATION_LINKS = {
    "DISABLE_DATA_FLOW": ("REPORT_ACTIVE_DATA_FLOW", "VERIFY_DATA_FLOW_DISABLED"),
    "BLOCK_RESTORE": ("REPORT_RESTORE_RISK", "VERIFY_RESTORE_BLOCKED"),
    "DELETE_RECORD": ("REPORT_REMAINING_RECORD", "VERIFY_RECORD_ABSENT"),
    "REDACT_RECORD": ("REPORT_EXPOSED_PII", "VERIFY_RECORD_REDACTED"),
    "ANONYMIZE_RECORD": ("REPORT_EXPOSED_PII", "VERIFY_RECORD_ANONYMIZED"),
}


def _phase_operation_key(step: dict[str, Any]) -> tuple[int, int]:
    phase = str(step.get("phase", ""))
    operation = str(step.get("operation", ""))
    return (PHASE_ORDER.get(phase, 99), OPERATION_ORDER.get(phase, {}).get(operation, 99))


def _one_row_errors(case_id: str, status: str, steps_json: str,
                    valid_evidence: set[str]) -> list[str]:
    errors: list[str] = []
    prefix = f"{case_id}: "
    try:
        steps = json.loads(steps_json)
    except (TypeError, json.JSONDecodeError) as exc:
        return [prefix + f"steps_json is invalid JSON ({type(exc).__name__})"]
    if not isinstance(steps, list):
        return [prefix + "steps_json must decode to a JSON array"]
    if status not in ALLOWED_STATUSES:
        errors.append(prefix + f"invalid deletion_status {status!r}")
    if status == "NOT_APPLICABLE" and steps:
        errors.append(prefix + "NOT_APPLICABLE must have an empty steps array")

    step_numbers: list[int] = []
    clean_steps: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    text_fields = ("phase", "system_id", "resource_id", "operation", "state", "evidence_id")
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            errors.append(prefix + f"step {index} must be a JSON object")
            continue
        if set(step) != STEP_FIELDS:
            errors.append(prefix + f"step {index} fields must be exactly {sorted(STEP_FIELDS)}")
        number = step.get("step_no")
        if isinstance(number, bool) or not isinstance(number, int):
            errors.append(prefix + f"step {index} step_no must be an integer")
        else:
            step_numbers.append(number)
        phase = step.get("phase")
        operation = step.get("operation")
        state = step.get("state")
        expected_state = OPERATION_STATES.get((str(phase), str(operation)))
        if expected_state is None:
            errors.append(prefix + f"step {index} has disallowed phase/operation {phase!r}/{operation!r}")
        elif state != expected_state:
            errors.append(prefix + f"step {index} {operation} requires state {expected_state}, got {state!r}")
        evidence_id = step.get("evidence_id")
        if not isinstance(evidence_id, str):
            errors.append(prefix + f"step {index} evidence_id must be a string")
        elif evidence_id and evidence_id not in valid_evidence:
            errors.append(prefix + f"step {index} cites unknown evidence_id {evidence_id!r}")

        if not isinstance(phase, str) or phase not in PHASE_ORDER:
            errors.append(prefix + f"step {index} has invalid phase {phase!r}")
        for field in text_fields[1:]:
            if not isinstance(step.get(field), str):
                errors.append(prefix + f"step {index} {field} must be a string")
        if (set(step) == STEP_FIELDS and all(isinstance(step.get(field), str)
                                             for field in text_fields)):
            clean_steps.append(step)
            signature = tuple(step.get(field) for field in (
                "phase", "system_id", "resource_id", "operation", "state", "evidence_id"))
            if signature in seen:
                errors.append(prefix + f"duplicate step at position {index}: {signature[3]}")
            seen.add(signature)

    if step_numbers != list(range(1, len(steps) + 1)):
        errors.append(prefix + "step_no values must be consecutive from 1")
    if clean_steps:
        keys = [_phase_operation_key(step) for step in clean_steps]
        if keys != sorted(keys):
            errors.append(prefix + "steps must be ordered by phase and operation")

    findings = {(step.get("system_id"), step.get("resource_id"), step.get("operation"))
                for step in clean_steps if step.get("phase") == "FINDING"}
    verifications = {(step.get("system_id"), step.get("resource_id"), step.get("operation"))
                     for step in clean_steps if step.get("phase") == "VERIFICATION"}
    remediations = [step for step in clean_steps if step.get("phase") == "REMEDIATION"]
    for step in remediations:
        finding_op, verify_op = _REMEDIATION_LINKS.get(str(step.get("operation")), (None, None))
        key = (step.get("system_id"), step.get("resource_id"))
        if (key[0], key[1], finding_op) not in findings:
            errors.append(prefix + f"{step.get('operation')} has no matching finding for {key}")
        if (key[0], key[1], verify_op) not in verifications:
            errors.append(prefix + f"{step.get('operation')} has no matching verification for {key}")

    if status == "COMPLETE":
        if any(step.get("phase") != "VERIFICATION" for step in clean_steps):
            errors.append(prefix + "COMPLETE cases may contain verification steps only")
        if any(step.get("phase") == "REMEDIATION" for step in clean_steps):
            errors.append(prefix + "COMPLETE cases cannot contain remediation")
        if not clean_steps:
            errors.append(prefix + "COMPLETE cases require verification evidence")
        if any(not step.get("evidence_id") for step in clean_steps):
            errors.append(prefix + "COMPLETE verification steps require evidence_id")
    elif status == "INCOMPLETE":
        for step in clean_steps:
            if step.get("phase") == "FINDING" and not step.get("evidence_id"):
                errors.append(prefix + "INCOMPLETE findings require evidence_id")
            if step.get("phase") in {"REMEDIATION", "VERIFICATION"} and step.get("evidence_id"):
                errors.append(prefix + f"INCOMPLETE {step.get('phase')} evidence_id must be empty")
        if not any(step.get("phase") == "FINDING" for step in clean_steps):
            errors.append(prefix + "INCOMPLETE cases require at least one finding")
        if not any(step.get("phase") == "VERIFICATION" for step in clean_steps):
            errors.append(prefix + "INCOMPLETE cases require verification steps")
    return errors


def validate_output(path: str | Path, dataset_dir: str | Path = DATASET_DIR,
                    *, sample: bool | None = None) -> list[str]:
    """Return all format, reference, row-count, and step-invariant errors.

    The canonical dataset/sample_output.csv is recognized automatically and checked
    against the 32 sample request IDs. All other files default to the required 518
    request rows. Set ``sample`` explicitly to override that detection in tests.
    """
    output_path = Path(path)
    dataset_root = Path(dataset_dir)
    ds = load_all(dataset_root)
    if sample is None:
        sample = output_path.resolve() == (dataset_root / "sample_output.csv").resolve()
    request_frame = ds.sample_deletion_requests if sample else ds.deletion_requests
    expected_ids = [str(value) for value in request_frame.case_id]
    valid_evidence = set(ds.evidence_files.file_id.astype(str))
    errors: list[str] = []

    try:
        with output_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream)
            header = next(reader, [])
            if tuple(header) != HEADER:
                errors.append(f"header must be exactly {','.join(HEADER)}; got {header!r}")
            raw_rows = list(reader)
    except OSError as exc:
        return [f"could not read output file ({type(exc).__name__}): {output_path}"]

    expected_count = len(expected_ids)
    if len(raw_rows) != expected_count:
        errors.append(f"expected {expected_count} data rows; found {len(raw_rows)}")
    parsed_ids: list[str] = []
    rows_to_check: list[tuple[str, str, str]] = []
    for row_no, row in enumerate(raw_rows, 2):
        if len(row) != len(HEADER):
            errors.append(f"CSV row {row_no} must have exactly 3 fields; found {len(row)}")
            continue
        case_id, status, steps_json = row
        parsed_ids.append(case_id)
        rows_to_check.append((case_id, status, steps_json))
    if parsed_ids != sorted(parsed_ids):
        errors.append("case rows must be sorted by case_id")
    if len(parsed_ids) != len(set(parsed_ids)):
        errors.append("case_id values must be unique")
    if set(parsed_ids) != set(expected_ids):
        missing = sorted(set(expected_ids) - set(parsed_ids))
        extra = sorted(set(parsed_ids) - set(expected_ids))
        errors.append(f"case_id set differs from requests; missing={missing[:10]}, extra={extra[:10]}")

    for case_id, status, steps_json in rows_to_check:
        errors.extend(_one_row_errors(case_id, status, steps_json, valid_evidence))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=str(Path(__file__).resolve().parents[1] / "output.csv"))
    parser.add_argument("--sample", action="store_true", help="validate against the 32 sample requests")
    args = parser.parse_args(argv)
    errors = validate_output(args.path, sample=True if args.sample else None)
    if errors:
        print(f"validation failed: {len(errors)} error(s)")
        for error in errors:
            print(f"- {error}")
        return 1
    print("validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
