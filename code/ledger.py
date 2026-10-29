"""Evidence ledger with content-addressed on-disk reuse."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

from identity import resolve
from parsers import Fact, parse_file
from usage import LLMClient

LOGGER = logging.getLogger(__name__)
_CACHE_VERSION = 5
ANCHOR_WINDOW_MINUTES = 45
_OWNERSHIP_RE = re.compile(
    r"(?P<object>[^()]+?)\s*\((?P<file>[^()]*)\)\s+belongs only to\s+"
    r"(?P<email>[^\s;]+)\s+and\s+(?P<user_id>[^;]+);\s*no other subject is linked",
    re.IGNORECASE,
)


class Ledger:
    """Parsed evidence facts and per-file snapshot scopes."""

    def __init__(self, facts: list[Fact], scopes_by_file: dict[str, dict[str, datetime]],
                 *, cache_hit: bool = False, build_seconds: float = 0.0,
                 single_subject_files: set[str] | frozenset[str] = frozenset(),
                 subjects_by_file: dict[str, set[str] | frozenset[str]] | None = None,
                 ownership_by_resource: dict[str, dict[str, str]] | None = None) -> None:
        self.facts = facts
        self.scopes_by_file = scopes_by_file
        self.cache_hit = cache_hit
        self.build_seconds = build_seconds
        self.single_subject_files = frozenset(single_subject_files)
        self.subjects_by_file = {key: frozenset(values) for key, values in (subjects_by_file or {}).items()}
        self.ownership_by_resource = ownership_by_resource or {}
        self.by_file: dict[str, list[Fact]] = {}
        for fact in facts:
            self.by_file.setdefault(fact.file_id, []).append(fact)

    @staticmethod
    def _fingerprint(ds: Any, dataset_dir: Path, client: Any) -> str:
        digest = hashlib.sha256()
        digest.update(f"ledger-v{_CACHE_VERSION}".encode())
        digest.update((dataset_dir / "sample_output.csv").read_bytes())
        for filename in ("user_identities.csv", "user_audit_log.csv", "system_activity.csv"):
            source_data = dataset_dir / filename
            if source_data.exists():
                digest.update(filename.encode())
                digest.update(source_data.read_bytes())
        models = getattr(client, "gemini_models", ())
        digest.update(json.dumps(list(models), sort_keys=True).encode())
        for source in sorted((Path(__file__).parent / "parsers").glob("*.py")):
            digest.update(source.name.encode())
            digest.update(source.read_bytes())
        for source in (Path(__file__), Path(__file__).with_name("identity.py")):
            digest.update(source.name.encode())
            digest.update(source.read_bytes())
        for row in ds.evidence_files.sort_values("file_id").itertuples(index=False):
            relative = str(row.file_path)
            path = Path(relative)
            path = path if path.is_absolute() else dataset_dir / path
            digest.update(str(row.file_id).encode())
            digest.update(relative.encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()

    @staticmethod
    def _fact_to_json(fact: Fact) -> dict[str, Any]:
        return {
            "file_id": fact.file_id,
            "observed_at": fact.observed_at.isoformat(),
            "system_id": fact.system_id,
            "resource_id": fact.resource_id,
            "category": fact.category,
            "state": fact.state,
            "emails": list(fact.emails),
            "hashes": list(fact.hashes),
            "phones": list(fact.phones),
            "user_ids": list(fact.user_ids),
            "names": list(fact.names),
            "topology": fact.topology,
            "source_kind": fact.source_kind,
            "raw_ref": fact.raw_ref,
            "flags": list(fact.flags),
        }

    @staticmethod
    def _fact_from_json(row: dict[str, Any]) -> Fact:
        observed = datetime.fromisoformat(row["observed_at"])
        return Fact(
            file_id=row["file_id"], observed_at=observed,
            system_id=row["system_id"], resource_id=row["resource_id"],
            category=row["category"], state=row["state"],
            emails=tuple(row.get("emails", ())), hashes=tuple(row.get("hashes", ())),
            phones=tuple(row.get("phones", ())), user_ids=tuple(row.get("user_ids", ())),
            names=tuple(row.get("names", ())), topology=row.get("topology"),
            source_kind=row["source_kind"], raw_ref=row["raw_ref"],
            flags=tuple(row.get("flags", ())),
        )

    @staticmethod
    def _fact_subjects(fact: Fact, ds: Any, captured_at: Any) -> set[str]:
        users: set[str] = set()

        def lookup(method_name: str, value: str) -> Any:
            method = getattr(ds, method_name, None)
            return method(value) if callable(method) else pd.DataFrame()

        def add_rows(rows: Any) -> None:
            if "user_id" not in rows:
                return
            for value in rows["user_id"]:
                text = str(value).strip()
                if text and text.lower() not in {"nan", "none", "null"}:
                    users.add(text.lower())

        for value in fact.user_ids:
            add_rows(lookup("identities_by_user_id", value))
            if not users and str(value).strip().lower().startswith("user_"):
                users.add(str(value).strip().lower())
        for value in fact.emails:
            if all(hasattr(ds, name) for name in ("user_identities", "user_audit_log", "system_activity")):
                resolved = resolve(value, ds, captured_at, limit_history_to_audit_at=False)
                users.update(item.lower() for item in resolved.user_ids)
            add_rows(lookup("identities_by_email", value))
        for value in fact.hashes:
            add_rows(lookup("identities_by_hash", value))
        for value in fact.phones:
            add_rows(lookup("identities_by_phone", value))

        # Historical-only hashes and phones can still identify a single owner.
        audit = getattr(ds, "user_audit_log", pd.DataFrame())
        if not audit.empty and {"field_name", "old_value", "new_value", "user_id"}.issubset(audit.columns):
            for field, values in (("email_hash", fact.hashes), ("phone", fact.phones)):
                targets = {str(value).strip().lower() for value in values if str(value).strip()}
                if not targets:
                    continue
                subset = audit.loc[audit.field_name.astype(str).str.lower().eq(field)]
                for _, row in subset.iterrows():
                    old = str(row.old_value).strip().lower()
                    new = str(row.new_value).strip().lower()
                    if old in targets or new in targets:
                        user_id = str(row.user_id).strip().lower()
                        if user_id and user_id not in {"nan", "none", "null"}:
                            users.add(user_id)
        return users

    @classmethod
    def _derive_subject_metadata(cls, ds: Any, facts: list[Fact]) -> tuple[dict[str, set[str]], set[str]]:
        capture_by_file = {
            str(row.file_id): getattr(row, "captured_at", None)
            for row in ds.evidence_files.itertuples(index=False)
        }
        file_facts: dict[str, list[Fact]] = {}
        for fact in facts:
            file_facts.setdefault(fact.file_id, []).append(fact)
        subjects_by_file: dict[str, set[str]] = {}
        single_subject_files: set[str] = set()
        for file_id, group in file_facts.items():
            per_fact = [cls._fact_subjects(fact, ds, capture_by_file.get(file_id)) for fact in group]
            subjects = set().union(*per_fact) if per_fact else set()
            subjects_by_file[file_id] = subjects
            kinds = {fact.source_kind for fact in group}
            if kinds == {"image"} and len(subjects) <= 1:
                # One screenshot is one UI record even when OCR misses its identity fields.
                single_subject_files.add(file_id)
            elif kinds == {"pdf"} and len(subjects) == 1 and all(len(owners) == 1 for owners in per_fact):
                single_subject_files.add(file_id)
            elif kinds.issubset({"json", "log"}) and per_fact and all(len(owners) == 1 for owners in per_fact):
                if len(subjects) == 1:
                    single_subject_files.add(file_id)
        return subjects_by_file, single_subject_files

    @staticmethod
    def _extract_ownership(ds: Any) -> dict[str, dict[str, str]]:
        ownership: dict[str, dict[str, str]] = {}
        activity = getattr(ds, "system_activity", pd.DataFrame())
        if not {"event_type", "resource_id", "details"}.issubset(activity.columns):
            return ownership
        rows = activity.loc[activity.event_type.astype(str).str.lower().eq("link_resource_identity")]
        for _, row in rows.iterrows():
            match = _OWNERSHIP_RE.search(str(row.get("details") or ""))
            resource_id = str(row.get("resource_id") or "").strip()
            if not match or not resource_id:
                continue
            ownership[resource_id.lower()] = {
                "ownership": "ONLY_SUBJECT",
                "object": match.group("object").strip(),
                "file": match.group("file").strip(),
                "email": match.group("email").strip().lower(),
                "user_id": match.group("user_id").strip(),
            }
        return ownership

    @classmethod
    def build(cls, ds: Any, dataset_dir: str | Path, llm: Any = None,
              cache_dir: str | Path | None = None) -> "Ledger":
        """Parse all manifest evidence once, then reuse the content-addressed cache."""
        started = time.perf_counter()
        root = Path(dataset_dir).expanduser().resolve()
        client = llm if llm is not None else LLMClient()
        cache_root = Path(cache_dir) if cache_dir is not None else root.parent / ".cache" / "ledger"
        fingerprint = cls._fingerprint(ds, root, client)
        cache_path = cache_root / f"ledger-{fingerprint}.json"
        try:
            saved = json.loads(cache_path.read_text(encoding="utf-8"))
            if saved.get("fingerprint") == fingerprint and saved.get("version") == _CACHE_VERSION:
                facts = [cls._fact_from_json(item) for item in saved.get("facts", [])]
                scopes = {
                    file_id: {system: datetime.fromisoformat(timestamp)
                              for system, timestamp in file_scope.items()}
                    for file_id, file_scope in saved.get("scopes_by_file", {}).items()
                }
                subjects = {key: set(values) for key, values in saved.get("subjects_by_file", {}).items()}
                return cls(facts, scopes, cache_hit=True,
                           build_seconds=time.perf_counter() - started,
                           single_subject_files=set(saved.get("single_subject_files", ())),
                           subjects_by_file=subjects,
                           ownership_by_resource=saved.get("ownership_by_resource", {}))
        except (OSError, ValueError, KeyError, TypeError):
            pass

        facts: list[Fact] = []
        scopes: dict[str, dict[str, datetime]] = {}
        for _, row in ds.evidence_files.iterrows():
            parsed, scope = parse_file(row, root, llm=client)
            file_id = str(row["file_id"])
            facts.extend(
                replace(fact, flags=tuple(sorted(set(fact.flags) | {"CONTEXT_ONLY"})))
                if fact.category == "LEGAL_HOLD_RECORD" and "CONTEXT_ONLY" not in fact.flags
                else fact
                for fact in parsed
            )
            scopes[file_id] = scope

        subjects, single_subject_files = cls._derive_subject_metadata(ds, facts)
        ownership = cls._extract_ownership(ds)
        ledger = cls(facts, scopes, cache_hit=False,
                     single_subject_files=single_subject_files,
                     subjects_by_file=subjects,
                     ownership_by_resource=ownership,
                     build_seconds=time.perf_counter() - started)
        payload = {
            "version": _CACHE_VERSION,
            "fingerprint": fingerprint,
            "facts": [cls._fact_to_json(fact) for fact in facts],
            "scopes_by_file": {
                file_id: {system: timestamp.isoformat() for system, timestamp in scope.items()}
                for file_id, scope in scopes.items()
            },
            "subjects_by_file": {key: sorted(values) for key, values in subjects.items()},
            "single_subject_files": sorted(single_subject_files),
            "ownership_by_resource": ownership,
        }
        try:
            cache_root.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(f".{time.time_ns()}.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temporary.replace(cache_path)
        except OSError as exc:
            LOGGER.warning("Could not write ledger cache (%s)", type(exc).__name__)
        return ledger

    def query(self, identity: Any) -> list[Fact]:
        """Return facts linked to any current/historical identity or linked resource."""
        emails = {value.strip().lower() for value in getattr(identity, "emails", ()) if value}
        hashes = {value.strip().lower() for value in getattr(identity, "hashes", ()) if value}
        phones = {value.strip() for value in getattr(identity, "phones", ()) if value}
        user_ids = {value.strip().lower() for value in getattr(identity, "user_ids", ()) if value}
        linked = {value.strip().lower() for value in getattr(identity, "linked_resources", ()) if value}
        return [fact for fact in self.facts if (
            bool({v.lower() for v in fact.emails} & emails)
            or bool({v.lower() for v in fact.hashes} & hashes)
            or bool(set(fact.phones) & phones)
            or bool({v.lower() for v in fact.user_ids} & user_ids)
            or fact.resource_id.lower() in linked
        )]

    @staticmethod
    def anchor_files(ds: Any, audit_at: Any,
                     window_minutes: int = ANCHOR_WINDOW_MINUTES) -> set[str]:
        """Evidence captured in (audit_at - window, audit_at]."""
        cutoff = pd.to_datetime(audit_at, errors="coerce", utc=True)
        if pd.isna(cutoff):
            return set()
        lower = cutoff - pd.Timedelta(minutes=window_minutes)
        captures = pd.to_datetime(ds.evidence_files.captured_at, errors="coerce", utc=True)
        mask = captures.notna() & (captures > lower) & (captures <= cutoff)
        return set(ds.evidence_files.loc[mask, "file_id"].astype(str))

    def query_for_case(self, identity: Any, ds: Any, audit_at: Any,
                       window_minutes: int = ANCHOR_WINDOW_MINUTES) -> list[Fact]:
        """Identity query plus safe single-subject time anchors, marked on returned Facts."""
        cutoff = pd.to_datetime(audit_at, errors="coerce", utc=True)
        if pd.isna(cutoff):
            return []
        matched = [fact for fact in self.query(identity)
                   if pd.to_datetime(fact.observed_at, errors="coerce", utc=True) <= cutoff]
        result = list(matched)
        seen = {(fact.file_id, fact.system_id, fact.resource_id, fact.category, fact.state)
                for fact in result}
        identity_users = {str(value).strip().lower() for value in getattr(identity, "user_ids", ()) if value}
        for file_id in self.anchor_files(ds, audit_at, window_minutes):
            if file_id not in self.single_subject_files:
                continue
            subjects = set(self.subjects_by_file.get(file_id, ()))
            # When extracted identifiers establish a different subject, timestamp alone cannot bind it.
            if subjects and not subjects.issubset(identity_users):
                continue
            for fact in self.by_file.get(file_id, ()):
                if not fact.system_id or fact.system_id == "unknown_system":
                    continue
                key = (fact.file_id, fact.system_id, fact.resource_id, fact.category, fact.state)
                if key in seen:
                    continue
                result.append(replace(fact, flags=tuple(sorted(set(fact.flags) | {"BOUND_BY_TIME"}))))
                seen.add(key)
        return result

    def step_candidate_facts(self, identity: Any, ds: Any, audit_at: Any,
                             window_minutes: int = ANCHOR_WINDOW_MINUTES) -> list[Fact]:
        """Exclude retained legal-hold context from deletion/remediation step candidates."""
        return [fact for fact in self.query_for_case(identity, ds, audit_at, window_minutes)
                if fact.category != "LEGAL_HOLD_RECORD"]
