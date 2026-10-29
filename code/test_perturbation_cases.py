from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from identity import IdentitySet, resolve  # noqa: E402
from ledger import Ledger  # noqa: E402
from parsers import Fact, IDENTIFIABLE, PRESENT  # noqa: E402
from policy import decide  # noqa: E402
from state import ResourceState, resolve_states  # noqa: E402

DATASET = ROOT / "dataset"
CUSTOM_CASES = ROOT / "code" / "evaluation" / "custom_cases" / "perturbation_cases.json"
AUDIT_AT = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def _cases():
    return json.loads(CUSTOM_CASES.read_text(encoding="utf-8-sig"))


def _dataset_stub():
    return SimpleNamespace(
        evidence_files=pd.DataFrame(columns=["file_id", "captured_at", "file_path"]),
        system_activity=pd.DataFrame(),
        PREFIX_TO_SYSTEM={"account_": "account_service", "tombstone_": "identity_service"},
        RESOURCE_PREFIX_TO_SYSTEM={"account_": "account_service", "tombstone_": "identity_service"},
    )


def test_perturbation_cases_have_explicit_expected_answers_and_public_bases():
    cases = _cases()
    sample_ids = set(pd.read_csv(DATASET / "sample_deletion_requests.csv").case_id.astype(str))
    assert len(cases) >= 3
    assert all(case["base_case_id"] in sample_ids for case in cases)
    assert all(case["expected"] == "COMPLETE_OR_INCOMPLETE_DELETION" for case in cases)
    assert all(case.get("expected_result") for case in cases)


def test_historical_email_only_perturbation_resolves_the_original_subject():
    case = next(item for item in _cases() if item["id"] == "perturb_old_email_only_case10")
    requests = pd.read_csv(DATASET / "sample_deletion_requests.csv")
    base = requests.loc[requests.case_id.eq(case["base_case_id"])].iloc[0]
    ds = __import__("loader").load_all(DATASET)

    identity = resolve(case["email"], ds, base.audit_at)

    assert set(identity.user_ids) == set(case["expected_result"]["identity_user_ids"])


def test_disabled_flow_perturbation_verifies_without_reporting_or_disabling_it():
    case = next(item for item in _cases() if item["id"] == "perturb_flow_disabled_case11")
    decision = decide(ResourceState(
        "integration_service", case["perturbation"]["resource_id"], "DATA_FLOW",
        "DISABLED", "evidence_1"), AUDIT_AT)

    assert decision.finding_op is None
    assert decision.remediation_op is None
    assert decision.verify_op == case["expected_result"]["flow_verification"]


def test_missing_system_snapshot_does_not_turn_positive_replica_into_absence():
    case = next(item for item in _cases() if item["id"] == "perturb_missing_system_snapshot_case05")
    identity = IdentitySet(
        user_ids=("user_05",), emails=frozenset({"leila.haddad@yahoo.com"}),
        hashes=frozenset(), phones=frozenset(), linked_resources=frozenset(),
        primary_user_id="user_05", flags=frozenset(),
    )
    fact = Fact(
        file_id="replica_evidence", observed_at=AUDIT_AT,
        system_id="account_service", resource_id=case["perturbation"]["retain_positive_replica_observation"],
        category="USER_PROFILE", state=PRESENT, emails=("leila.haddad@yahoo.com",),
        hashes=(), phones=(), user_ids=("user_05",), names=(), topology="failover_replica",
        source_kind="sql", raw_ref="{}",
    )
    states = resolve_states(identity, Ledger([fact], {}), _dataset_stub(), AUDIT_AT)
    state = next(item for item in states if item.resource_id == fact.resource_id)
    decision = decide(state, AUDIT_AT)

    assert state.state == case["expected_result"]["resource_state"]
    assert decision.finding_op == case["expected_result"]["finding"][1]


def test_tombstone_phone_perturbation_requires_redaction():
    case = next(item for item in _cases() if item["id"] == "perturb_tombstone_phone_case32")
    state = ResourceState(
        "identity_service", case["perturbation"]["resource_id"], "ACCOUNT_TOMBSTONE",
        "PRESENT", "evidence_1", ("HAS_EXPOSED_PII",),
    )
    decision = decide(state, AUDIT_AT)

    assert (decision.finding_op, decision.remediation_op, decision.verify_op) == (
        case["expected_result"]["finding"][1], case["expected_result"]["remediation"][1],
        case["expected_result"]["verification"][1])
