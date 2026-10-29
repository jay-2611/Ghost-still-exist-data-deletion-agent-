"""Evidence parser registry and shared fact types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping


PRESENT = "PRESENT"
ABSENT = "ABSENT"
IDENTIFIABLE = "IDENTIFIABLE"
ANONYMIZED = "ANONYMIZED"
REDACTED = "REDACTED"
ACTIVE = "ACTIVE"
DISABLED = "DISABLED"
BLOCKED = "BLOCKED"
RETAINED = "RETAINED"
UNKNOWN = "UNKNOWN"
STATES = frozenset({PRESENT, ABSENT, IDENTIFIABLE, ANONYMIZED, REDACTED,
                    ACTIVE, DISABLED, BLOCKED, RETAINED, UNKNOWN})


@dataclass(frozen=True)
class Fact:
    file_id: str
    observed_at: datetime
    system_id: str
    resource_id: str
    category: str
    state: str
    emails: tuple[str, ...]
    hashes: tuple[str, ...]
    phones: tuple[str, ...]
    user_ids: tuple[str, ...]
    names: tuple[str, ...]
    topology: str | None
    source_kind: str
    raw_ref: str
    flags: tuple[str, ...] = ()


Parser = Callable[[Mapping[str, Any], str | Path], tuple[list[Fact], dict[str, datetime]]]
PARSER_REGISTRY: dict[str, Parser] = {}


def register_parser(extension: str, parser: Parser) -> None:
    PARSER_REGISTRY[extension.lower() if extension.startswith(".") else f".{extension.lower()}"] = parser


def _value(row: Any, key: str, default: Any = None) -> Any:
    if hasattr(row, "get"):
        value = row.get(key, default)
        return default if value is None else value
    return default


def parse_file(file_row: Mapping[str, Any], dataset_dir: str | Path, llm: Any = None) -> tuple[list[Fact], dict[str, datetime]]:
    """Dispatch an evidence manifest row to the parser registered for its extension."""
    path = Path(str(_value(file_row, "file_path", "")))
    parser = PARSER_REGISTRY.get(path.suffix.lower())
    if parser is None:
        raise ValueError(f"No evidence parser registered for {path.suffix or '<no extension>'}")
    if path.suffix.lower() in {".png", ".pdf"}:
        return parser(file_row, dataset_dir, llm=llm)
    return parser(file_row, dataset_dir)


from parsers.sql import parse as _parse_sql
from parsers.json import parse as _parse_json
from parsers.txt import parse as _parse_txt
from parsers.log import parse as _parse_log
from parsers.image import parse as _parse_image
from parsers.pdf import parse as _parse_pdf

register_parser(".sql", _parse_sql)
register_parser(".json", _parse_json)
register_parser(".txt", _parse_txt)
register_parser(".log", _parse_log)
register_parser(".png", _parse_image)
register_parser(".pdf", _parse_pdf)
