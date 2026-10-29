import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = ROOT / "code"
sys.path.insert(0, str(CODE_DIR))
from loader import (CSV_FILES, DATASET_DIR, UNVERIFIED_PREFIXES,
                    activity_target_distribution, load_all)  # noqa: E402


def _write_inputs(root):
    inputs = {
        "deletion_requests": [{"case_id": "1", "email": " Test@Example.com ", "requested_at": "2025-01-01T00:00:00Z"}],
        "sample_deletion_requests": [], "sample_output": [{"steps_json": '[{"resource_id":"account_1","system_id":"accounts"}]'}],
        "user_identities": [{"email": " Test@Example.com ", "email_hash": " ABC ", "phone": " 123 ", "user_id": " U1 "}],
        "user_audit_log": [],
        "system_activity": [{"resource_id": "account_1", "target_system": "accounts", "event_type": "DELETE"}],
        "deletion_rules": [{"category": "USER_PROFILE"}],
        "evidence_files": [{"file_id": "e1", "file_path": "x", "captured_at": "2025-01-02T00:00:00Z"}],
    }
    for name, filename in CSV_FILES.items():
        frame = pd.DataFrame(inputs[name]) if inputs[name] else pd.DataFrame({"_unused": []})
        frame.to_csv(root / filename, index=False)


def test_load_normalizes_and_builds_lookups():
    with tempfile.TemporaryDirectory(dir=CODE_DIR) as temp_dir:
        root = Path(temp_dir)
        _write_inputs(root)
        ds = load_all(root)
        assert ds.deletion_requests.loc[0, "email"] == "test@example.com"
        assert str(ds.deletion_requests.loc[0, "requested_at"].tz) == "UTC"
        assert len(ds.identities_by_email("TEST@example.com")) == 1
        assert len(ds.identities_by_hash("abc")) == 1
        assert len(ds.identities_by_phone("123")) == 1
        assert len(ds.identities_by_user_id("u1")) == 1
        assert len(ds.evidence_by_id("e1")) == 1
        assert len(ds.activity_for_resource("ACCOUNT_1")) == 1
        assert len(ds.activity_by_type("delete")) == 1
        assert len(ds.rules_by_category("user_profile")) == 1
        assert ds.PREFIX_TO_SYSTEM == {"account_": "accounts"}
        assert ds.prefix_system_agreement_rate == 1.0


@pytest.mark.skipif(not DATASET_DIR.exists(), reason="provided dataset directory is absent")
def test_reference_counts_and_print_prefix_gate():
    ds = load_all(DATASET_DIR)
    expected = {
        "deletion_requests": 518, "sample_deletion_requests": 32,
        "sample_output": 32, "user_identities": 850, "user_audit_log": 306,
        "system_activity": 4011, "deletion_rules": 15, "evidence_files": 94,
    }
    actual = {name: len(getattr(ds, name)) for name in expected}
    print("PREFIX_TO_SYSTEM:", ds.PREFIX_TO_SYSTEM)
    print("sample_output prefix step counts:", ds.prefix_step_counts)
    mapped_steps = sum(ds.prefix_step_counts.values())
    print(f"sample_output mapped steps: {mapped_steps}/{ds.sample_output_step_count} ({ds.prefix_system_agreement_rate:.0%})")
    print("UNVERIFIED_PREFIXES:", list(UNVERIFIED_PREFIXES))
    print("system_activity routing distribution (informational only):")
    print(activity_target_distribution(ds.system_activity, tuple(ds.PREFIX_TO_SYSTEM)).to_string(index=False))
    print("Activity target_system is the operation destination; cross-system events describe the operation, not necessarily the resource's home system.")
    print("Example divergence: UPDATE_RECORD support_platform -> search_service is a search-index update; the support_ resource remains homed in support_platform.")
    assert actual == expected
    assert ds.PREFIX_TO_SYSTEM
    assert ds.prefix_system_agreement_rate == 1.0
    assert sum(ds.prefix_step_counts.values()) == ds.sample_output_step_count == 193
    assert len(ds.PREFIX_TO_SYSTEM) == 9
    assert ds.prefix_step_counts == {"account_": 38, "analytics_": 25, "audit_record_": 24, "backup_": 12, "data_flow_": 21, "export_": 6, "search_": 36, "support_": 27, "tombstone_": 4}
    assert UNVERIFIED_PREFIXES == ("legal_hold_", "object_", "marketing_", "cache_", "email_delivery_")
    assert ds.prefix_system_agreement_rate == 1.0




