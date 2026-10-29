"""LLM-assisted extraction of identity and resource keys from PNG evidence."""

from __future__ import annotations

import json as _stdjson
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from parsers import Fact, PRESENT
from parsers.sql import _clean, _sample_prefix_map, _utc
from usage import LLMClient

LOGGER = logging.getLogger(__name__)
NO_LLM_USED = False
SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": ["string", "null"]},
        "user_id": {"type": ["string", "null"]},
        "account_id": {"type": ["string", "null"]},
        "email": {"type": ["string", "null"]},
        "phone": {"type": ["string", "null"]},
        "support_ticket": {"type": ["string", "null"]},
        "orders": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "user_id", "account_id", "email", "phone", "support_ticket", "orders"],
    "additionalProperties": False,
}


def _get(row: Any, key: str, default: Any = None) -> Any:
    if hasattr(row, "get"):
        value = row.get(key, default)
        return default if value is None else value
    return default


def _text(value: Any) -> str | None:
    return _clean(value)


def _system(prefix: str, prefix_map: Mapping[str, str], fallback: str) -> str:
    return prefix_map.get(prefix, fallback)


def parse(file_row: Mapping[str, Any], dataset_dir: str | Path,
          llm: Any = None) -> tuple[list[Fact], dict[str, datetime]]:
    """Extract an account/support screenshot into one Fact per visible resource key."""
    global NO_LLM_USED
    path_value = _text(_get(file_row, "file_path")) or ""
    root = Path(dataset_dir).expanduser().resolve()
    path = Path(path_value)
    path = path if path.is_absolute() else root / path
    file_id = _text(_get(file_row, "file_id")) or path.stem
    observed_at = _utc(_get(file_row, "captured_at")) or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    if llm is None:
        llm = LLMClient()
    NO_LLM_USED = False
    response = llm.generate_json(
        "Read the screenshot and return only the schema fields. Copy identifiers exactly; "
        "use null for fields not visible and an empty orders list when none are visible.",
        SCHEMA, file=path,
    )
    if response is None:
        NO_LLM_USED = bool(getattr(llm, "no_llm", False))
        if NO_LLM_USED:
            LOGGER.warning("Image evidence not extracted because --no-llm is active: %s", file_id)
        return [], {}
    if not isinstance(response, Mapping):
        return [], {}
    # Keep only contract fields even if a nonconforming client returns extras.
    data = {key: response.get(key) for key in SCHEMA["properties"]}
    user_id = _text(data.get("user_id"))
    name = _text(data.get("name"))
    email = _text(data.get("email"))
    email = email.lower() if email else None
    phone = _text(data.get("phone"))
    identifiers = {
        "emails": (email,) if email else (),
        "phones": (phone,) if phone else (),
        "user_ids": (user_id,) if user_id else (),
        "names": (name,) if name else (),
    }
    prefix_map = _sample_prefix_map(str(root))
    facts: list[Fact] = []
    for resource_id, prefix, category in (
        (_text(data.get("account_id")), "account_", "USER_PROFILE"),
        (_text(data.get("support_ticket")), "support_", "SUPPORT_MESSAGE"),
    ):
        if not resource_id or not resource_id.lower().startswith(prefix):
            continue
        facts.append(Fact(
            file_id=file_id, observed_at=observed_at,
            system_id=_system(prefix, prefix_map, _text(_get(file_row, "origin")) or "unknown_system"),
            resource_id=resource_id, category=category, state=PRESENT,
            emails=identifiers["emails"], hashes=(), phones=identifiers["phones"],
            user_ids=identifiers["user_ids"], names=identifiers["names"],
            topology=None, source_kind="image",
            raw_ref=_stdjson.dumps(data, sort_keys=True, ensure_ascii=False),
        ))
    return facts, {}
