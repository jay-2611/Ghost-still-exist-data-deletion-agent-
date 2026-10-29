"""Data-driven policy decisions for identity-linked resource states."""

from __future__ import annotations

import csv
import json as _stdjson
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


RULES_PATH = Path(__file__).resolve().parents[1] / "dataset" / "deletion_rules.csv"


@dataclass(frozen=True)
class Decision:
    system_id: str
    resource_id: str
    category: str
    finding_op: str | None
    remediation_op: str | None
    verify_op: str
    target_state: str
    evidence_id: str


@dataclass(frozen=True)
class RuleSpec:
    """A row in the compiled category/condition/state decision table."""

    rule_id: str
    category: str
    condition: str
    state: str
    finding_op: str | None
    remediation_op: str | None
    verify_op: str
    target_state: str
    guard: str = ""


def load_deletion_rules(path: str | Path = RULES_PATH) -> tuple[dict[str, dict[str, str]], ...]:
    """Read the supplied policy CSV, retaining its source rule IDs and conditions."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        rows = csv.DictReader(stream)
        required = {"rule_id", "data_category", "condition", "required_action"}
        if not required.issubset(rows.fieldnames or ()):
            raise ValueError(f"deletion_rules.csv must contain {sorted(required)}")
        return tuple({key: (row.get(key) or "").strip() for key in required}
                     for row in rows)


_SEED_RULES = load_deletion_rules() if RULES_PATH.is_file() else ()
RULES_BY_CATEGORY: dict[str, dict[str, str]] = {
    row["data_category"].upper(): row for row in _SEED_RULES
}

_DELETE_REMAINING = ("REPORT_REMAINING_RECORD", "DELETE_RECORD",
                     "VERIFY_RECORD_ABSENT", "ABSENT")
_EXPOSED_REDACT = ("REPORT_EXPOSED_PII", "REDACT_RECORD",
                   "VERIFY_RECORD_REDACTED", "REDACTED")
_EXPOSED_ANONYMIZE = ("REPORT_EXPOSED_PII", "ANONYMIZE_RECORD",
                       "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED")


def _compile_rules(seed: Iterable[dict[str, str]]) -> tuple[RuleSpec, ...]:
    """Compile CSV actions and explicit state/category overrides into one table."""
    result: list[RuleSpec] = []
    for row in seed:
        category = row["data_category"].upper()
        action = row["required_action"].upper()
        rule_id = row["rule_id"]
        condition = row["condition"]

        if action == "DELETE":
            if category == "SUPPORT_ATTACHMENT":
                # Rule 06 is conditional: never delete a shared attachment.
                result.append(RuleSpec(rule_id, category, condition, "PRESENT",
                                       *_DELETE_REMAINING, guard="ONLY_SUBJECT"))
                result.append(RuleSpec(rule_id, category, condition, "ABSENT",
                                       None, None, "VERIFY_RECORD_ABSENT", "ABSENT"))
            else:
                result.append(RuleSpec(rule_id, category, condition, "PRESENT",
                                       *_DELETE_REMAINING))
                result.append(RuleSpec(rule_id, category, condition, "IDENTIFIABLE",
                                       *_DELETE_REMAINING))
                result.append(RuleSpec(rule_id, category, condition, "ABSENT",
                                       None, None, "VERIFY_RECORD_ABSENT", "ABSENT"))
        elif action == "ANONYMIZE":
            result.extend((
                RuleSpec(rule_id, category, condition, "IDENTIFIABLE", *_EXPOSED_ANONYMIZE),
                RuleSpec(rule_id, category, condition, "PRESENT", *_EXPOSED_ANONYMIZE,
                         guard="EXPOSED_PII"),
                RuleSpec(rule_id, category, condition, "ANONYMIZED", None, None,
                         "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
                RuleSpec(rule_id, category, condition, "ABSENT", None, None,
                         "VERIFY_RECORD_ABSENT", "ABSENT"),
            ))
        elif action == "REDACT":
            result.extend((
                RuleSpec(rule_id, category, condition, "IDENTIFIABLE", *_EXPOSED_REDACT),
                RuleSpec(rule_id, category, condition, "PRESENT", *_EXPOSED_REDACT,
                         guard="EXPOSED_PII"),
                RuleSpec(rule_id, category, condition, "REDACTED", None, None,
                         "VERIFY_RECORD_REDACTED", "REDACTED"),
                RuleSpec(rule_id, category, condition, "ABSENT", None, None,
                         "VERIFY_RECORD_ABSENT", "ABSENT"),
            ))
            if category in {"SUPPORT_MESSAGE", "EMAIL_DELIVERY_LOG", "ACCOUNT_TOMBSTONE"}:
                result.append(RuleSpec(rule_id, category, condition, "PRESENT", None, None,
                                       "VERIFY_RECORD_PRESENT", "PRESENT",
                                       guard="NO_EXPOSED_PII"))
        elif action == "RETAIN":
            if category == "SECURITY_AUDIT_LOG":
                # Explicit override: retain while the supplied time limit is active;
                # after expiry the row must be removed under this deletion audit.
                result.extend((
                    RuleSpec(rule_id, category, condition, "PRESENT", None, None,
                             "VERIFY_RECORD_PRESENT", "PRESENT", guard="WITHIN_RETENTION"),
                    RuleSpec(rule_id, category, condition, "RETAINED", None, None,
                             "VERIFY_RECORD_PRESENT", "PRESENT", guard="WITHIN_RETENTION"),
                    RuleSpec(rule_id, category, condition, "PRESENT", *_DELETE_REMAINING,
                             guard="RETENTION_EXPIRED"),
                    RuleSpec(rule_id, category, condition, "RETAINED", *_DELETE_REMAINING,
                             guard="RETENTION_EXPIRED"),
                    RuleSpec(rule_id, category, condition, "ABSENT", None, None,
                             "VERIFY_RECORD_PRESENT", "PRESENT"),
                ))
            elif category == "BACKUP_ARCHIVE":
                # Explicit override: preserve the archive but block any active restore path.
                result.extend((
                    RuleSpec(rule_id, category, condition, "ACTIVE", "REPORT_RESTORE_RISK",
                             "BLOCK_RESTORE", "VERIFY_RESTORE_BLOCKED", "BLOCKED",
                             guard="RESTORABLE"),
                    RuleSpec(rule_id, category, condition, "BLOCKED", None, None,
                             "VERIFY_RESTORE_BLOCKED", "BLOCKED"),
                    RuleSpec(rule_id, category, condition, "ABSENT", None, None,
                             "VERIFY_RECORD_ABSENT", "ABSENT"),
                ))
            elif category == "LEGAL_HOLD_RECORD":
                # This category is retained context; it has no finding or remediation.
                result.extend((
                    RuleSpec(rule_id, category, condition, "PRESENT", None, None,
                             "VERIFY_RECORD_PRESENT", "PRESENT"),
                    RuleSpec(rule_id, category, condition, "RETAINED", None, None,
                             "VERIFY_RECORD_PRESENT", "PRESENT"),
                ))

    # The activity category is not a deletion_rules.csv row, so it is an explicit
    # override in the same table.
    result.extend((
        RuleSpec("override_data_flow", "DATA_FLOW", "Enabled connector can recreate data",
                 "ACTIVE", "REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW",
                 "VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
        RuleSpec("override_data_flow", "DATA_FLOW", "Already disabled",
                 "DISABLED", None, None, "VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
        RuleSpec("override_data_flow", "DATA_FLOW", "Already absent",
                 "ABSENT", None, None, "VERIFY_RECORD_ABSENT", "ABSENT"),
    ))
    return tuple(result)


DECISION_RULES = _compile_rules(_SEED_RULES)


def _flags(resource_state: Any) -> set[str]:
    return {str(flag).strip().upper() for flag in getattr(resource_state, "flags", ())}


def _has_flag(flags: set[str], expected: str) -> bool:
    return any(flag == expected or flag.startswith(expected + ":") or
               flag.startswith(expected + "=") for flag in flags)


def _retention_until(resource_state: Any) -> datetime | None:
    explicit = getattr(resource_state, "retention_until", None)
    candidates: list[str] = [str(explicit)] if explicit else []
    candidates.extend(flag.split(":", 1)[1].strip() for flag in _flags(resource_state)
                      if flag.startswith("RETENTION_UNTIL:") and ":" in flag)
    candidates.extend(flag.split("=", 1)[1].strip() for flag in _flags(resource_state)
                      if flag.startswith("RETENTION_UNTIL=") and "=" in flag)
    raw_ref = getattr(resource_state, "raw_ref", "")
    if raw_ref:
        try:
            raw = _stdjson.loads(str(raw_ref))
        except (TypeError, ValueError):
            raw = {}

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if str(key).lower() in {"retention_until", "retain_until"} and child:
                        candidates.append(str(child).strip())
                    else:
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(raw)
    for value in candidates:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
    return None


def _audit_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _guard_matches(rule: RuleSpec, resource_state: Any, audit_at: Any) -> bool:
    flags = _flags(resource_state)
    if rule.guard == "ONLY_SUBJECT":
        return (_has_flag(flags, "ONLY_SUBJECT") or
                str(getattr(resource_state, "ownership", "")).upper() == "ONLY_SUBJECT")
    if rule.guard == "EXPOSED_PII":
        return _has_flag(flags, "HAS_EXPOSED_PII") or _has_flag(flags, "EXPOSED_PII")
    if rule.guard == "NO_EXPOSED_PII":
        return not (_has_flag(flags, "HAS_EXPOSED_PII") or _has_flag(flags, "EXPOSED_PII"))
    if rule.guard in {"WITHIN_RETENTION", "RETENTION_EXPIRED"}:
        until, cutoff = _retention_until(resource_state), _audit_datetime(audit_at)
        if cutoff is None:
            return False
        if until is None:
            return rule.guard == "WITHIN_RETENTION"
        return (until > cutoff) if rule.guard == "WITHIN_RETENTION" else (until <= cutoff)
    if rule.guard == "RESTORABLE":
        return (_has_flag(flags, "RECREATION_RISK:RESTORABLE_BACKUP") or
                _has_flag(flags, "RESTORABLE") or _has_flag(flags, "RESTORE_ALLOWED"))
    return True


def fired_rule(resource_state: Any, audit_at: Any) -> RuleSpec | None:
    """Return the first matching table row, useful for diagnostics and audits."""
    category = str(getattr(resource_state, "category", "")).strip().upper()
    state = str(getattr(resource_state, "state", "")).strip().upper()
    for rule in DECISION_RULES:
        if rule.category == category and rule.state == state and _guard_matches(rule, resource_state, audit_at):
            return rule
    return None


def decide(resource_state: Any, audit_at: Any) -> Decision | None:
    """Apply the compiled policy table to one resolved resource state."""
    rule = fired_rule(resource_state, audit_at)
    if rule is None:
        return None
    return Decision(
        system_id=str(getattr(resource_state, "system_id", "")),
        resource_id=str(getattr(resource_state, "resource_id", "")),
        category=str(getattr(resource_state, "category", "")),
        finding_op=rule.finding_op,
        remediation_op=rule.remediation_op,
        verify_op=rule.verify_op,
        target_state=rule.target_state,
        evidence_id=str(getattr(resource_state, "evidence_id", "") or ""),
    )
