"""Parser for JSON evidence bundles and service exports."""

from __future__ import annotations

import json as _stdjson
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from loader import RESOURCE_PREFIXES
from parsers import (ACTIVE, ABSENT, ANONYMIZED, BLOCKED, DISABLED, Fact,
                     IDENTIFIABLE, PRESENT, REDACTED, RETAINED, UNKNOWN)
from parsers.sql import (_category, _category_from_name, _clean, _extract_values,
                         _sample_prefix_map, _state, _utc)

_KNOWN_CATEGORIES = {
    "USER_PROFILE", "SECONDARY_IDENTIFIER", "SEARCH_INDEX_ENTRY", "CACHE_ENTRY",
    "SUPPORT_MESSAGE", "SUPPORT_ATTACHMENT", "ANALYTICS_PROFILE", "PRODUCT_TELEMETRY",
    "USER_EXPORT", "MARKETING_PROFILE", "EMAIL_DELIVERY_LOG", "SECURITY_AUDIT_LOG",
    "LEGAL_HOLD_RECORD", "BACKUP_ARCHIVE", "ACCOUNT_TOMBSTONE", "DATA_FLOW",
}
_STATE_MAP = {
    "NOT_FOUND": ABSENT, "ABSENT": ABSENT, "FOUND": PRESENT, "PRESENT": PRESENT,
    "IDENTIFIABLE": IDENTIFIABLE, "ANONYMIZED": ANONYMIZED, "REDACTED": REDACTED,
    "ACTIVE": ACTIVE, "DISABLED": DISABLED, "BLOCKED": BLOCKED, "RETAINED": RETAINED,
}


def _get(row: Any, key: str, default: Any = None) -> Any:
    if hasattr(row, "get"):
        value = row.get(key, default)
        return default if value is None else value
    return default


def _prefix(resource_id: str) -> str | None:
    return next((p for p in sorted(RESOURCE_PREFIXES, key=len, reverse=True)
                 if resource_id.lower().startswith(p)), None)


def _walk_records(node: Any, context: dict[str, Any]):
    """Yield resource-bearing dictionaries without treating nested metrics as records."""
    if isinstance(node, dict):
        if _clean(node.get("resource_id")):
            yield node, context
            return
        for key, child in node.items():
            child_context = dict(context)
            key_lower = str(key).lower()
            if key_lower in {"account_service", "analytics_platform", "backup_service", "backup_restore_service",
                             "export_service", "integration_service", "search_service", "security_service",
                             "support_platform", "support_storage_service", "object_storage", "identity_service",
                             "privacy_treatment_service", "legal_service", "order_service"}:
                child_context["system_id"] = key
            if key_lower in {
                "customer_profiles", "customer_search_documents", "customer_analytics_reports",
                "support_conversations", "ticket_attachments", "customer_export_jobs",
                "connector_configurations", "backup_catalog", "security_audit_events",
                "deleted_customer_references", "retained_order_records", "profile_lookups",
                "profiles", "restore_entries", "exports", "connectors", "index_queries",
                "audit_records", "tickets",
            }:
                child_context["collection"] = key
            if isinstance(child, list):
                for item in child:
                    if isinstance(item, dict):
                        yield from _walk_records(item, child_context)
            elif isinstance(child, dict):
                yield from _walk_records(child, child_context)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_records(item, context)


def _category_for(record: Mapping[str, Any], context: Mapping[str, Any], rid: str) -> str:
    declared = _clean(record.get("category") or record.get("record_type"), lower=True)
    if declared:
        normalized = declared.upper()
        if normalized in _KNOWN_CATEGORIES:
            return normalized
    prefix = _prefix(rid)
    prefix_categories = {
        "account_": "USER_PROFILE", "data_flow_": "DATA_FLOW",
        "cache_": "CACHE_ENTRY", "email_delivery_": "EMAIL_DELIVERY_LOG",
        "marketing_": "MARKETING_PROFILE", "legal_hold_": "LEGAL_HOLD_RECORD",
        "object_": "SUPPORT_ATTACHMENT",
        "analytics_": "ANALYTICS_PROFILE", "support_": "SUPPORT_MESSAGE",
        "search_": "SEARCH_INDEX_ENTRY", "audit_record_": "SECURITY_AUDIT_LOG",
        "backup_": "BACKUP_ARCHIVE", "export_": "USER_EXPORT",
        "tombstone_": "ACCOUNT_TOMBSTONE",
    }
    if prefix and prefix in prefix_categories:
        return prefix_categories[prefix]
    collection = _clean(record.get("collection_name") or record.get("collection") or context.get("collection"))
    if collection:
        collection_category = _category(collection, {**record, "collection_name": collection})
        if collection_category != "UNKNOWN":
            return collection_category
    if prefix:
        inferred = _category_from_name(prefix)
        if inferred != "UNKNOWN":
            return inferred
    return _category_from_name(str(context.get("data_store") or context.get("system_id") or ""))


def _extract_json_values(record: Mapping[str, Any]):
    emails, hashes, phones, user_ids, names = map(set, _extract_values(record))
    for key in ("query", "lookup_value", "lookup_key", "match_key", "subject_key", "correlation_key", "matched_value"):
        value = _clean(record.get(key))
        if not value:
            continue
        if "@" in value:
            emails.add(value.lower())
        elif value.lower().startswith("user_"):
            user_ids.add(value)
        elif "hash" in key.lower():
            hashes.add(value.lower())
    return tuple(sorted(emails)), tuple(sorted(hashes)), tuple(sorted(phones)), tuple(sorted(user_ids)), tuple(sorted(names))


def _json_state(record: Mapping[str, Any], category: str, values) -> str:
    for key in ("state", "status", "result"):
        raw = _clean(record.get(key))
        if raw and raw.upper() in _STATE_MAP:
            return _STATE_MAP[raw.upper()]
    status_code = _clean(record.get("status_code") or record.get("http_status"))
    if status_code == "404":
        return ABSENT
    emails, hashes, phones, user_ids, names = values
    if not any((emails, hashes, phones, user_ids, names)):
        return ANONYMIZED
    return _state(category, record, emails, hashes, phones, names)


def parse(file_row: Mapping[str, Any], dataset_dir: str | Path) -> tuple[list[Fact], dict[str, datetime]]:
    root = Path(dataset_dir).expanduser().resolve()
    rel = Path(str(_get(file_row, "file_path", "")))
    path = rel if rel.is_absolute() else root / rel
    payload = _stdjson.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        return [], {}

    file_id = _clean(_get(file_row, "file_id")) or path.stem
    source = _clean(payload.get("source") or payload.get("origin")) or "json"
    fallback_observed = _utc(payload.get("captured_at") or payload.get("exported_at") or _get(file_row, "captured_at"))
    records: list[tuple[dict[str, Any], dict[str, Any]]] = []
    scope: dict[str, datetime] = {}

    snapshots = payload.get("snapshots")
    if isinstance(snapshots, list):
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                continue
            context = {
                "system_id": _clean(snapshot.get("data_store") or snapshot.get("origin_system")),
                "data_store": _clean(snapshot.get("data_store")),
                "collection": _clean(snapshot.get("collection") or snapshot.get("collection_name")),
                "observed_at": _utc(snapshot.get("captured_at")) or fallback_observed,
            }
            if context["system_id"] and context["observed_at"] and snapshot.get("records"):
                scope[context["system_id"]] = context["observed_at"]
            for record, inherited in _walk_records(snapshot.get("records", []), context):
                records.append((record, inherited))
    else:
        for record, context in _walk_records(payload, {"observed_at": fallback_observed}):
            records.append((record, context))

    fallback_map = _sample_prefix_map(str(root))
    facts: list[Fact] = []
    for record, context in records:
        resource_id = _clean(record.get("resource_id"))
        if not resource_id:
            continue
        category = _category_for(record, context, resource_id)
        system_id = _clean(context.get("system_id") or record.get("data_store") or record.get("origin_system")
                           or record.get("system"))
        if not system_id:
            system_id = fallback_map.get(_prefix(resource_id) or "", "unknown_system")
        observed_at = (_utc(context.get("observed_at")) or _utc(record.get("observed_at"))
                       or _utc(record.get("recorded_at")) or _utc(record.get("captured_at"))
                       or fallback_observed or _utc(_get(file_row, "captured_at")))
        if observed_at is None:
            continue
        scope.setdefault(system_id, observed_at)
        values = _extract_json_values(record)
        state = _json_state(record, category, values)
        raw_ref = _stdjson.dumps({"context": context, "record": record}, sort_keys=True,
                                 ensure_ascii=False, default=str)
        facts.append(Fact(
            file_id=file_id, observed_at=observed_at, system_id=system_id,
            resource_id=resource_id, category=category, state=state,
            emails=values[0], hashes=values[1], phones=values[2], user_ids=values[3],
            names=values[4], topology=None, source_kind="json", raw_ref=raw_ref,
        ))
    return facts, scope
