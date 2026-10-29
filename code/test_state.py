from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from identity import IdentitySet  # noqa: E402
from ledger import Ledger  # noqa: E402
from parsers import Fact, PRESENT  # noqa: E402
from state import link_identity_resources, resolve_states  # noqa: E402


def test_replica_only_resource_is_present_with_replica_drift_flag():
    earlier = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    latest = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
    identity = IdentitySet(
        user_ids=("user_05",), emails=frozenset({"person@example.com"}),
        hashes=frozenset(), phones=frozenset(), linked_resources=frozenset(),
        primary_user_id="user_05", flags=frozenset(),
    )
    replica_fact = Fact(
        file_id="replica", observed_at=earlier, system_id="account_service",
        resource_id="account_005", category="USER_PROFILE", state=PRESENT,
        emails=("person@example.com",), hashes=(), phones=(), user_ids=("user_05",),
        names=(), topology="failover_replica", source_kind="sql", raw_ref="{}",
    )
    ledger = Ledger(
        [replica_fact], {"replica": {"account_service": earlier}},
    )
    ds = SimpleNamespace(
        PREFIX_TO_SYSTEM={"account_": "account_service"},
        RESOURCE_PREFIX_TO_SYSTEM={"account_": "account_service"},
    )

    links = link_identity_resources(identity, ledger, ds, latest)
    states = resolve_states(identity, ledger, ds, latest)
    drift = next(state for state in states if state.resource_id == "account_005")
    assert links["account_005"]["source"] == "IDENTITY_ADJACENT_EVIDENCE"
    assert drift.state == "PRESENT"
    assert drift.evidence_id == "replica"
    assert "REPLICA_DRIFT" in drift.flags


def test_newer_scoped_absence_is_not_overridden_by_stale_replica():
    earlier = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    latest = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
    identity = IdentitySet(
        user_ids=("user_05",), emails=frozenset({"person@example.com"}),
        hashes=frozenset(), phones=frozenset(), linked_resources=frozenset(),
        primary_user_id="user_05", flags=frozenset(),
    )
    replica_fact = Fact(
        file_id="replica", observed_at=earlier, system_id="account_service",
        resource_id="account_005", category="USER_PROFILE", state=PRESENT,
        emails=("person@example.com",), hashes=(), phones=(), user_ids=("user_05",),
        names=(), topology="failover_replica", source_kind="sql", raw_ref="{}",
    )
    ledger = Ledger(
        [replica_fact], {"replica": {"account_service": earlier},
                         "latest_snapshot": {"account_service": latest}},
    )
    ds = SimpleNamespace(PREFIX_TO_SYSTEM={"account_": "account_service"})

    state = resolve_states(identity, ledger, ds, latest)[0]

    assert state.state == "ABSENT"
    assert state.evidence_id == "latest_snapshot"
    assert "REPLICA_DRIFT" not in state.flags


def test_linked_resource_outside_every_scope_is_unknown_not_absent():
    audit_at = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
    identity = IdentitySet(
        user_ids=("user_05",), emails=frozenset(), hashes=frozenset(), phones=frozenset(),
        linked_resources=frozenset({"account_005"}), primary_user_id="user_05",
        flags=frozenset(),
    )
    ledger = Ledger([], {})
    ds = SimpleNamespace(PREFIX_TO_SYSTEM={"account_": "account_service"})

    state = resolve_states(identity, ledger, ds, audit_at)[0]

    assert state.state == "UNKNOWN"
    assert "OUT_OF_SCOPE" in state.flags


def test_account_number_similarity_never_links_identity():
    identity = IdentitySet(
        user_ids=("user_01",), emails=frozenset({"person@example.com"}),
        hashes=frozenset(), phones=frozenset(), linked_resources=frozenset(),
        primary_user_id="user_01", flags=frozenset(),
    )
    fact = Fact(
        file_id="unrelated", observed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        system_id="account_service", resource_id="account_001", category="USER_PROFILE",
        state=PRESENT, emails=(), hashes=(), phones=(), user_ids=(), names=(),
        topology="failover_replica", source_kind="sql", raw_ref="{}",
    )
    ledger = Ledger([fact], {})
    ds = SimpleNamespace(PREFIX_TO_SYSTEM={"account_": "account_service"})

    assert link_identity_resources(identity, ledger, ds, "2026-09-02T00:00:00Z") == {}


def test_identity_adjacent_source_resource_id_links_account_without_creating_fact():
    observed = datetime(2026, 9, 1, tzinfo=timezone.utc)
    identity = IdentitySet(
        user_ids=("user_06",), emails=frozenset({"person@example.com"}),
        hashes=frozenset(), phones=frozenset(), linked_resources=frozenset(),
        primary_user_id="user_06", flags=frozenset(),
    )
    search_fact = Fact(
        file_id="search_snapshot", observed_at=observed, system_id="search_service",
        resource_id="search_001", category="SEARCH_INDEX_ENTRY", state=PRESENT,
        emails=("person@example.com",), hashes=(), phones=(), user_ids=("user_06",),
        names=(), topology="primary", source_kind="sql",
        raw_ref='{"row":{"resource_id":"search_001","source_resource_id":"account_006"}}',
    )
    ledger = Ledger([search_fact], {})
    ds = SimpleNamespace(PREFIX_TO_SYSTEM={"account_": "account_service"})

    links = link_identity_resources(identity, ledger, ds, "2026-09-02T00:00:00Z")
    assert links["account_006"]["source"] == "IDENTITY_ADJACENT_EVIDENCE"
    assert links["account_006"]["file_id"] == "search_snapshot"
    assert "account_006" not in {fact.resource_id for fact in ledger.facts}


def test_unknown_lookup_key_does_not_prove_account_ownership():
    observed = datetime(2026, 9, 1, tzinfo=timezone.utc)
    identity = IdentitySet(
        user_ids=("user_17",), emails=frozenset({"person@example.com"}),
        hashes=frozenset(), phones=frozenset(), linked_resources=frozenset(),
        primary_user_id="user_17", flags=frozenset(),
    )
    lookup_start = Fact(
        file_id="lookup_log", observed_at=observed, system_id="account_service",
        resource_id="account_6523", category="USER_PROFILE", state="UNKNOWN",
        emails=("person@example.com",), hashes=(), phones=(), user_ids=(), names=(),
        topology=None, source_kind="log", raw_ref='{"event":"profile_lookup_started"}',
    )
    ledger = Ledger([lookup_start], {})
    ds = SimpleNamespace(PREFIX_TO_SYSTEM={"account_": "account_service"})

    assert link_identity_resources(identity, ledger, ds, "2026-09-02T00:00:00Z") == {}


def test_linked_activity_without_state_is_unknown():
    observed = datetime(2026, 9, 1, tzinfo=timezone.utc)
    identity = IdentitySet(
        user_ids=("user_01",), emails=frozenset(), hashes=frozenset(), phones=frozenset(),
        linked_resources=frozenset({"search_9"}), primary_user_id="user_01", flags=frozenset(),
    )
    ds = SimpleNamespace(
        PREFIX_TO_SYSTEM={"search_": "search_service"},
        activity_for_resource=lambda rid: pd.DataFrame([{
            "activity_id": "activity_1", "event_type": "LINK_RESOURCE_IDENTITY",
        }]),
    )
    ledger = Ledger([], {})

    states = resolve_states(identity, ledger, ds, observed)
    assert len(states) == 1
    assert states[0].state == "UNKNOWN"
    assert states[0].evidence_id == "activity_1"
    assert "ACTIVITY_ONLY" in states[0].flags


def test_activity_nearest_account_guess_is_opt_in_and_snapshot_backed():
    observed = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
    identity = IdentitySet(
        user_ids=("user_99",), emails=frozenset(), hashes=frozenset(), phones=frozenset(),
        linked_resources=frozenset(), primary_user_id="user_99", flags=frozenset(),
    )
    ledger = Ledger([], {"snapshot": {"account_service": observed}})
    ds = SimpleNamespace(
        PREFIX_TO_SYSTEM={"account_": "account_service"},
        system_activity=pd.DataFrame([{
            "event_type": "DELETE_RECORD", "event_time": observed - pd.Timedelta(minutes=1),
            "resource_id": "account_777", "target_system": "account_service",
        }]),
    )

    assert resolve_states(identity, ledger, ds, observed) == []
    guessed = resolve_states(identity, ledger, ds, observed, account_guess=True)
    assert len(guessed) == 1
    assert guessed[0].resource_id == "account_777"
    assert guessed[0].state == "ABSENT"
    assert guessed[0].evidence_id == "snapshot"
    assert "ACCOUNT_GUESS_LOW_CONFIDENCE" in guessed[0].flags
