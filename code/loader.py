from __future__ import annotations

from collections import Counter, defaultdict
import json as _stdjson
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = REPO_ROOT / "dataset"
EVIDENCE_DIR = DATASET_DIR / "evidence"
CACHE_DIR = REPO_ROOT / ".cache"
OUTPUT_PATH = REPO_ROOT / "output.csv"

CSV_FILES = {
    "deletion_requests": "deletion_requests.csv",
    "sample_deletion_requests": "sample_deletion_requests.csv",
    "sample_output": "sample_output.csv",
    "user_identities": "user_identities.csv",
    "user_audit_log": "user_audit_log.csv",
    "system_activity": "system_activity.csv",
    "deletion_rules": "deletion_rules.csv",
    "evidence_files": "evidence_files.csv",
}
RESOURCE_PREFIXES = (
    "account_", "search_", "support_", "analytics_", "audit_record_",
    "data_flow_", "backup_", "export_", "tombstone_", "cache_",
    "email_delivery_", "legal_hold_", "object_", "marketing_",
)
UNVERIFIED_PREFIXES = ("legal_hold_", "object_", "marketing_", "cache_", "email_delivery_")


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Strip strings, normalize emails, and parse timestamp-like columns as UTC."""
    frame = frame.copy()
    for column in frame.columns:
        name = str(column).lower()
        if any(token in name for token in ("_at", "_time", "timestamp")):
            parsed = pd.to_datetime(frame[column], errors="coerce", utc=True)
            if parsed.notna().any():
                frame[column] = parsed
                continue
        if pd.api.types.is_object_dtype(frame[column]) or pd.api.types.is_string_dtype(frame[column]):
            values = frame[column].map(lambda value: value.strip() if isinstance(value, str) else value)
            if "email" in name:
                values = values.map(lambda value: value.lower() if isinstance(value, str) else value)
            frame[column] = values
    return frame


def _key(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text.lower() if text else None


def _select(frame: pd.DataFrame, column: str, value: object) -> pd.DataFrame:
    key = _key(value)
    if key is None or column not in frame:
        return frame.iloc[0:0].copy()
    return frame.loc[frame[column].map(_key) == key].copy()


@dataclass
class Dataset:
    deletion_requests: pd.DataFrame
    sample_deletion_requests: pd.DataFrame
    sample_output: pd.DataFrame
    user_identities: pd.DataFrame
    user_audit_log: pd.DataFrame
    system_activity: pd.DataFrame
    deletion_rules: pd.DataFrame
    evidence_files: pd.DataFrame
    dataset_dir: Path = DATASET_DIR
    # Fallback only: parsed evidence systems (SQL snapshot_scope.origin_system,
    # JSON data_store, record_json origin_system, and TXT system) take precedence.
    PREFIX_TO_SYSTEM: dict[str, str] = field(default_factory=dict)
    prefix_step_counts: dict[str, int] = field(default_factory=dict)
    sample_output_step_count: int = 0
    UNVERIFIED_PREFIXES: tuple[str, ...] = UNVERIFIED_PREFIXES
    prefix_system_agreement_rate: float = 0.0
    _evidence_index: dict[str, int] = field(default_factory=dict, repr=False)
    _identity_indexes: dict[str, dict[str, list[int]]] = field(default_factory=dict, repr=False)

    @property
    def RESOURCE_PREFIX_TO_SYSTEM(self) -> dict[str, str]:
        """Compatibility alias for the sample-derived fallback system map."""
        return self.PREFIX_TO_SYSTEM

    def evidence_by_id(self, file_id: object) -> pd.DataFrame:
        key = _key(file_id)
        row = self._evidence_index.get(key) if key else None
        if row is None:
            return self.evidence_files.iloc[0:0].copy()
        return self.evidence_files.iloc[[row]].copy()

    def activity_for_resource(self, rid: object) -> pd.DataFrame:
        return _select(self.system_activity, "resource_id", rid)

    def activity_by_type(self, t: object) -> pd.DataFrame:
        return _select(self.system_activity, "event_type", t)

    def rules_by_category(self, c: object) -> pd.DataFrame:
        return _select(self.deletion_rules, "category", c)

    def _identity_lookup(self, kind: str, value: object) -> pd.DataFrame:
        key = _key(value)
        matches = self._identity_indexes.get(kind, {}).get(key, []) if key else []
        if not matches:
            return self.user_identities.iloc[0:0].copy()
        return self.user_identities.iloc[matches].copy()

    def identities_by_email(self, value: object) -> pd.DataFrame:
        return self._identity_lookup("email", value)

    def identities_by_hash(self, value: object) -> pd.DataFrame:
        return self._identity_lookup("hash", value)

    def identities_by_phone(self, value: object) -> pd.DataFrame:
        return self._identity_lookup("phone", value)

    def identities_by_user_id(self, value: object) -> pd.DataFrame:
        return self._identity_lookup("user_id", value)


def _make_identity_indexes(frame: pd.DataFrame) -> dict[str, dict[str, list[int]]]:
    aliases = {
        "email": ("email", "emails", "old_email", "new_email"),
        "hash": ("email_hash", "hash", "hashes"),
        "phone": ("phone", "phones"),
        "user_id": ("user_id", "user_ids"),
    }
    indexes: dict[str, dict[str, list[int]]] = {}
    for kind, columns in aliases.items():
        found: dict[str, list[int]] = defaultdict(list)
        for column in columns:
            if column not in frame:
                continue
            for row_no, value in enumerate(frame[column]):
                key = _key(value)
                if key is not None and row_no not in found[key]:
                    found[key].append(row_no)
        indexes[kind] = dict(found)
    return indexes


def _resource_prefix(resource_id: object) -> str | None:
    rid = _key(resource_id)
    if not rid:
        return None
    return next((prefix for prefix in sorted(RESOURCE_PREFIXES, key=len, reverse=True)
                 if rid.startswith(prefix)), None)


def _build_prefix_map(sample_output: pd.DataFrame) -> tuple[dict[str, str], dict[str, int], int, float]:
    """Build the fallback map from solved sample steps; activity is never consulted."""
    systems: dict[str, set[str]] = defaultdict(set)
    counts: Counter[str] = Counter()
    total_steps = 0
    if "steps_json" not in sample_output.columns:
        raise ValueError("sample_output.csv must contain steps_json")
    for row_no, raw_steps in enumerate(sample_output["steps_json"]):
        if pd.isna(raw_steps):
            continue
        try:
            steps = _stdjson.loads(raw_steps)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid steps_json in sample_output row {row_no}") from exc
        if not isinstance(steps, list):
            raise ValueError(f"steps_json in sample_output row {row_no} must be a JSON list")
        for step in steps:
            if not isinstance(step, dict):
                continue
            total_steps += 1
            prefix = _resource_prefix(step.get("resource_id"))
            system_id = _key(step.get("system_id"))
            if prefix and system_id:
                systems[prefix].add(system_id)
                counts[prefix] += 1
    ambiguous = {prefix: sorted(values) for prefix, values in systems.items() if len(values) != 1}
    if ambiguous:
        raise ValueError(f"sample_output prefixes map to multiple systems: {ambiguous}")
    mapping = {prefix: next(iter(values)) for prefix, values in sorted(systems.items())}
    mapped_steps = sum(counts.values())
    agreement = mapped_steps / total_steps if total_steps else 0.0
    return mapping, dict(sorted(counts.items())), total_steps, agreement


def activity_target_distribution(activity: pd.DataFrame, prefixes: tuple[str, ...] | None = None) -> pd.DataFrame:
    """Summarize activity routing by resource prefix and event type for diagnostics."""
    required = {"resource_id", "event_type", "source_system", "target_system"}
    columns = ["prefix", "event_type", "source_system", "target_system", "rows"]
    if not required.issubset(activity.columns):
        return pd.DataFrame(columns=columns)
    rows = activity[["resource_id", "event_type", "source_system", "target_system"]].copy()
    rows["prefix"] = rows["resource_id"].map(_resource_prefix)
    if prefixes is not None:
        rows = rows.loc[rows["prefix"].isin(prefixes)]
    return (rows.dropna(subset=["prefix"])
            .groupby(["prefix", "event_type", "source_system", "target_system"], dropna=False)
            .size().rename("rows").reset_index()[columns]
            .sort_values(columns[:-1], kind="stable").reset_index(drop=True))


def load_all(dataset_dir: str | Path) -> Dataset:
    """Read the eight dataset CSV files and prepare lookup helpers."""
    root = Path(dataset_dir).expanduser().resolve()
    frames = {
        name: _normalize_frame(pd.read_csv(root / filename, keep_default_na=True))
        for name, filename in CSV_FILES.items()
    }
    mapping, prefix_counts, sample_step_count, agreement = _build_prefix_map(frames["sample_output"])
    result = Dataset(**frames, dataset_dir=root,
                     PREFIX_TO_SYSTEM=mapping,
                     prefix_step_counts=prefix_counts,
                     sample_output_step_count=sample_step_count,
                     prefix_system_agreement_rate=agreement)
    if "file_id" in result.evidence_files:
        for row_no, value in enumerate(result.evidence_files["file_id"]):
            key = _key(value)
            if key is not None:
                result._evidence_index[key] = row_no
    result._identity_indexes = _make_identity_indexes(result.user_identities)
    return result
