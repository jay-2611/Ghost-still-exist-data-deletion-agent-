"""Parser for structured and semi-structured service logs."""

from __future__ import annotations

import json as _stdjson
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from parsers import (ABSENT, Fact, IDENTIFIABLE, PRESENT, UNKNOWN)
from parsers.sql import (_category_from_name, _clean, _sample_prefix_map, _utc)
from loader import RESOURCE_PREFIXES

_TIMESTAMP = re.compile(r"^\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)")
_KV = re.compile(r'''([A-Za-z_][\w.-]*)=(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)'|([^\s]+))''')


def _get(row: Any, key: str, default: Any = None) -> Any:
    if hasattr(row, "get"):
        value = row.get(key, default)
        return default if value is None else value
    return default


def _unquote(value: str) -> str:
    try:
        return bytes(value, "utf-8").decode("unicode_escape")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return value


def _fields(text: str) -> dict[str, str]:
    return {m.group(1).lower(): _unquote(m.group(2) or m.group(3) or m.group(4) or "")
            for m in _KV.finditer(text)}


def _resource_prefix(rid: str) -> str | None:
    return next((prefix for prefix in sorted(RESOURCE_PREFIXES, key=len, reverse=True)
                 if rid.lower().startswith(prefix)), None)


def _parse_event(raw: str, observed_at: datetime) -> dict[str, Any]:
    body = raw.strip()
    ts_match = _TIMESTAMP.match(body)
    if ts_match:
        body = body[ts_match.end():].lstrip()
    fields: dict[str, str] = {}
    event = service = trace_id = level = None

    # JSON payload after the timestamp (or a standalone JSON log line).
    json_start = body.find("{")
    if json_start >= 0:
        try:
            payload, _ = _stdjson.JSONDecoder().raw_decode(body[json_start:])
            if isinstance(payload, dict):
                fields.update({str(k).lower(): str(v) for k, v in payload.items() if v is not None})
        except ValueError:
            pass

    if " | " in body:
        parts = [part.strip() for part in body.split("|")]
        if len(parts) >= 5:
            level = parts[0]
            service = parts[1]
            if len(parts) >= 6:
                trace_id = parts[2]
                event = parts[3]
                field_text = " | ".join(parts[4:])
            else:
                event = parts[2]
                field_text = " | ".join(parts[3:])
            fields.update(_fields(field_text))
    else:
        bracket = re.match(r"\[(?P<level>[^]]+)\]\s+\[(?P<service>[^]]+)\]\s+\[(?P<trace>[^]]+)\]\s+(?P<event>[\w.-]+):?\s*(?P<fields>.*)$", body)
        if bracket:
            level, service, trace_id = bracket.group("level", "service", "trace")
            event = bracket.group("event")
            fields.update(_fields(bracket.group("fields")))
        else:
            # Syslog header: <PRI>VERSION HOST APP PROCID ... followed by logfmt payload.
            syslog = re.match(r"<\d+>\d+\s+\S+\s+(?P<app>\S+)\s+(?P<proc>\S+)\s+-\s+-\s+(?P<tail>.*)$", body)
            tail = body
            if syslog:
                service, trace_id, tail = syslog.group("app", "proc", "tail")
            outer = _fields(tail)
            fields.update(outer)
            message = outer.get("message")
            if message:
                fields.update(_fields(message))
            level = fields.get("level") or fields.get("severity")
            service = fields.get("service") or fields.get("function") or fields.get("logger") or service
            trace_id = fields.get("trace_id") or fields.get("trace") or fields.get("requestid") or fields.get("request_id") or trace_id
            event = fields.get("event") or fields.get("event_type")
            if not event:
                colon = re.search(r"\b([a-z][a-z0-9_.-]+):\s*(?:instance=|resource_id=|lookup_key=)", tail)
                if colon:
                    event = colon.group(1)

    event = event or fields.get("event") or fields.get("event_type")
    service = fields.get("service") or fields.get("function") or fields.get("logger") or service
    trace_id = fields.get("trace_id") or fields.get("trace") or fields.get("requestid") or fields.get("request_id") or trace_id
    return {"observed_at": observed_at, "level": level or fields.get("level") or fields.get("severity"),
            "service": service, "trace_id": trace_id, "resource_id": fields.get("resource_id"),
            "event": event, "fields": fields, "raw": raw}


def _event_identifiers(fields: Mapping[str, str]):
    emails, hashes, phones, user_ids, names = set(), set(), set(), set(), set()
    for key, raw in fields.items():
        value = _clean(raw)
        if not value:
            continue
        key = key.lower().replace("-", "_")
        if "@" in value and key in {"lookup_key", "lookup_value", "match_key", "subject_key", "correlation_key", "matched_value", "subject_reference", "email", "requester_email", "customer_email", "owner_email"}:
            emails.add(value.lower())
        elif "email_hash" in key or key in {"hash", "hash_value", "correlation_key"}:
            hashes.add(value.lower())
        elif len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value):
            hashes.add(value.lower())
        elif "phone" in key or key in {"phone_number", "mobile"}:
            phones.add(value)
        elif key in {"user_id", "customer_reference", "subject_reference", "user_reference"} or value.lower().startswith("user_"):
            if "@" not in value:
                user_ids.add(value)
        elif key in {"name", "full_name", "display_name", "requester_name"}:
            names.add(value)
        elif key in {"lookup_key", "lookup_value", "match_key", "subject_key", "correlation_key", "matched_value"} and "@" in value:
            emails.add(value.lower())
    return tuple(sorted(emails)), tuple(sorted(hashes)), tuple(sorted(phones)), tuple(sorted(user_ids)), tuple(sorted(names))


def _category(event: Mapping[str, Any]) -> str:
    fields = event["fields"]
    declared = _clean(fields.get("category") or fields.get("record_type"), lower=True)
    known = {"USER_PROFILE", "SECONDARY_IDENTIFIER", "SEARCH_INDEX_ENTRY", "CACHE_ENTRY",
             "SUPPORT_MESSAGE", "SUPPORT_ATTACHMENT", "ANALYTICS_PROFILE", "PRODUCT_TELEMETRY",
             "USER_EXPORT", "MARKETING_PROFILE", "EMAIL_DELIVERY_LOG", "SECURITY_AUDIT_LOG",
             "LEGAL_HOLD_RECORD", "BACKUP_ARCHIVE", "ACCOUNT_TOMBSTONE", "DATA_FLOW"}
    if declared and declared.upper() in known:
        return declared.upper()
    rid = _clean(event.get("resource_id"))
    prefix = _resource_prefix(rid) if rid else None
    prefix_categories = {
        "account_": "USER_PROFILE", "data_flow_": "DATA_FLOW",
        "cache_": "CACHE_ENTRY", "email_delivery_": "EMAIL_DELIVERY_LOG",
        "marketing_": "MARKETING_PROFILE", "legal_hold_": "LEGAL_HOLD_RECORD",
        "object_": "SUPPORT_ATTACHMENT",
    }
    if prefix in prefix_categories:
        return prefix_categories[prefix]
    return _category_from_name(prefix or str(event.get("service") or ""))


def _event_state(event: Mapping[str, Any], category: str, identifiers) -> str:
    fields = event["fields"]
    name = str(event.get("event") or "").lower()
    try:
        rows = int(fields.get("rows", "-1"))
    except (TypeError, ValueError):
        rows = -1
    try:
        direct_count = int(fields.get("direct_identifiers", "0"))
    except (TypeError, ValueError):
        direct_count = 0
    # A lookup-start event records a query, not a successful read of the resource.
    # Keep its identity as context while preventing it from becoming a PRESENT fact.
    if name.endswith(("_started", "_start", ".started", ".start")):
        return UNKNOWN
    http_status = str(fields.get("http_status") or fields.get("status_code") or "")
    if ("profile_lookup" in name or name.endswith("_completed")) and (rows == 0 or http_status == "404"):
        return ABSENT

    # Connector / data flow status
    if category == "DATA_FLOW":
        enabled = _clean(fields.get("enabled"), lower=True)
        if enabled in {"true", "1"}:
            return "ACTIVE"
        if enabled in {"false", "0"}:
            return "DISABLED"

    # Backup / restore status
    if category == "BACKUP_ARCHIVE":
        restore_allowed = _clean(fields.get("restore_allowed"), lower=True)
        if restore_allowed in {"true", "1"}:
            return "ACTIVE"
        if restore_allowed in {"false", "0"}:
            return "BLOCKED"
        eligible = _clean(fields.get("eligible"), lower=True)
        deletion_block = _clean(fields.get("deletion_block"), lower=True)
        if eligible in {"true", "1"} and deletion_block in {"false", "0"}:
            return "ACTIVE"
        if deletion_block in {"true", "1"}:
            return "BLOCKED"

    matched = _clean(fields.get("matched_value"))
    if matched and matched.lower() not in {"none", "null", "false", "0"} or direct_count > 0:
        return IDENTIFIABLE
    result = _clean(fields.get("result") or fields.get("state"), lower=True)
    if result in {"not_found", "absent", "miss"}:
        return ABSENT
    if result in {"found", "present", "hit"}:
        return PRESENT
    if any(identifiers[:4]):
        return IDENTIFIABLE if category in {"ANALYTICS_PROFILE", "SUPPORT_MESSAGE", "SUPPORT_ATTACHMENT"} else PRESENT
    if fields.get("email") == "null" and category in {"ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"}:
        return "ANONYMIZED"
    return UNKNOWN


def parse(file_row: Mapping[str, Any], dataset_dir: str | Path) -> tuple[list[Fact], dict[str, datetime]]:
    root = Path(dataset_dir).expanduser().resolve()
    rel = Path(str(_get(file_row, "file_path", "")))
    path = rel if rel.is_absolute() else root / rel
    file_id = _clean(_get(file_row, "file_id")) or path.stem
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    grouped: list[tuple[datetime, list[str]]] = []
    current_time = None
    current_lines: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        match = _TIMESTAMP.match(line)
        if match:
            timestamp = _utc(match.group(1))
            if current_lines and current_time:
                grouped.append((current_time, current_lines))
            current_time, current_lines = timestamp, [line]
        elif current_lines:
            current_lines.append(line)
    if current_lines and current_time:
        grouped.append((current_time, current_lines))

    facts: list[Fact] = []
    prefix_system = _sample_prefix_map(str(root))
    
    # First pass: collect identifiers across all events by trace_id
    trace_identifiers: dict[str, tuple[set[str], set[str], set[str], set[str], set[str]]] = {}
    parsed_events: list[tuple[datetime, dict[str, Any]]] = []
    for observed_at, raw_lines in grouped:
        event = _parse_event("\n".join(raw_lines), observed_at)
        parsed_events.append((observed_at, event))
        trace_id = _clean(event.get("trace_id"))
        if trace_id:
            if trace_id not in trace_identifiers:
                trace_identifiers[trace_id] = (set(), set(), set(), set(), set())
            idents = _event_identifiers(event["fields"])
            for idx in range(5):
                trace_identifiers[trace_id][idx].update(idents[idx])

    for observed_at, event in parsed_events:
        resource_id = _clean(event.get("resource_id"))
        # A match_key alone is a query, not a resource fact.
        if not resource_id:
            continue
        fields = event["fields"]
        service = _clean(fields.get("system") or event.get("service")) or "unknown_system"
        # Replica/collector service names describe where the event was emitted,
        # while the resource prefix identifies the resource's home system.
        prefix = _resource_prefix(resource_id)
        if service.endswith(("_replica", "_failover_replica", "_read_replica")) and prefix:
            service = prefix_system.get(prefix, service)
        category = _category(event)
        direct_idents = _event_identifiers(fields)
        trace_id = _clean(event.get("trace_id"))
        if trace_id and trace_id in trace_identifiers:
            t_idents = trace_identifiers[trace_id]
            emails = tuple(sorted(set(direct_idents[0]) | t_idents[0]))
            hashes = tuple(sorted(set(direct_idents[1]) | t_idents[1]))
            phones = tuple(sorted(set(direct_idents[2]) | t_idents[2]))
            user_ids = tuple(sorted(set(direct_idents[3]) | t_idents[3]))
            names = tuple(sorted(set(direct_idents[4]) | t_idents[4]))
            identifiers = (emails, hashes, phones, user_ids, names)
        else:
            identifiers = direct_idents

        state = _event_state(event, category, identifiers)
        raw_ref = _stdjson.dumps(event, sort_keys=True, ensure_ascii=False, default=str)
        facts.append(Fact(
            file_id=file_id, observed_at=observed_at, system_id=service,
            resource_id=resource_id, category=category, state=state,
            emails=identifiers[0], hashes=identifiers[1], phones=identifiers[2],
            user_ids=identifiers[3], names=identifiers[4], topology=None,
            source_kind="log", raw_ref=raw_ref,
        ))
    return facts, {}
