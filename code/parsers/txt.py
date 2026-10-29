"""Parser for plain-text handover tables."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from parsers import (ACTIVE, ABSENT, ANONYMIZED, BLOCKED, DISABLED, Fact,
                     IDENTIFIABLE, PRESENT, REDACTED, RETAINED, UNKNOWN)
from parsers.sql import _clean, _utc

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


def _identifiers(value: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    text = _clean(value)
    if not text or text.lower() in {"no direct identifier", "none", "null", "-"}:
        return (), (), (), ()
    if "@" in text:
        return (text.lower(),), (), (), ()
    if text.lower().startswith("user_"):
        return (), (), (), (text,)
    if re.search(r"\d", text):
        return (), (), (text,), ()
    return (), (), (), ()


def parse(file_row: Mapping[str, Any], dataset_dir: str | Path) -> tuple[list[Fact], dict[str, datetime]]:
    root = Path(dataset_dir).expanduser().resolve()
    rel = Path(str(_get(file_row, "file_path", "")))
    path = rel if rel.is_absolute() else root / rel
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    header = re.search(r"(?im)^\s*Snapshot:\s*(\S+)", text)
    header_time = _utc(header.group(1)) if header else _utc(_get(file_row, "captured_at"))
    file_id = _clean(_get(file_row, "file_id")) or path.stem
    facts: list[Fact] = []
    scope: dict[str, datetime] = {}
    arrow_comment = re.compile(r"(?:->|→|➡️|➜|➔|⇒).*$")
    for line in text.splitlines():
        if "|" not in line:
            continue
        cleaned = line.strip().lstrip("-•▪* ")
        cleaned = arrow_comment.sub("", cleaned)
        cleaned = cleaned.replace("✅", "").replace("❌", "").strip()
        parts = [part.strip() for part in cleaned.split("|")]
        row_time = _utc(parts[0]) if len(parts) >= 6 else None
        if row_time:
            parts = parts[1:]
        if len(parts) < 5:
            continue
        system_id, resource_id, category, raw_state, identifier = parts[:5]
        system_id = _clean(system_id)
        resource_id = _clean(resource_id)
        category = _clean(category, lower=True)
        raw_state = _clean(raw_state, lower=True)
        if not system_id or not resource_id or not category or not raw_state:
            continue
        category = category.upper()
        state = _STATE_MAP.get(raw_state.upper(), UNKNOWN)
        emails, hashes, phones, user_ids = _identifiers(identifier)
        observed_at = row_time or header_time
        if observed_at is None:
            continue
        scope.setdefault(system_id, observed_at)
        raw_ref = cleaned
        facts.append(Fact(
            file_id=file_id, observed_at=observed_at, system_id=system_id,
            resource_id=resource_id, category=category, state=state,
            emails=emails, hashes=hashes, phones=phones, user_ids=user_ids,
            names=(), topology=None, source_kind="txt", raw_ref=raw_ref,
        ))
    return facts, scope
