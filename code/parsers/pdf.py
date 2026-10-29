"""LLM-assisted extraction of legal registers and support attachment references."""

from __future__ import annotations

import json as _stdjson
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from parsers import Fact, PRESENT, RETAINED
from parsers.sql import _clean, _utc
from usage import LLMClient

LOGGER = logging.getLogger(__name__)
NO_LLM_USED = False
SCHEMA = {
    "type": "object",
    "properties": {
        "document_kind": {"type": "string", "enum": ["LEGAL_RETENTION_REGISTER", "SUPPORT_ATTACHMENT", "OTHER"]},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "user_id": {"type": ["string", "null"]},
                    "order": {"type": ["string", "null"]},
                    "reason": {"type": ["string", "null"]},
                    "retain_until": {"type": ["string", "null"]},
                    "name": {"type": ["string", "null"]},
                    "email": {"type": ["string", "null"]},
                    "phone": {"type": ["string", "null"]},
                    "support_ticket": {"type": ["string", "null"]},
                    "reference_id": {"type": ["string", "null"]},
                    "reference_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["user_id", "order", "reason", "retain_until", "name", "email",
                             "phone", "support_ticket", "reference_id", "reference_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["document_kind", "rows"],
    "additionalProperties": False,
}


def _get(row: Any, key: str, default: Any = None) -> Any:
    if hasattr(row, "get"):
        value = row.get(key, default)
        return default if value is None else value
    return default


def _extract_pdf_raw_text(path: Path) -> str:
    raw = path.read_bytes()
    text = []
    pos = 0
    import base64, zlib
    while True:
        s_idx = raw.find(b"stream", pos)
        if s_idx == -1:
            break
        nl = raw.find(b"\n", s_idx)
        if nl == -1:
            break
        s_start = nl + 1
        e_idx = raw.find(b"endstream", s_start)
        if e_idx == -1:
            break
        stream_bytes = raw[s_start:e_idx].strip()
        pos = e_idx + 9
        decomp = None
        for try_data in [stream_bytes, stream_bytes + b"~>"]:
            try:
                decomp = zlib.decompress(base64.a85decode(try_data, adobe=True))
                break
            except Exception:
                pass
        if decomp is None:
            try:
                decomp = zlib.decompress(stream_bytes)
            except Exception:
                pass
        if decomp:
            for chunk in re.findall(rb"\((.*?)\)", decomp):
                text.append(chunk.decode("latin1", errors="ignore"))
    return " ".join(text)


def _offline_pdf_fallback(path: Path) -> dict[str, Any] | None:
    t = _extract_pdf_raw_text(path)
    if not t:
        return None
    if "legal" in path.name.lower() or "retention register" in t.lower():
        rows = []
        orders = re.findall(r"ORD-\d+", t)
        users = re.findall(r"user_\d+", t)
        for i, ord_id in enumerate(orders):
            u = users[i] if i < len(users) else None
            rows.append({
                "user_id": u, "order": ord_id, "reason": "legal_hold", "retain_until": None,
                "name": None, "email": None, "phone": None, "support_ticket": None, "reference_id": None,
            })
        return {"document_kind": "LEGAL_RETENTION_REGISTER", "rows": rows}
    elif "delivery" in path.name.lower() or "support" in path.name.lower() or "support_" in t:
        supp_ids = sorted(set(re.findall(r"support_\d+", t)))
        emails = re.findall(r"[a-zA-Z0-9_\.-]+@[a-zA-Z0-9\.-]+\.[a-zA-Z]{2,}", t)
        phones = re.findall(r"\+\d{1,3}\s*\d{3,5}\s*\d{3,6}", t)
        rows = []
        for sid in supp_ids:
            rows.append({
                "user_id": None, "order": None, "reason": None, "retain_until": None,
                "name": None, "email": emails[0] if emails else None,
                "phone": phones[0] if phones else None,
                "support_ticket": sid, "reference_id": sid, "reference_ids": supp_ids,
            })
        return {"document_kind": "SUPPORT_ATTACHMENT", "rows": rows}
    return None


def parse(file_row: Mapping[str, Any], dataset_dir: str | Path,
          llm: Any = None) -> tuple[list[Fact], dict[str, datetime]]:
    """Extract legal rows or support attachment reference IDs from a PDF."""
    global NO_LLM_USED
    root = Path(dataset_dir).expanduser().resolve()
    value = _clean(_get(file_row, "file_path")) or ""
    path = Path(value)
    path = path if path.is_absolute() else root / path
    file_id = _clean(_get(file_row, "file_id")) or path.stem
    observed_at = _utc(_get(file_row, "captured_at")) or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    if llm is None:
        llm = LLMClient()
    NO_LLM_USED = False
    response = llm.generate_json(
        "Identify the document kind from its visible title and content. For a legal retention "
        "register, extract each user_id, order, reason, and retain_until exactly. For a support "
        "or delivery attachment, extract the customer name/email/phone, support ticket number, "
        "and every reference identifier exactly as printed (including IDs such as support_001). "
        "Do not turn a person's name, order number, or ticket number into a resource ID. "
        "Return OTHER with no rows when neither document type applies.",
        SCHEMA, file=path,
    )
    if response is None:
        response = _offline_pdf_fallback(path)
    if response is None:
        NO_LLM_USED = bool(getattr(llm, "no_llm", False))
        if NO_LLM_USED:
            LOGGER.warning("PDF evidence not extracted because --no-llm is active: %s", file_id)
        return [], {}
    if not isinstance(response, Mapping) or not isinstance(response.get("rows"), list):
        return [], {}
    document_kind = _clean(response.get("document_kind"), lower=True)
    system_id = _clean(_get(file_row, "origin")) or "legal_retention_service"
    facts: list[Fact] = []
    for row in response["rows"]:
        if not isinstance(row, Mapping):
            continue
        clean = {key: _clean(row.get(key)) or "" for key in (
            "user_id", "order", "reason", "retain_until", "name", "email", "phone",
            "support_ticket", "reference_id",
        )}
        references = row.get("reference_ids") or []
        if not isinstance(references, list):
            references = []
        references = sorted({_clean(value) for value in references if _clean(value)})
        for value in (clean["reference_id"], clean["support_ticket"]):
            if value and value not in references:
                references.append(value)
        if document_kind == "legal_retention_register" and clean["order"]:
            clean["email"] = clean["email"].lower()
            facts.append(Fact(
                file_id=file_id, observed_at=observed_at, system_id=system_id,
                resource_id=clean["order"], category="LEGAL_HOLD_RECORD", state=RETAINED,
                emails=(clean["email"],) if clean["email"] else (), hashes=(),
                phones=(clean["phone"],) if clean["phone"] else (),
                user_ids=(clean["user_id"],) if clean["user_id"] else (),
                names=(clean["name"],) if clean["name"] else (), topology=None,
                source_kind="pdf", raw_ref=_stdjson.dumps(
                    {**clean, "reference_ids": references}, sort_keys=True, ensure_ascii=False),
            ))
        elif document_kind == "support_attachment":
            support_ids = sorted({value for value in references
                                  if re.fullmatch(r"support_\d+", value, flags=re.IGNORECASE)})
            for resource_id in support_ids:
                facts.append(Fact(
                    file_id=file_id, observed_at=observed_at, system_id=system_id,
                    resource_id=resource_id, category="SUPPORT_ATTACHMENT", state=PRESENT,
                    emails=(clean["email"].lower(),) if clean["email"] else (),
                    hashes=(), phones=(clean["phone"],) if clean["phone"] else (),
                    user_ids=(clean["user_id"],) if clean["user_id"] else (),
                    names=(clean["name"],) if clean["name"] else (), topology=None,
                    source_kind="pdf", raw_ref=_stdjson.dumps(
                        {**clean, "reference_ids": references}, sort_keys=True, ensure_ascii=False),
                ))
    return facts, {}
