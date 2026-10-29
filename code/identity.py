from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class IdentitySet:
    user_ids: tuple[str, ...]
    emails: frozenset[str]
    hashes: frozenset[str]
    phones: frozenset[str]
    linked_resources: frozenset[str]
    primary_user_id: str | None
    flags: frozenset[str]


def _clean(value: Any, *, lower: bool = False) -> str | None:
    if value is None or pd.isna(value):
        return None
    result = str(value).strip()
    if not result or result.lower() in {"nan", "none", "null"}:
        return None
    return result.lower() if lower else result


def _utc(value: Any) -> pd.Timestamp | None:
    if value is None or pd.isna(value):
        return None
    timestamp = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(timestamp) else timestamp


def _at_or_before(frame: pd.DataFrame, column: str, cutoff: pd.Timestamp | None) -> pd.DataFrame:
    if cutoff is None or column not in frame.columns:
        return frame
    times = pd.to_datetime(frame[column], errors="coerce", utc=True)
    return frame.loc[times.notna() & (times <= cutoff)]


def _rows_for_users(frame: pd.DataFrame, user_ids: set[str]) -> pd.DataFrame:
    if not user_ids or "user_id" not in frame.columns:
        return frame.iloc[0:0].copy()
    normalized = frame["user_id"].map(lambda value: _clean(value, lower=True))
    wanted = {user_id.lower() for user_id in user_ids}
    return frame.loc[normalized.isin(wanted)].copy()


def _linked_to_identity(details: Any, user_ids: set[str], emails: set[str],
                        hashes: set[str], phones: set[str]) -> bool:
    text = _clean(details, lower=True) or ""
    if not text:
        return False
    if any(email in text for email in emails if email):
        return True
    # IDs are matched as whole tokens so user_01 cannot match user_010.
    for user_id in user_ids:
        if re.search(rf"(?<![\w]){re.escape(user_id.lower())}(?![\w])", text):
            return True
    for digest in hashes:
        if len(digest) >= 16 and digest.lower() in text:
            return True
    text_digits = re.sub(r"\D", "", text)
    return any((digits := re.sub(r"\D", "", phone)) and len(digits) >= 7 and digits in text_digits
               for phone in phones)


def _empty_identity(flag: str = "UNRESOLVED") -> IdentitySet:
    return IdentitySet((), frozenset(), frozenset(), frozenset(), frozenset(), None, frozenset({flag}))


def resolve(email: str, ds: Any, audit_at: Any, *, limit_history_to_audit_at: bool = True) -> IdentitySet:
    """Resolve current and historical identifiers for an email.

    By default, audit and identity-link events after ``audit_at`` are excluded.
    Set ``limit_history_to_audit_at=False`` to compare against the full history.
    """
    requested_email = _clean(email, lower=True)
    if not requested_email:
        return _empty_identity()

    identities = ds.user_identities
    audit = ds.user_audit_log
    activity = ds.system_activity
    cutoff = _utc(audit_at) if limit_history_to_audit_at else None
    audit_view = _at_or_before(audit, "event_time", cutoff)

    current_rows = ds.identities_by_email(requested_email)
    user_ids: list[str] = []
    for value in current_rows.get("user_id", pd.Series(dtype=object)):
        user_id = _clean(value)
        if user_id and user_id not in user_ids:
            user_ids.append(user_id)

    history_match = False
    if not user_ids and {"field_name", "old_value", "new_value", "user_id"}.issubset(audit_view.columns):
        email_rows = audit_view.loc[
            audit_view["field_name"].map(lambda v: _clean(v, lower=True)) == "email"
        ]
        matches = email_rows.loc[
            email_rows["old_value"].map(lambda v: _clean(v, lower=True)).eq(requested_email)
            | email_rows["new_value"].map(lambda v: _clean(v, lower=True)).eq(requested_email)
        ]
        for value in matches["user_id"]:
            user_id = _clean(value)
            if user_id and user_id not in user_ids:
                user_ids.append(user_id)
        history_match = bool(user_ids)

    if not user_ids:
        return _empty_identity()

    user_id_set = set(user_ids)
    identity_rows = _rows_for_users(identities, user_id_set)
    user_audit = _rows_for_users(audit_view, user_id_set)
    emails: set[str] = set()
    hashes: set[str] = set()
    phones: set[str] = set()

    if "email" in identity_rows:
        emails.update(v for v in (_clean(x, lower=True) for x in identity_rows["email"]) if v)
    if "email_hash" in identity_rows:
        hashes.update(v for v in (_clean(x, lower=True) for x in identity_rows["email_hash"]) if v)
    if "phone" in identity_rows:
        phones.update(v for v in (_clean(x) for x in identity_rows["phone"]) if v)

    for _, row in user_audit.iterrows():
        field_name = _clean(row.get("field_name"), lower=True)
        if field_name not in {"email", "email_hash", "phone"}:
            continue
        target = emails if field_name == "email" else hashes if field_name == "email_hash" else phones
        for column in ("old_value", "new_value"):
            value = _clean(row.get(column), lower=(field_name in {"email", "email_hash"}))
            if value:
                target.add(value)

    hashes.update(hashlib.sha256(value.encode("utf-8")).hexdigest() for value in emails)

    activity_view = _at_or_before(activity, "event_time", cutoff)
    links = activity_view.loc[
        activity_view.get("event_type", pd.Series(index=activity_view.index, dtype=object))
        .map(lambda v: _clean(v, lower=True)).eq("link_resource_identity")
    ]
    linked_resources = {
        resource_id
        for _, row in links.iterrows()
        if _linked_to_identity(row.get("details"), user_id_set, emails, hashes, phones)
        and (resource_id := _clean(row.get("resource_id")))
    }
    flags = {"AUDIT_HISTORY_MATCH"} if history_match else set()
    if len(user_ids) > 1:
        flags.add("AMBIGUOUS")
    return IdentitySet(
        tuple(user_ids), frozenset(emails), frozenset(hashes), frozenset(phones),
        frozenset(linked_resources), user_ids[0], frozenset(flags),
    )
