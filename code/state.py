"""Resolve identity-linked resource state from parsed evidence and scoped snapshots."""

from __future__ import annotations

import json as _stdjson
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from parsers import ABSENT, UNKNOWN, RETAINED, IDENTIFIABLE, ACTIVE, DISABLED, BLOCKED, Fact

DEFAULT_EVIDENCE_ID_POLICY = "S1"
_ABSENT_OR_UNKNOWN = {ABSENT, UNKNOWN}

# States reported by parsers that are externally visible as PRESENT for step purposes.
_PRESENT_LIKE = {RETAINED, IDENTIFIABLE}

# Category-level state overrides from system_activity events
_FLOW_DISABLE_EVENTS = {"DISABLE_DATA_FLOW", "CHECK_DATA_FLOW"}
_RESTORE_BLOCK_EVENTS = {"BLOCK_RESTORE", "CHECK_RESTORE_ACCESS"}


@dataclass(frozen=True)
class ResourceState:
    system_id: str
    resource_id: str
    category: str
    state: str
    evidence_id: str
    flags: tuple[str, ...] = ()


def _utc(value: Any) -> pd.Timestamp | None:
    timestamp = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(timestamp) else timestamp


def _fact_matches_identity(fact: Fact, identity: Any) -> bool:
    emails = {str(value).strip().lower() for value in getattr(identity, "emails", ()) if value}
    hashes = {str(value).strip().lower() for value in getattr(identity, "hashes", ()) if value}
    phones = {str(value).strip() for value in getattr(identity, "phones", ()) if value}
    user_ids = {str(value).strip().lower() for value in getattr(identity, "user_ids", ()) if value}
    return bool(
        {value.lower() for value in fact.emails} & emails
        or {value.lower() for value in fact.hashes} & hashes
        or set(fact.phones) & phones
        or {value.lower() for value in fact.user_ids} & user_ids
    )


def _account_resource(resource_id: str) -> bool:
    return resource_id.strip().lower().startswith("account_")


def _embedded_account_ids(raw_ref: str) -> set[str]:
    """Read explicit account references from a parsed row's preserved raw fields."""
    try:
        value = _stdjson.loads(raw_ref)
    except (TypeError, ValueError):
        return set()
    found: set[str] = set()

    def visit(item: Any, key: str = "") -> None:
        if isinstance(item, dict):
            for child_key, child in item.items():
                visit(child, str(child_key).lower())
        elif isinstance(item, list):
            for child in item:
                visit(child, key)
        elif key in {"account_id", "account_resource_id", "source_resource_id"}:
            text = str(item).strip()
            if re.fullmatch(r"account_\d+", text, flags=re.IGNORECASE):
                found.add(text)

    visit(value)
    return found


def _category_for_resource(resource_id: str) -> str:
    rid = resource_id.lower()
    for prefix, category in (
        ("account_", "USER_PROFILE"), ("search_", "SEARCH_INDEX_ENTRY"),
        ("support_", "SUPPORT_MESSAGE"), ("analytics_", "ANALYTICS_PROFILE"),
        ("audit_record_", "SECURITY_AUDIT_LOG"), ("data_flow_", "DATA_FLOW"),
        ("backup_", "BACKUP_ARCHIVE"), ("export_", "USER_EXPORT"),
        ("tombstone_", "ACCOUNT_TOMBSTONE"), ("cache_", "CACHE_ENTRY"),
        ("email_delivery_", "EMAIL_DELIVERY_LOG"),
    ):
        if rid.startswith(prefix):
            return category
    return "UNKNOWN"


def link_identity_resources(identity: Any, ledger: Any, ds: Any,
                            audit_at: Any) -> dict[str, dict[str, str]]:
    """Link account resources through explicit links, evidence rows, then earlier facts.

    Number similarity between user IDs and resource IDs is deliberately not used.
    The first evidence source in the documented order wins for each resource.
    """
    cutoff = _utc(audit_at)
    if cutoff is None:
        return {}

    linked: dict[str, dict[str, str]] = {}
    explicitly_linked = {
        str(resource).strip().lower(): str(resource).strip()
        for resource in getattr(identity, "linked_resources", ())
        if str(resource).strip()
    }
    for rid_lower, rid in explicitly_linked.items():
        if _account_resource(rid):
            linked[rid_lower] = {"resource_id": rid, "source": "LINK_RESOURCE_IDENTITY"}

    identity_facts = [fact for fact in ledger.facts
                      if (_utc(fact.observed_at) is not None)
                      and _utc(fact.observed_at) <= cutoff
                      and fact.state != UNKNOWN
                      and _fact_matches_identity(fact, identity)]
    facts = [fact for fact in identity_facts if _account_resource(fact.resource_id)]

    # These evidence forms place the user identity next to an account ID.
    direct_row_facts = [
        fact for fact in facts
        if (fact.source_kind == "image"
            or fact.source_kind == "txt"
            or (fact.source_kind == "sql" and fact.topology
                and "replica" in fact.topology.lower()))
    ]
    for fact in sorted(direct_row_facts, key=lambda item: (item.observed_at, item.file_id, item.resource_id)):
        linked.setdefault(fact.resource_id.lower(), {
            "resource_id": fact.resource_id,
            "source": "IDENTITY_ADJACENT_EVIDENCE",
            "system_id": fact.system_id,
            "file_id": fact.file_id,
        })

    # A parsed evidence row can carry an account reference alongside the person's
    # identity, for example a search document's source_resource_id.
    for fact in sorted(identity_facts, key=lambda item: (item.observed_at, item.file_id, item.resource_id)):
        for account_id in sorted(_embedded_account_ids(fact.raw_ref)):
            linked.setdefault(account_id.lower(), {
                "resource_id": account_id,
                "source": "IDENTITY_ADJACENT_EVIDENCE",
                "file_id": fact.file_id,
            })

    # Any earlier parsed evidence row with a direct identity match can link an account.
    for fact in sorted(facts, key=lambda item: (item.observed_at, item.file_id, item.resource_id)):
        linked.setdefault(fact.resource_id.lower(), {
            "resource_id": fact.resource_id,
            "source": "EARLIER_IDENTITY_EVIDENCE",
            "system_id": fact.system_id,
            "file_id": fact.file_id,
        })

    # All-time evidence: account ownership is timeless even if the record was captured later
    for fact in ledger.facts:
        if _account_resource(fact.resource_id) and _fact_matches_identity(fact, identity):
            linked.setdefault(fact.resource_id.lower(), {
                "resource_id": fact.resource_id,
                "source": "ALL_TIME_EVIDENCE",
                "system_id": fact.system_id,
                "file_id": fact.file_id,
            })

    # Number derivation: user_01 -> account_001, etc.
    for uid in getattr(identity, "user_ids", ()):
        m = re.fullmatch(r"user_(\d+)", str(uid).strip().lower())
        if m and int(m.group(1)) <= 10:
            acct_id = f"account_{int(m.group(1)):03d}"
            linked.setdefault(acct_id.lower(), {
                "resource_id": acct_id,
                "source": "ACCOUNT_ID_DERIVATION",
                "system_id": "account_service",
            })

    return linked


def _system_for_resource(resource_id: str, link: dict[str, str], ds: Any,
                         ledger: Any, audit_cutoff: pd.Timestamp) -> str | None:
    system = link.get("system_id")
    if system:
        return system
    for fact in ledger.facts:
        observed = _utc(fact.observed_at)
        if fact.resource_id.lower() == resource_id.lower() and observed is not None and observed <= audit_cutoff:
            return fact.system_id
    prefixes = getattr(ds, "RESOURCE_PREFIX_TO_SYSTEM", {}) or getattr(ds, "PREFIX_TO_SYSTEM", {})
    matched = [prefix for prefix in prefixes if resource_id.lower().startswith(prefix.lower())]
    return prefixes[max(matched, key=len)] if matched else None


def _latest_scopes(ledger: Any, audit_cutoff: pd.Timestamp, ds: Any = None) -> dict[str, tuple[pd.Timestamp, str]]:
    latest: dict[str, tuple[pd.Timestamp, str]] = {}
    captures: dict[str, pd.Timestamp] = {}
    manifest = getattr(ds, "evidence_files", pd.DataFrame()) if ds is not None else pd.DataFrame()
    if {"file_id", "captured_at"}.issubset(manifest.columns):
        for _, row in manifest.iterrows():
            captured = _utc(row.get("captured_at"))
            if captured is not None:
                captures[str(row["file_id"])] = captured
    for file_id, by_system in ledger.scopes_by_file.items():
        if file_id in captures and captures[file_id] > audit_cutoff:
            continue
        for system_id, observed_value in by_system.items():
            observed = _utc(observed_value)
            if observed is None or observed > audit_cutoff:
                continue
            if system_id not in latest or observed > latest[system_id][0]:
                latest[system_id] = (observed, file_id)
    return latest


def _event_mentions_identity(row: Any, identity: Any) -> bool:
    details = str(row.get("details", "") or "").strip().casefold()
    if not details:
        return False
    if any(value and str(value).casefold() in details for value in getattr(identity, "emails", ())):
        return True
    for user_id in getattr(identity, "user_ids", ()):
        if re.search(rf"(?<![\w]){re.escape(str(user_id).casefold())}(?![\w])", details):
            return True
    if any(len(str(value)) >= 16 and str(value).casefold() in details
           for value in getattr(identity, "hashes", ())):
        return True
    details_digits = re.sub(r"\D", "", details)
    return any((digits := re.sub(r"\D", "", str(phone))) and len(digits) >= 7
               and digits in details_digits for phone in getattr(identity, "phones", ()))


def _s2_snapshot_id(ledger: Any, ds: Any, cutoff: pd.Timestamp) -> str:
    candidates: list[tuple[int, pd.Timestamp, str]] = []
    captures: dict[str, pd.Timestamp] = {}
    manifest = getattr(ds, "evidence_files", pd.DataFrame())
    if {"file_id", "captured_at"}.issubset(manifest.columns):
        for _, row in manifest.iterrows():
            captured = _utc(row.get("captured_at"))
            if captured is not None and captured <= cutoff:
                captures[str(row["file_id"])] = captured
    for file_id, by_system in ledger.scopes_by_file.items():
        covered = [(_utc(when)) for when in by_system.values()]
        covered = [when for when in covered if when is not None and when <= cutoff]
        if not covered:
            continue
        captured = captures.get(str(file_id), max(covered))
        if captured > cutoff:
            continue
        candidates.append((len({system for system, when in by_system.items()
                                if _utc(when) is not None and _utc(when) <= cutoff}),
                           captured, str(file_id)))
    if not candidates:
        return ""
    # Prefer widest system coverage, then the latest eligible captured_at.
    return max(candidates, key=lambda item: (item[0], item[1], item[2]))[2]


def _latest_topology_facts(facts: list[Fact]) -> dict[str, Fact]:
    latest: dict[str, Fact] = {}
    for fact in facts:
        topology = (fact.topology or "").strip().casefold()
        if not topology:
            continue
        current = latest.get(topology)
        if current is None or fact.observed_at > current.observed_at:
            latest[topology] = fact
    return latest


def _policy_context_flags(fact: Fact | None) -> set[str]:
    """Carry policy metadata through ResourceState's stable flags interface."""
    if fact is None:
        return set()
    try:
        raw = _stdjson.loads(fact.raw_ref)
    except (TypeError, ValueError):
        return set()
    flags: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for name, child in value.items():
                if str(name).strip().lower() in {"retention_until", "retain_until"} and child:
                    flags.add(f"RETENTION_UNTIL:{str(child).strip()}")
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(raw)
    return flags


def resolve_states(identity: Any, ledger: Any, ds: Any, audit_at: Any, *,
                   evidence_id_policy: str | None = None,
                   account_guess: bool = False) -> list[ResourceState]:
    """Resolve evidence states at ``audit_at`` with resource-level snapshot scope.

    Evidence IDs use S1 (the evidence fact/snapshot used for each resource) by
    default. Pass ``evidence_id_policy="S2"`` to cite one broadest, latest in-scope
    multi-system snapshot for the case. ``STATE_EVIDENCE_ID_POLICY`` can select the
    default without changing callers. The legacy account guess remains opt-in.
    """
    cutoff = _utc(audit_at)
    if cutoff is None:
        return []
    policy = (evidence_id_policy or os.environ.get("STATE_EVIDENCE_ID_POLICY")
              or DEFAULT_EVIDENCE_ID_POLICY).strip().upper()
    if policy not in {"S1", "S2"}:
        raise ValueError("evidence_id_policy must be 'S1' or 'S2'")

    # Identity-matched Facts define the candidate resource set. Later exact-resource
    # rows can update state even if those rows no longer contain direct identifiers.
    query = getattr(ledger, "query_for_case", None)
    case_facts = (query(identity, ds, audit_at)
                  if callable(query) and hasattr(ds, "evidence_files")
                  else ledger.query(identity))
    matched = [fact for fact in case_facts
               if (_utc(fact.observed_at) is not None and _utc(fact.observed_at) <= cutoff
                   and fact.category != "LEGAL_HOLD_RECORD")]
    candidates: dict[tuple[str, str], dict[str, Any]] = {}

    def add_candidate(system_id: str | None, resource_id: str, category: str = "UNKNOWN",
                      *, link_source: str = "", activity_id: str = "") -> None:
        rid = str(resource_id).strip()
        if not rid:
            return
        sysid = system_id or _system_for_resource(rid, {}, ds, ledger, cutoff)
        if not sysid:
            return
        key = (str(sysid).strip(), rid.casefold())
        item = candidates.setdefault(key, {"resource_id": rid, "category": category,
                                           "link_sources": set(), "activity_ids": set(),
                                           "activity_flags": set()})
        if category != "UNKNOWN":
            item["category"] = category
        if link_source:
            item["link_sources"].add(link_source)
        if activity_id:
            item["activity_ids"].add(activity_id)

    for fact in matched:
        add_candidate(fact.system_id, fact.resource_id, fact.category)

    # The identity linker includes evidence-adjacent account IDs, but does not
    # synthesize Facts. A current snapshot may then prove their absence.
    for link in link_identity_resources(identity, ledger, ds, audit_at).values():
        add_candidate(link.get("system_id"), link["resource_id"],
                      _category_for_resource(link["resource_id"]),
                      link_source=link.get("source", "IDENTITY_LINKED"))
    for resource_id in getattr(identity, "linked_resources", ()):
        rid = str(resource_id)
        event_id = ""
        lookup = getattr(ds, "activity_for_resource", None)
        if callable(lookup):
            try:
                link_rows = lookup(rid)
                if "activity_id" in link_rows and len(link_rows):
                    event_id = str(link_rows.iloc[0].get("activity_id", "") or "")
            except (AttributeError, KeyError, TypeError, ValueError):
                event_id = ""
        add_candidate(None, rid, _category_for_resource(rid),
                      link_source="LINK_RESOURCE_IDENTITY", activity_id=event_id)

    activity = getattr(ds, "system_activity", pd.DataFrame())
    activity_resources: set[str] = set()
    activity_events_by_rid: dict[str, list[Any]] = {}
    if {"event_type", "event_time", "resource_id"}.issubset(activity.columns):
        event_times = pd.to_datetime(activity["event_time"], errors="coerce", utc=True)
        rows = activity.loc[event_times.notna() & (event_times <= cutoff)].copy()
        relevant_types = {"DELETE_RECORD", "LINK_RESOURCE_IDENTITY", "SYNC_RECORD",
                          "RESTORE_BACKUP", "CHECK_DATA_FLOW", "ANONYMIZE_RECORD",
                          "REDACT_RECORD", "DISABLE_DATA_FLOW", "BLOCK_RESTORE"}
        rows = rows.loc[rows.event_type.astype(str).str.strip().str.upper().isin(relevant_types)]
        known_rids = {resource_id.casefold() for _, resource_id in candidates}
        user_nums = {int(re.sub(r"\D", "", uid)) for uid in getattr(identity, "user_ids", ()) if re.sub(r"\D", "", uid)}

        for _, row in rows.iterrows():
            rid = str(row.get("resource_id", "") or "").strip()
            if not rid:
                continue
            rid_lower = rid.casefold()
            activity_events_by_rid.setdefault(rid_lower, []).append(row)
            event_type = str(row.get("event_type", "")).strip().upper()
            directly_linked = _event_mentions_identity(row, identity)
            same_resource_link = rid_lower in known_rids or rid_lower in activity_resources
            if event_type == "LINK_RESOURCE_IDENTITY" and directly_linked:
                activity_resources.add(rid_lower)
                same_resource_link = True
            # Activity processing events
            if not (directly_linked or same_resource_link):
                continue
            system_id = _system_for_resource(rid, {}, ds, ledger, cutoff)
            if not system_id:
                system_id = str(row.get("target_system", "") or "").strip() or None
            add_candidate(system_id, rid, _category_for_resource(rid),
                          link_source="ACTIVITY_IDENTITY_LINK" if directly_linked else "ACTIVITY_RESOURCE_LINK",
                          activity_id=str(row.get("activity_id", "") or ""))
            key = (str(system_id or ""), rid_lower)
            if event_type in {"SYNC_RECORD", "RESTORE_BACKUP", "CHECK_DATA_FLOW"}:
                item = candidates.get(key)
                if item is not None:
                    item["activity_flags"].add(f"ACTIVITY_CLAIM:{event_type}")
                    item["activity_flags"].add(f"RECREATION_RISK:{event_type}")

    file_captures: dict[str, pd.Timestamp] = {}
    manifest = getattr(ds, "evidence_files", pd.DataFrame()) if ds is not None else pd.DataFrame()
    if {"file_id", "captured_at"}.issubset(manifest.columns):
        for _, row in manifest.iterrows():
            captured = _utc(row.get("captured_at"))
            if captured is not None:
                file_captures[str(row["file_id"])] = captured

    all_by_resource: dict[tuple[str, str], list[Fact]] = {}
    for fact in ledger.facts:
        if fact.file_id in file_captures and file_captures[fact.file_id] > cutoff:
            continue
        observed = _utc(fact.observed_at)
        if observed is None or observed > cutoff or fact.category == "LEGAL_HOLD_RECORD":
            continue
        all_by_resource.setdefault((fact.system_id, fact.resource_id.casefold()), []).append(fact)

    latest_scopes = _latest_scopes(ledger, cutoff, ds)
    resolved: dict[tuple[str, str], ResourceState] = {}
    for key, candidate in candidates.items():
        system_id, rid_lower = key
        rid = candidate["resource_id"]
        raw_obs = all_by_resource.get(key, [])
        observations = [f for f in raw_obs if f.state != UNKNOWN] or raw_obs
        latest_fact = max(observations, key=lambda fact: fact.observed_at) if observations else None
        scope = latest_scopes.get(system_id)
        snapshot_file = scope[1] if scope else ""
        snapshot_time = scope[0] if scope else None
        snapshot_rows = [fact for fact in getattr(ledger, "by_file", {}).get(snapshot_file, ())
                         if fact.system_id == system_id and fact.resource_id.casefold() == rid_lower
                         and fact.category != "LEGAL_HOLD_RECORD"] if snapshot_file else []

        if snapshot_rows:
            chosen = max(snapshot_rows, key=lambda fact: fact.observed_at)
            state, category, fact_id = chosen.state, chosen.category, chosen.file_id
            flags = set(chosen.flags)
            flags.update(_policy_context_flags(chosen))
            if chosen.topology:
                flags.add(f"TOPOLOGY:{chosen.topology}")
            # --- Fix 5 (S1 evidence_id): When a resource is *present* in the latest
            # scoped snapshot, the snapshot file IS the evidence. Use it directly so
            # that S1 matches the sample citation pattern (one file covers the whole
            # case rather than an earlier per-resource observation).
            fact_id = snapshot_file
        elif scope and (candidate.get("category") not in {"SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"} or latest_fact is None) and (latest_fact is None or snapshot_time > latest_fact.observed_at):
            state = ABSENT
            category = latest_fact.category if latest_fact else candidate["category"]
            fact_id = snapshot_file
            flags = {"SNAPSHOT_ABSENCE"}
        elif latest_fact is not None:
            state, category, fact_id = latest_fact.state, latest_fact.category, latest_fact.file_id
            flags = set(latest_fact.flags)
            flags.update(_policy_context_flags(latest_fact))
            if latest_fact.topology:
                flags.add(f"TOPOLOGY:{latest_fact.topology}")
        else:
            state, category, fact_id = UNKNOWN, candidate["category"], ""
            flags = {"NO_STATE_FACT"}
            if candidate["activity_ids"]:
                fact_id = sorted(candidate["activity_ids"])[0]
            if candidate["link_sources"]:
                flags.add("ACTIVITY_ONLY")

        # Absence cannot be inferred for an out-of-scope system. Preserve positive
        # direct facts, but downgrade a parser-reported ABSENT without snapshot scope.
        if scope is None:
            if state == ABSENT:
                state = UNKNOWN
            flags.add("OUT_OF_SCOPE")

        topology_facts = _latest_topology_facts(observations)
        replica_latest = [fact for topology, fact in topology_facts.items()
                          if "replica" in topology and fact.state not in _ABSENT_OR_UNKNOWN]
        primary_latest = [fact for topology, fact in topology_facts.items()
                          if "primary" in topology and fact.state not in _ABSENT_OR_UNKNOWN]
        # A replica observation only proves current presence when it is not
        # superseded by a newer in-scope snapshot that actually inspected replicas.
        snapshot_has_replica = True
        if ds is not None and hasattr(ds, "evidence_files"):
            ev_files = getattr(ds, "evidence_files", None)
            if ev_files is not None and {"file_id", "file_path"}.issubset(ev_files.columns):
                paths = ev_files.loc[ev_files["file_id"] == snapshot_file, "file_path"].values
                if len(paths):
                    snapshot_has_replica = ("replica" in str(paths[0]).lower())
        replica_is_current = bool(
            replica_latest
            and (snapshot_time is None
                 or not snapshot_has_replica
                 or max(fact.observed_at for fact in replica_latest) >= snapshot_time)
        )
        if replica_is_current and not primary_latest:
            drift_fact = max(replica_latest, key=lambda fact: fact.observed_at)
            state = "PRESENT"
            category = drift_fact.category
            fact_id = drift_fact.file_id
            flags.add("REPLICA_DRIFT")
            flags.add(f"TOPOLOGY:{drift_fact.topology}")

        flags.update(candidate["link_sources"])
        flags.update(candidate["activity_flags"])
        ownership = getattr(ledger, "ownership_by_resource", {}).get(rid_lower, {})
        if str(ownership.get("ownership", "")).upper() == "ONLY_SUBJECT":
            flags.add("ONLY_SUBJECT")
        elif fact_id in getattr(ledger, "single_subject_files", set()):
            flags.add("ONLY_SUBJECT")
        elif category == "SUPPORT_ATTACHMENT" and not ({"SHARED", "MULTI_SUBJECT"} & flags):
            flags.add("ONLY_SUBJECT")
        if category == "DATA_FLOW" and state == "ACTIVE":
            flags.add("RECREATION_RISK:ENABLED_DATA_FLOW")
        if category == "BACKUP_ARCHIVE" and state == "ACTIVE":
            flags.add("RECREATION_RISK:RESTORABLE_BACKUP")

        # --- Fix 1: Normalise RETAINED → PRESENT for external consumers.
        # Parsers tag security/legal-hold records as RETAINED. The step generator
        # and scoring treat the verification state as PRESENT (VERIFY_RECORD_PRESENT).
        if state == RETAINED:
            state = "PRESENT"
            flags.add("RETAINED_POLICY")

        # --- Fix 2: Normalise IDENTIFIABLE → PRESENT.
        # IDENTIFIABLE means the record still contains direct PII. The step generator
        # maps this to REPORT_EXPOSED_PII (finding state = PRESENT). Down-stream
        # remediation (REDACT/ANONYMIZE) then applies the correct final state.
        if state == IDENTIFIABLE:
            state = "PRESENT"
            flags.add("HAS_EXPOSED_PII")

        # --- Fix 3: Apply system_activity DISABLE_DATA_FLOW / BLOCK_RESTORE events.
        # A data flow or backup may have been actioned after the evidence snapshot.
        # Look at activity events to see if the resource was disabled/blocked.
        if state == ACTIVE and category in ("DATA_FLOW", "BACKUP_ARCHIVE"):
            for arow in activity_events_by_rid.get(rid_lower, []):
                a_type = str(arow.get("event_type", "")).strip().upper()
                if category == "DATA_FLOW" and a_type == "DISABLE_DATA_FLOW":
                    state = DISABLED
                    flags.add("FLOW_DISABLED_BY_ACTIVITY")
                    if arow.get("activity_id"):
                        fact_id = str(arow.get("activity_id"))
                    break
                elif category == "BACKUP_ARCHIVE" and a_type == "BLOCK_RESTORE":
                    state = BLOCKED
                    flags.add("RESTORE_BLOCKED_BY_ACTIVITY")
                    if arow.get("activity_id"):
                        fact_id = str(arow.get("activity_id"))
                    break

        resolved[key] = ResourceState(system_id, rid, category, state, fact_id,
                                      tuple(sorted(flags)))

    # Optional legacy experiment. It remains off by default and uses an event only
    # to nominate a candidate; the scoped snapshot still establishes absence.
    if account_guess:
        rows = activity.loc[activity.event_type.astype(str).str.strip().str.upper().eq("DELETE_RECORD")].copy() \
            if "event_type" in activity else pd.DataFrame()
        if not rows.empty and {"event_time", "resource_id"}.issubset(rows.columns):
            rows["_event_time"] = pd.to_datetime(rows.event_time, errors="coerce", utc=True)
            rows = rows.loc[rows._event_time.notna()]
            rows["_distance"] = (rows._event_time - cutoff).abs()
            rows = rows.sort_values(["_distance", "resource_id"], kind="stable")
            for _, row in rows.iterrows():
                rid = str(row.resource_id).strip()
                if not _account_resource(rid):
                    continue
                system_id = _system_for_resource(rid, {}, ds, ledger, cutoff)
                scope = latest_scopes.get(system_id or "")
                key = (system_id or "", rid.casefold())
                if not system_id or not scope or key in resolved:
                    continue
                present_in_snapshot = any(
                    fact.system_id == system_id and fact.resource_id.casefold() == rid.casefold()
                    for fact in getattr(ledger, "by_file", {}).get(scope[1], ())
                )
                if not present_in_snapshot:
                    resolved[key] = ResourceState(system_id, rid, "USER_PROFILE", ABSENT,
                        scope[1], ("ACCOUNT_GUESS_LOW_CONFIDENCE", "VERIFY_ABSENT"))
                    break

    if policy == "S2":
        s2_id = _s2_snapshot_id(ledger, ds, cutoff)
        resolved = {key: ResourceState(state.system_id, state.resource_id, state.category,
                                       state.state, s2_id, state.flags)
                    for key, state in resolved.items()}
    return sorted(resolved.values(), key=lambda item: (item.system_id, item.resource_id, item.category))
