"""Small cache and identity-query tests for the evidence ledger."""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

import ledger as ledger_module  # noqa: E402
from ledger import Ledger  # noqa: E402
from parsers import Fact, PRESENT, RETAINED  # noqa: E402


def test_ledger_builds_once_then_uses_disk_cache(monkeypatch):
    with tempfile.TemporaryDirectory(dir=ROOT / "code") as temporary:
        root = Path(temporary) / "dataset"
        (root / "evidence").mkdir(parents=True)
        (root / "sample_output.csv").write_text("sample", encoding="utf-8")
        evidence = root / "evidence" / "stub.json"
        evidence.write_text("{}", encoding="utf-8")
        ds = SimpleNamespace(evidence_files=pd.DataFrame([{
            "file_id": "e1", "file_path": "evidence/stub.json",
        }]))
        calls = []

        def fake_parse(row, dataset_dir, llm=None):
            calls.append(str(row["file_id"]))
            return [Fact(
                file_id="e1", observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                system_id="account_service", resource_id="account_1", category="USER_PROFILE",
                state=PRESENT, emails=("person@example.com",), hashes=(), phones=(),
                user_ids=("user_1",), names=(), topology=None,
                source_kind="json", raw_ref="{}",
            )], {"account_service": datetime(2026, 1, 1, tzinfo=timezone.utc)}

        monkeypatch.setattr(ledger_module, "parse_file", fake_parse)
        cache = Path(temporary) / "cache"
        first = Ledger.build(ds, root, llm=object(), cache_dir=cache)
        second = Ledger.build(ds, root, llm=object(), cache_dir=cache)
        identity = SimpleNamespace(
            emails=frozenset({"person@example.com"}), hashes=frozenset(), phones=frozenset(),
            user_ids=("user_1",), linked_resources=frozenset(),
        )
        assert first.cache_hit is False
        assert second.cache_hit is True
        assert second.build_seconds < 2.0
        assert calls == ["e1"]
        assert len(second.query(identity)) == 1


def test_time_anchor_is_marked_and_legal_hold_is_context_only():
    captured = datetime(2026, 9, 1, 11, 30, tzinfo=timezone.utc)
    cutoff = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    facts = [
        Fact("image1", captured, "support_platform", "support_1", "SUPPORT_ATTACHMENT",
             PRESENT, (), (), (), (), (), None, "image", "{}"),
        Fact("image1", captured, "legal_retention_service", "order_1", "LEGAL_HOLD_RECORD",
             RETAINED, (), (), (), (), (), None, "image", "{}", ("CONTEXT_ONLY",)),
        Fact("later", cutoff + timedelta(minutes=1), "account_service", "account_1", "USER_PROFILE",
             PRESENT, ("person@example.com",), (), (), (), (), None, "json", "{}"),
    ]
    ds = SimpleNamespace(evidence_files=pd.DataFrame([{
        "file_id": "image1", "captured_at": captured,
    }]))
    identity = SimpleNamespace(
        emails=frozenset({"person@example.com"}), hashes=frozenset(), phones=frozenset(),
        user_ids=(), linked_resources=frozenset(),
    )
    ledger = Ledger(facts, {}, single_subject_files={"image1"}, subjects_by_file={"image1": set()})
    ledger.by_file = {"image1": facts[:2], "later": facts[2:]}

    case_facts = ledger.query_for_case(identity, ds, cutoff)
    anchored = next(fact for fact in case_facts if fact.resource_id == "support_1")
    assert "BOUND_BY_TIME" in anchored.flags
    assert not any(fact.resource_id == "account_1" for fact in case_facts)
    assert not any(fact.category == "LEGAL_HOLD_RECORD"
                   for fact in ledger.step_candidate_facts(identity, ds, cutoff))


def test_link_activity_ownership_details_are_retained():
    ds = SimpleNamespace(system_activity=pd.DataFrame([{
        "event_type": "LINK_RESOURCE_IDENTITY",
        "resource_id": "object_19",
        "details": "Attachment catalog (delivery_confirmation_19.pdf) belongs only to "
                   "person@example.com and user_19; no other subject is linked",
    }]))
    assert Ledger._extract_ownership(ds) == {
        "object_19": {
            "ownership": "ONLY_SUBJECT",
            "object": "Attachment catalog",
            "file": "delivery_confirmation_19.pdf",
            "email": "person@example.com",
            "user_id": "user_19",
        }
    }
