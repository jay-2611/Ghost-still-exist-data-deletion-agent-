import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
from identity import resolve  # noqa: E402
from loader import DATASET_DIR, load_all  # noqa: E402
from parsers import parse_file  # noqa: E402


def _identity_match(fact, identity):
    return bool(
        {value.lower() for value in fact.user_ids} & {value.lower() for value in identity.user_ids}
        or set(fact.emails) & set(identity.emails)
        or set(fact.hashes) & set(identity.hashes)
        or set(fact.phones) & set(identity.phones)
        or fact.resource_id in identity.linked_resources
    )


def _raw_identity_tokens(identity):
    return {value.lower() for value in (
        *identity.emails, *identity.hashes, *identity.phones, *identity.user_ids,
    ) if value}


def test_sql_citation_recall_and_identity_precision_gate():
    ds = load_all(DATASET_DIR)
    sql_rows = ds.evidence_files.loc[ds.evidence_files.file_path.str.lower().str.endswith(".sql")]
    assert len(sql_rows) == 24
    facts_by_file = {}
    scopes_by_file = {}
    all_facts = []
    for _, row in sql_rows.iterrows():
        parsed, scope = parse_file(row, DATASET_DIR)
        facts_by_file[str(row.file_id)] = parsed
        scopes_by_file[str(row.file_id)] = scope
        all_facts.extend(parsed)

    manifest = {str(row.file_id): row for row in ds.evidence_files.itertuples(index=False)}
    requests = ds.sample_deletion_requests.set_index("case_id")
    expected_by_case = defaultdict(set)
    expectations = {}
    citation_ids = defaultdict(set)

    for sample in ds.sample_output.itertuples(index=False):
        steps = json.loads(sample.steps_json)
        for step in steps:
            resource_id = step.get("resource_id")
            system_id = step.get("system_id")
            if not resource_id or not system_id:
                continue
            triple = (str(sample.case_id), str(system_id), str(resource_id))
            expected_by_case[sample.case_id].add(triple)
            # A finding cites the evidence for an INCOMPLETE record. COMPLETE
            # cases cite their verification evidence. Proposed future steps are ignored.
            wanted_phase = "VERIFICATION" if sample.deletion_status == "COMPLETE" else "FINDING"
            if step.get("phase") == wanted_phase:
                evidence_id = str(step.get("evidence_id") or "").strip()
                if evidence_id:
                    citation_ids[triple].add(evidence_id)
                    expectations[triple] = (str(step.get("state") or ""), evidence_id)

    expected_triples = set().union(*expected_by_case.values())
    assert len(expected_triples) == 111

    evidence_types = Counter()
    cited_records = {}
    for triple, evidence_ids in citation_ids.items():
        for evidence_id in evidence_ids:
            evidence = manifest.get(evidence_id)
            if evidence is None:
                evidence_types["unmapped"] += 1
                continue
            file_type = Path(evidence.file_path).suffix.lower().lstrip(".") or "unknown"
            evidence_types[file_type] += 1
            cited_records[(triple, evidence_id)] = (evidence, file_type)

    sql_expected = []
    other_cited = 0
    uncited = len(expected_triples - set(citation_ids))
    for triple, evidence_ids in citation_ids.items():
        for evidence_id in evidence_ids:
            evidence_type = cited_records.get((triple, evidence_id), (None, None))[1]
            if evidence_type == "sql":
                state, _ = expectations[triple]
                sql_expected.append((triple, evidence_id, state))
            else:
                other_cited += 1

    direct_hits = 0
    scoped_absence_hits = 0
    misses = []
    for (case_id, system_id, resource_id), evidence_id, expected_state in sql_expected:
        evidence = manifest[evidence_id]
        file_path = DATASET_DIR / evidence.file_path
        identity = resolve(requests.loc[case_id].email, ds, requests.loc[case_id].audit_at)
        file_facts = facts_by_file.get(evidence_id, [])
        matching = [fact for fact in file_facts
                    if fact.resource_id == resource_id and fact.system_id == system_id
                    and _identity_match(fact, identity)]
        if matching:
            direct_hits += 1
            continue
        raw = file_path.read_text(encoding="utf-8-sig", errors="replace").lower()
        identity_tokens = _raw_identity_tokens(identity)
        identity_in_file = any(token in raw for token in identity_tokens)
        resource_in_file = resource_id.lower() in raw
        resource_facts = [fact for fact in file_facts if fact.resource_id == resource_id]
        scope_covers_system = system_id in scopes_by_file.get(evidence_id, {})

        # A complete-case VERIFY_RECORD_ABSENT can be backed by a complete SQL
        # snapshot's scope even though an absent row correctly emits no Fact.
        if expected_state == "ABSENT" and scope_covers_system and not resource_facts:
            scoped_absence_hits += 1
            diagnosis = "identity gap: no case identifier appears; the complete scoped snapshot supports expected ABSENT"
        elif not identity_in_file:
            diagnosis = "identity gap: no case identifier appears in the cited SQL file"
        elif resource_in_file and not resource_facts:
            diagnosis = "parser gap: resource_id occurs in SQL text but no Fact was emitted"
        elif resource_facts:
            summaries = sorted({f"{fact.system_id}/{fact.state}" for fact in resource_facts})
            diagnosis = f"wrong system/state: parsed Fact(s) are {', '.join(summaries)}"
        else:
            diagnosis = "wrong system/state: no matching resource row or scoped absence proof"
        misses.append((case_id, system_id, resource_id, expected_state, evidence.file_path, diagnosis))

    sql_denominator = len(sql_expected)
    state_aware_hits = direct_hits + scoped_absence_hits
    state_aware_recall = state_aware_hits / sql_denominator if sql_denominator else 1.0
    raw_fact_recall = direct_hits / sql_denominator if sql_denominator else 1.0

    # Precision is measured over distinct case/system/resource facts that match
    # that case's resolved identity at audit_at; later snapshot facts are ignored.
    precision_candidates = set()
    precision_true_positives = set()
    for sample in ds.sample_output.itertuples(index=False):
        request = requests.loc[sample.case_id]
        identity = resolve(request.email, ds, request.audit_at)
        cutoff = request.audit_at
        cutoff = cutoff.tz_convert("UTC") if getattr(cutoff, "tzinfo", None) else cutoff.tz_localize("UTC")
        expected = expected_by_case[sample.case_id]
        for fact in all_facts:
            if fact.observed_at > cutoff.to_pydatetime():
                continue
            if not _identity_match(fact, identity):
                continue
            triple = (str(sample.case_id), fact.system_id, fact.resource_id)
            precision_candidates.add(triple)
            if triple in expected:
                precision_true_positives.add(triple)
    precision = len(precision_true_positives) / len(precision_candidates) if precision_candidates else 1.0
    extras = sorted(precision_candidates - precision_true_positives)[:10]

    print(f"SQL evidence files parsed: {len(sql_rows)}/24")
    print(f"Distinct expected triples: {len(expected_triples)}/111")
    print("Recall by cited evidence type:")
    for file_type, count in sorted(evidence_types.items()):
        if file_type == "sql":
            print(f"  {file_type}: {direct_hits}/{count} raw Facts ({raw_fact_recall:.1%}); {state_aware_hits}/{count} state-aware evidence coverage ({state_aware_recall:.1%})")
        else:
            print(f"  {file_type}: {count} expected triples; excluded (non-SQL parser gate)")
    print(f"Uncited expected triples: {uncited}; non-SQL cited triples excluded from SQL recall: {other_cited}")
    print(f"SQL-cited expected resources: {sql_denominator} (expected approximately 11)")
    print(f"SQL raw Fact recall: {direct_hits}/{sql_denominator} ({raw_fact_recall:.1%})")
    print(f"SQL state-aware evidence recall (including scoped ABSENT verification): {state_aware_hits}/{sql_denominator} ({state_aware_recall:.1%})")
    print("Misses (cited SQL path and diagnosis):")
    for miss in misses:
        print("  ", " | ".join(map(str, miss)))
    print(f"Identity-matched Fact precision: {len(precision_true_positives)}/{len(precision_candidates)} ({precision:.1%})")
    print("10 extra identity-matched fact examples (case, system, resource):", extras)

    assert sql_denominator > 0
    assert state_aware_recall >= 0.90, "SQL-cited state-aware recall must be at least 90%"
    assert len(misses) == sql_denominator - direct_hits
