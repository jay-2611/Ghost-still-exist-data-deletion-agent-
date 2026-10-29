"""Deterministic parser for SQLite-compatible evidence snapshots."""

from __future__ import annotations

import csv
import json as _stdjson
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from loader import RESOURCE_PREFIXES
from parsers import (ACTIVE, ANONYMIZED, BLOCKED, DISABLED, Fact, IDENTIFIABLE,
                     PRESENT, REDACTED, RETAINED, UNKNOWN)


_TABLE_CATEGORIES = {
    "customer_profiles": "USER_PROFILE",
    "customer_search_documents": "SEARCH_INDEX_ENTRY",
    "search_documents_primary": "SEARCH_INDEX_ENTRY",
    "customer_analytics_profiles": "ANALYTICS_PROFILE",
    "support_records": "SUPPORT_MESSAGE",
    "customer_exports": "USER_EXPORT",
    "connector_subscriptions": "DATA_FLOW",
    "backup_restore_entries": "BACKUP_ARCHIVE",
    "security_audit_records": "SECURITY_AUDIT_LOG",
}
_COLLECTION_CATEGORIES = {
    "customer_profiles": "USER_PROFILE",
    "customer_search_documents": "SEARCH_INDEX_ENTRY",
    "customer_analytics_reports": "ANALYTICS_PROFILE",
    "support_conversations": "SUPPORT_MESSAGE",
    "ticket_attachments": "SUPPORT_ATTACHMENT",
    "customer_export_jobs": "USER_EXPORT",
    "connector_configurations": "DATA_FLOW",
    "backup_catalog": "BACKUP_ARCHIVE",
    "security_audit_events": "SECURITY_AUDIT_LOG",
    "deleted_customer_references": "ACCOUNT_TOMBSTONE",
    "retained_order_records": "LEGAL_HOLD_RECORD",
}
_TABLE_SYSTEMS = {
    "customer_profiles": "account_service",
    "customer_search_documents": "search_service",
    "search_documents_primary": "search_service",
    "customer_analytics_profiles": "analytics_platform",
    "support_records": "support_platform",
    "customer_exports": "export_service",
    "connector_subscriptions": "integration_service",
    "backup_restore_entries": "backup_service",
    "security_audit_records": "security_service",
}
_COLLECTION_SYSTEMS = {
    "customer_profiles": "account_service",
    "customer_search_documents": "search_service",
    "customer_analytics_reports": "analytics_platform",
    "support_conversations": "support_platform",
    "ticket_attachments": "object_storage",
    "customer_export_jobs": "export_service",
    "connector_configurations": "integration_service",
    "backup_catalog": "backup_service",
    "security_audit_events": "security_service",
    "deleted_customer_references": "identity_service",
    "retained_order_records": "order_service",
}


def _get(row: Any, key: str, default: Any = None) -> Any:
    if hasattr(row, "get"):
        value = row.get(key, default)
        return default if value is None else value
    return default


def _clean(value: Any, *, lower: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    return text.lower() if lower else text


def _utc(value: Any) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _prefix(resource_id: str) -> str | None:
    return next((prefix for prefix in sorted(RESOURCE_PREFIXES, key=len, reverse=True)
                 if resource_id.lower().startswith(prefix)), None)


@lru_cache(maxsize=16)
def _sample_prefix_map(dataset_root: str) -> dict[str, str]:
    mapping: dict[str, set[str]] = defaultdict(set)
    path = Path(dataset_root) / "sample_output.csv"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            try:
                steps = _stdjson.loads(row.get("steps_json", "[]"))
            except (TypeError, ValueError):
                continue
            for step in steps if isinstance(steps, list) else []:
                if not isinstance(step, dict):
                    continue
                rid, system = _clean(step.get("resource_id")), _clean(step.get("system_id"))
                prefix = _prefix(rid) if rid else None
                if prefix and system:
                    mapping[prefix].add(system)
    return {prefix: next(iter(systems)) for prefix, systems in mapping.items() if len(systems) == 1}


def _topology(table: str, file_topology: str | None) -> str | None:
    name = table.lower()
    if "failover" in name:
        return "failover_replica"
    if "regional" in name or re.search(r"replica_(ap_south|eu_west)", name):
        return "regional_replica"
    if "read_replica" in name:
        return "read_replica"
    if "reporting_replica" in name:
        return "reporting_replica"
    if name.endswith("_replica") or "_replica_" in name:
        return "replica"
    if name.endswith("_primary") or name == "customer_data_primary":
        return "primary"
    return file_topology


def _category(table: str, row: Mapping[str, Any]) -> str:
    collection = _clean(row.get("collection_name"), lower=True)
    if collection:
        return _COLLECTION_CATEGORIES.get(collection, _category_from_name(collection))
    normalized = table.lower()
    if normalized in _TABLE_CATEGORIES:
        return _TABLE_CATEGORIES[normalized]
    for name, category in _TABLE_CATEGORIES.items():
        if normalized.startswith(name + "_"):
            return category
    return _category_from_name(normalized)


def _category_from_name(value: str) -> str:
    name = value.lower()
    for token, category in (
        ("profile", "USER_PROFILE"), ("search", "SEARCH_INDEX_ENTRY"),
        ("analytics", "ANALYTICS_PROFILE"), ("support", "SUPPORT_MESSAGE"),
        ("attachment", "SUPPORT_ATTACHMENT"), ("export", "USER_EXPORT"),
        ("connector", "DATA_FLOW"), ("backup", "BACKUP_ARCHIVE"),
        ("audit", "SECURITY_AUDIT_LOG"), ("tombstone", "ACCOUNT_TOMBSTONE"),
        ("deleted_customer_reference", "ACCOUNT_TOMBSTONE"),
        ("retained_order", "LEGAL_HOLD_RECORD"),
    ):
        if token in name:
            return category
    return "UNKNOWN"


def _flatten(value: Any, parent: str = "") -> list[tuple[str, Any]]:
    pairs: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            pairs.extend(_flatten(item, str(key).lower()))
    elif isinstance(value, list):
        for item in value:
            pairs.extend(_flatten(item, parent))
    elif parent:
        pairs.append((parent, value))
    return pairs


def _extract_values(row: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    values = list(_flatten(dict(row)))
    emails, hashes, phones, user_ids, names = set(), set(), set(), set(), set()
    for key, raw in values:
        key = key.lower().replace("-", "_")
        value = _clean(raw)
        if value is None:
            continue
        if key in {"email", "email_address", "requester_email", "customer_email", "owner_email", "user_email"} or key.endswith("_email"):
            emails.add(value.lower())
        elif key in {"email_hash", "emailhash", "hash"} or key.endswith("_email_hash"):
            hashes.add(value.lower())
        elif key in {"phone", "phone_number", "requester_phone", "customer_phone", "owner_phone", "user_phone"} or key.endswith("_phone"):
            phones.add(value)
        elif key in {"user_id", "userid", "customer_reference", "subject_reference", "user_reference"}:
            user_ids.add(value)
        elif key in {"name", "full_name", "display_name", "requester_name", "customer_name", "owner_name"} or key.endswith("_name"):
            names.add(value)
    return tuple(sorted(emails)), tuple(sorted(hashes)), tuple(sorted(phones)), tuple(sorted(user_ids)), tuple(sorted(names))


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled", "active"}


def _state(category: str, record: Mapping[str, Any], emails: tuple[str, ...], hashes: tuple[str, ...],
           phones: tuple[str, ...], names: tuple[str, ...]) -> str:
    collection = _clean(record.get("collection_name"), lower=True) or ""
    if category == "DATA_FLOW":
        enabled = record.get("enabled", record.get("is_enabled"))
        return ACTIVE if _truthy(enabled) else DISABLED
    if category == "BACKUP_ARCHIVE":
        restore = record.get("restore_allowed")
        return ACTIVE if _truthy(restore) else BLOCKED
    if category in {"SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"}:
        return RETAINED
    if category == "ACCOUNT_TOMBSTONE":
        direct = record.get("name") or record.get("full_name") or record.get("email") or record.get("phone") or record.get("email_hash")
        if not direct:
            direct = bool(emails or hashes or phones or names)
        return IDENTIFIABLE if direct else REDACTED
    has_direct_identifiers = bool(emails or hashes or phones or names)
    if not has_direct_identifiers:
        return REDACTED if any(_clean(record.get(key)) for key in ("user_id", "customer_reference", "subject_reference")) else ANONYMIZED
    if category in {"ANALYTICS_PROFILE", "SUPPORT_MESSAGE", "SUPPORT_ATTACHMENT"}:
        return IDENTIFIABLE
    return PRESENT


def _resolve_system(table: str, record: Mapping[str, Any], category: str,
                    scope: Mapping[str, datetime], dataset_root: str) -> str:
    explicit = _clean(record.get("origin_system"))
    if explicit:
        return explicit
    table_base = table.lower()
    for suffix in ("_failover_replica", "_read_replica", "_reporting_replica", "_primary", "_replica"):
        if table_base.endswith(suffix):
            table_base = table_base[:-len(suffix)]
    candidate = _TABLE_SYSTEMS.get(table_base)
    if not candidate and record.get("collection_name"):
        candidate = _COLLECTION_SYSTEMS.get(str(record["collection_name"]).lower())
    if candidate and candidate in scope:
        return candidate
    if candidate:
        return candidate
    rid = _clean(record.get("resource_id"))
    prefix = _prefix(rid) if rid else None
    return _sample_prefix_map(dataset_root).get(prefix or "", "unknown_system")


def parse(file_row: Mapping[str, Any], dataset_dir: str | Path) -> tuple[list[Fact], dict[str, datetime]]:
    """Execute a SQL snapshot in memory and emit one normalized fact per resource row."""
    dataset_root = Path(dataset_dir).expanduser().resolve()
    relative_path = Path(str(_get(file_row, "file_path", "")))
    path = relative_path if relative_path.is_absolute() else dataset_root / relative_path
    sql_text = path.read_text(encoding="utf-8-sig")
    header_match = re.search(r"(?im)^\s*--\s*Captured at:\s*(\S+)", sql_text)
    header_time = _utc(header_match.group(1)) if header_match else None
    topology_match = re.search(r"(?im)^\s*--\s*Database topology:\s*(.+?)\s*$", sql_text)
    file_topology = _clean(topology_match.group(1), lower=True) if topology_match else None

    db = sqlite3.connect(":memory:")
    try:
        db.executescript(sql_text)
        tables = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        scope: dict[str, datetime] = {}
        if "snapshot_scope" in tables:
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({_q('snapshot_scope')})")}
            if {"origin_system", "captured_at"}.issubset(columns):
                for system, captured in db.execute("SELECT origin_system,captured_at FROM snapshot_scope"):
                    system_id, observed = _clean(system), _utc(captured)
                    if system_id and observed:
                        scope[system_id] = observed

        facts: list[Fact] = []
        fallback_time = header_time or _utc(_get(file_row, "captured_at"))
        file_id = _clean(_get(file_row, "file_id")) or path.stem
        for table in tables:
            if table == "snapshot_scope":
                continue
            table_info = db.execute(f"PRAGMA table_info({_q(table)})").fetchall()
            columns = [row[1] for row in table_info]
            if not columns:
                continue
            for raw_tuple in db.execute(f"SELECT * FROM {_q(table)}"):
                record = dict(zip(columns, raw_tuple))
                json_record: dict[str, Any] = {}
                raw_json = record.get("record_json")
                if raw_json:
                    try:
                        decoded = _stdjson.loads(raw_json)
                        if isinstance(decoded, dict):
                            json_record = decoded
                    except (TypeError, ValueError):
                        pass
                merged = {**record, **json_record}
                resource_id = _clean(record.get("resource_id") or json_record.get("resource_id"))
                if not resource_id:
                    continue
                category = _category(table, record)
                system_id = _resolve_system(table, record, category, scope, str(dataset_root))
                emails, hashes, phones, user_ids, names = _extract_values(merged)
                state = _state(category, merged, emails, hashes, phones, names)
                table_topology = _topology(table, file_topology)
                updated = _utc(record.get("updated_at") or record.get("indexed_at") or merged.get("updated_at"))
                observed_at = scope.get(system_id) or fallback_time or updated
                if observed_at is None:
                    observed_at = updated
                if observed_at is None:
                    raise ValueError(f"No observation timestamp for {path.name}:{table}:{resource_id}")
                # Keep retention fields and original table context available to downstream policy logic.
                raw_ref = _stdjson.dumps({"table": table, "row": record, "record_json": json_record},
                                         sort_keys=True, ensure_ascii=False, default=str)
                facts.append(Fact(
                    file_id=file_id, observed_at=observed_at.astimezone(timezone.utc),
                    system_id=system_id, resource_id=resource_id, category=category,
                    state=state, emails=emails, hashes=hashes, phones=phones,
                    user_ids=user_ids, names=names, topology=table_topology,
                    source_kind="sql", raw_ref=raw_ref,
                ))
                if system_id not in scope and header_time:
                    scope[system_id] = header_time
        return facts, scope
    finally:
        db.close()
