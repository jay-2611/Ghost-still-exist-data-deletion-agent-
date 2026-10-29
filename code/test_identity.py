import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
from identity import resolve  # noqa: E402
from loader import DATASET_DIR, load_all  # noqa: E402


def test_identity_history_modes_and_full_dataset_gate():
    ds = load_all(DATASET_DIR)
    requests = ds.deletion_requests
    as_of_results = []
    all_history_results = []
    audit_resolved = 0
    for row in requests.itertuples(index=False):
        as_of = resolve(row.email, ds, row.audit_at, limit_history_to_audit_at=True)
        all_history = resolve(row.email, ds, row.audit_at, limit_history_to_audit_at=False)
        as_of_results.append(as_of)
        all_history_results.append(all_history)
        audit_resolved += "AUDIT_HISTORY_MATCH" in all_history.flags

    as_of_user_resolved = sum(bool(result.user_ids) for result in as_of_results)
    full_user_resolved = sum(bool(result.user_ids) for result in all_history_results)
    as_of_linked = sum(bool(result.linked_resources) for result in as_of_results)
    full_linked = sum(bool(result.linked_resources) for result in all_history_results)
    cutoff_link_total = sum(len(result.linked_resources) for result in as_of_results)
    full_link_total = sum(len(result.linked_resources) for result in all_history_results)
    history_enriched_cases = sum(
        (cutoff.emails, cutoff.hashes, cutoff.phones, cutoff.linked_resources)
        != (full.emails, full.hashes, full.phones, full.linked_resources)
        for cutoff, full in zip(as_of_results, all_history_results)
    )
    duplicate_emails = requests.email.str.strip().str.lower().value_counts()
    duplicate_request_rows = int(duplicate_emails[duplicate_emails > 1].sum() - len(duplicate_emails[duplicate_emails > 1]))

    print(f"Requests resolved by cutoff history: {as_of_user_resolved}/{len(requests)}")
    print(f"Requests resolved by full history: {full_user_resolved}/{len(requests)}")
    print(f"Requests requiring audit-log email history (full history): {audit_resolved}")
    print(f"Requests with linked resources: cutoff={as_of_linked}, full={full_linked}; linked-resource matches={cutoff_link_total} cutoff vs {full_link_total} full")
    print(f"Requests enriched by post-audit history (identifiers or links): {history_enriched_cases}")
    print(f"Repeated request-email rows beyond first occurrence: {duplicate_request_rows}")

    assert len(requests) == 518
    assert as_of_user_resolved == 518
    assert full_user_resolved == 518
    assert all(result.primary_user_id for result in all_history_results)
    assert duplicate_request_rows == 1


def test_unknown_email_is_unresolved():
    ds = load_all(DATASET_DIR)
    result = resolve(" nobody@example.invalid ", ds, "2026-10-01T00:00:00Z")
    assert result.user_ids == ()
    assert result.flags == frozenset({"UNRESOLVED"})
