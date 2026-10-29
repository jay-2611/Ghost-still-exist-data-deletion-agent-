from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from policy import decide, fired_rule, load_deletion_rules  # noqa: E402
from identity import IdentitySet  # noqa: E402
from ledger import Ledger  # noqa: E402
from parsers import Fact, RETAINED  # noqa: E402
from state import ResourceState, resolve_states  # noqa: E402


AUDIT_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _state(category: str, state: str, *, flags: tuple[str, ...] = (),
           resource_id: str = "resource_1") -> ResourceState:
    return ResourceState("system", resource_id, category, state, "evidence_1", flags)


def test_policy_table_is_seeded_from_deletion_rules_csv():
    rows = load_deletion_rules()
    assert len(rows) == 15
    assert any(row["rule_id"] == "rule_06" and row["required_action"] == "DELETE"
               for row in rows)


def test_delete_and_already_absent_decisions():
    remaining = decide(_state("USER_PROFILE", "PRESENT"), AUDIT_AT)
    clean = decide(_state("USER_PROFILE", "ABSENT"), AUDIT_AT)

    assert (remaining.finding_op, remaining.remediation_op, remaining.verify_op,
            remaining.target_state) == (
                "REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT", "ABSENT")
    assert clean.finding_op is None and clean.remediation_op is None
    assert clean.verify_op == "VERIFY_RECORD_ABSENT"


def test_identifiable_analytics_and_redacted_support_decisions():
    exposed = decide(_state("ANALYTICS_PROFILE", "PRESENT",
                            flags=("HAS_EXPOSED_PII",)), AUDIT_AT)
    clean = decide(_state("SUPPORT_MESSAGE", "REDACTED"), AUDIT_AT)

    assert exposed.finding_op == "REPORT_EXPOSED_PII"
    assert exposed.remediation_op == "ANONYMIZE_RECORD"
    assert exposed.verify_op == "VERIFY_RECORD_ANONYMIZED"
    assert clean.finding_op is None and clean.verify_op == "VERIFY_RECORD_REDACTED"


def test_active_flow_and_restorable_backup_get_blocking_plans():
    flow = decide(_state("DATA_FLOW", "ACTIVE"), AUDIT_AT)
    backup = _state("BACKUP_ARCHIVE", "ACTIVE",
                    flags=("RECREATION_RISK:RESTORABLE_BACKUP",))
    backup_decision = decide(backup, AUDIT_AT)

    assert (flow.finding_op, flow.remediation_op, flow.verify_op, flow.target_state) == (
        "REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW", "VERIFY_DATA_FLOW_DISABLED", "DISABLED")
    assert backup_decision.finding_op == "REPORT_RESTORE_RISK"
    assert backup_decision.remediation_op == "BLOCK_RESTORE"
    assert backup_decision.verify_op == "VERIFY_RESTORE_BLOCKED"


def test_audit_retention_and_legal_hold_are_verification_only():
    retained = _state("SECURITY_AUDIT_LOG", "PRESENT",
                      flags=("RETENTION_UNTIL:2027-01-01T00:00:00Z",))
    decision = decide(retained, AUDIT_AT)
    legal_hold = decide(_state("LEGAL_HOLD_RECORD", "RETAINED"), AUDIT_AT)

    assert decision.finding_op is None and decision.remediation_op is None
    assert decision.verify_op == "VERIFY_RECORD_PRESENT"
    assert fired_rule(retained, AUDIT_AT).guard == "WITHIN_RETENTION"
    assert legal_hold.finding_op is None and legal_hold.verify_op == "VERIFY_RECORD_PRESENT"


def test_state_resolver_carries_sql_retention_date_into_policy_flags():
    identity = IdentitySet(
        user_ids=("user_5",), emails=frozenset(), hashes=frozenset(), phones=frozenset(),
        linked_resources=frozenset(), primary_user_id="user_5", flags=frozenset(),
    )
    fact = Fact(
        file_id="snapshot", observed_at=AUDIT_AT, system_id="security_service",
        resource_id="audit_record_5", category="SECURITY_AUDIT_LOG", state=RETAINED,
        emails=(), hashes=(), phones=(), user_ids=("user_5",), names=(), topology=None,
        source_kind="sql",
        raw_ref='{"row":{"retention_until":"2027-01-01T00:00:00Z"}}',
    )
    ledger = Ledger([fact], {"snapshot": {"security_service": AUDIT_AT}})

    resolved = resolve_states(identity, ledger, object(), AUDIT_AT)[0]
    decision = decide(resolved, AUDIT_AT)

    assert "RETENTION_UNTIL:2027-01-01T00:00:00Z" in resolved.flags
    assert decision.verify_op == "VERIFY_RECORD_PRESENT"


def test_attachment_rule_requires_only_subject_ownership():
    shared = _state("SUPPORT_ATTACHMENT", "PRESENT", resource_id="support_20")
    owned = _state("SUPPORT_ATTACHMENT", "PRESENT", flags=("ONLY_SUBJECT",),
                   resource_id="support_21")

    assert decide(shared, AUDIT_AT) is None
    decision = decide(owned, AUDIT_AT)
    assert decision.finding_op == "REPORT_REMAINING_RECORD"
    assert decision.remediation_op == "DELETE_RECORD"

