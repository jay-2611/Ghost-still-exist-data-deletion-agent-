"""Sample-templated intent classification with batched, fail-closed LLM fallback."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Iterable

import pandas as pd
from identity import resolve

# Editable policy list of limiting / explicit non-deletion phrases.
# Patterns are contextual so "copies to be deleted" is not treated as a copy request.
LIMITING_PHRASES: list[tuple[str, str]] = [
    ("English explicit negation", r"\b(?:not\s+(?:asking|requesting)\s+(?:for\s+)?(?:deletion|erasure|to\s+delete|to\s+erase)|not\s+a\s+request\s+to\s+(?:delete|erase)|do\s+not\s+(?:delete|erase|remove|close|cancel)|don't\s+(?:delete|erase|remove|close|cancel)|dont\s+(?:delete|erase|remove|close|cancel)|no\s+(?:deletion|erasure)\s+request)\b"),
    ("English retain or limit", r"\b(?:leave|keep|retain)\s+(?:the\s+|my\s+|this\s+)?(?:account|profile|order\s+history|purchase\s+history|receipts?|service\s+messages?)\b|\bmarketing\s+lists?\s+only\b|\b(?:information\s+request|request\s+for\s+information|send\s+(?:me\s+)?(?:a\s+)?copy|give\s+(?:me\s+)?(?:a\s+)?copy|download\s+(?:my|the|a|an)\s+(?:account|personal|data|information|invoice))\b|\b(?:update|replace|change|stop|unsubscribe|opt\s+out|reset|recover)\s+(?:my|the|this|email|phone|number|profile|login|account|promotional|marketing)\b|\bcorrect\s+(?:my|the|it|name|email|number|phone|spelling|profile|account)\b"),
    ("Spanish explicit negation", r"\b(?:no\s+(?:solicito|pido|quiero)\s+(?:la\s+)?(?:eliminaci[oó]n|supresi[oó]n|borrar|eliminar)|no\s+(?:eliminar|borrar|suprimir)|sin\s+(?:eliminar|borrar|suprimir))\b"),
    ("Spanish scope", r"\b(?:dejar\s+la\s+cuenta|mantener\s+(?:la\s+)?cuenta|todav[ií]a\s+(?:quiero|uso|necesito)|solo|solamente|solicitud\s+de\s+informaci[oó]n|copia|descargar|actualizar|corregir|reemplazar|cambiar|detener|cancelar\s+los\s+correos)\b"),
    ("French explicit negation", r"\bne\b.{0,25}\b(?:demande|souhaite|veux)\b.{0,10}\bpas\b.{0,40}\b(?:suppression|effacement|supprimer|effacer)\b|\bne\s+pas\s+(?:supprimer|effacer)\b|\bsans\s+(?:supprimer|effacer)\b"),
    ("French scope", r"\b(?:laisser\s+(?:le\s+)?compte|garder\s+(?:le\s+)?compte|toujours\s+(?:utiliser|vouloir|avoir\s+besoin)|uniquement|seulement|demande\s+d'information|copie|t[eé]l[eé]charger|mettre\s+[aà]\s+jour|corriger|remplacer|modifier|arr[eê]ter|d[eé]sinscrire)\b"),
    ("Portuguese explicit negation", r"\b(?:n[aã]o\s+(?:solicito|pe[cç]o|quero)\s+(?:a\s+)?(?:exclus[aã]o|elimina[cç][aã]o)|n[aã]o\s+(?:excluir|apagar)|sem\s+(?:excluir|apagar))\b"),
    ("Portuguese scope", r"\b(?:deixar\s+(?:a\s+)?conta|manter\s+(?:a\s+)?conta|ainda\s+(?:quero|uso|preciso)|somente|apenas|pedido\s+de\s+informa[cç][aã]o|c[oó]pia|baixar|atualizar|corrigir|substituir|alterar|parar|cancelar)\b"),
    ("Korean explicit negation", r"(?:삭제를\s*(?:요청|원)(?:하는\s*것이\s*)?아닙니다|삭제를\s*(?:요청|원)하지\s*않|삭제하지\s*마)"),
    ("Korean scope", r"(?:계정.{0,8}(?:유지|그대로)|계속\s*(?:사용|필요)|정보\s*(?:요청|사본)|다운로드|업데이트|수정|변경|중지|만\s*필요)"),
    ("Japanese explicit negation", r"(?:削除を(?:依頼|希望)していません|削除しないで)"),
    ("Japanese scope", r"(?:アカウント.{0,8}(?:維持|そのまま)|まだ(?:使いたい|利用|必要)|情報開示請求|コピー|ダウンロード|更新|訂正|変更|停止|だけ|のみ)"),
]
_LIMITS = [(label, re.compile(pattern, re.I | re.S)) for label, pattern in LIMITING_PHRASES]
_TEMPLATE_THRESHOLD = 0.65
_BATCH_SIZE = 40
_FIRST_SENTENCE_NEGATION = re.compile(
    "|".join(pattern for label, pattern in LIMITING_PHRASES if "explicit negation" in label),
    re.IGNORECASE | re.DOTALL,
)


def _get(case: Any, field: str, default: Any = None) -> Any:
    if isinstance(case, dict):
        return case.get(field, default)
    if isinstance(case, pd.Series):
        return case.get(field, default)
    return getattr(case, field, default)


def _text(value: Any) -> str:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return ""
    return str(value).strip()


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).strip()


def _first_sentence(value: str) -> str:
    match = re.search(r"[.!?。！？](?:\s|$)|\n", value.strip())
    return value[:match.start()].strip() if match else value.strip()


def _templates(ds: Any) -> tuple[str, ...]:
    samples = getattr(ds, "sample_deletion_requests", pd.DataFrame())
    if "request_text" not in samples:
        return ()
    return tuple(sorted({_normalize(_first_sentence(_text(v))) for v in samples.request_text if _text(v)}))


def _template_match(text: str, templates: tuple[str, ...]) -> bool:
    first_sentence = _first_sentence(text)
    if _FIRST_SENTENCE_NEGATION.search(first_sentence):
        return False
    first = _normalize(first_sentence)
    if not first:
        return False
    if first in templates:
        return True
    return max((SequenceMatcher(None, first, template).ratio() for template in templates), default=0.0) >= _TEMPLATE_THRESHOLD


def _limiter(text: str) -> tuple[str, str] | None:
    for label, pattern in _LIMITS:
        match = pattern.search(text)
        if match:
            return label, match.group(0)
    return None


def _fact_matches(fact: Any, identity: Any) -> bool:
    identity_values = {str(v).strip().casefold() for field in ("emails", "hashes", "user_ids")
                       for v in getattr(identity, field, ()) if v}
    fact_values = {str(v).strip().casefold() for field in ("emails", "hashes", "user_ids")
                   for v in getattr(fact, field, ()) if v}
    if identity_values & fact_values:
        return True
    raw = str(getattr(fact, "raw_ref", "")).casefold()
    if any(re.search(rf"(?<![\w.+-]){re.escape(v)}(?![\w.+-])", raw) for v in identity_values):
        return True
    raw_digits = re.sub(r"\D", "", raw)
    return any((digits := re.sub(r"\D", "", str(phone))) and len(digits) >= 7 and digits in raw_digits
               for phone in identity.phones)


def _event(case: Any, ds: Any) -> tuple[bool, str] | None:
    email, audit_at = _text(_get(case, "email")), _get(case, "audit_at")
    identity = resolve(email, ds, audit_at)
    if not identity.user_ids:
        return None
    activity = getattr(ds, "system_activity", pd.DataFrame())
    if not {"event_type", "event_time", "details"}.issubset(activity.columns):
        return None
    rows = activity.loc[activity.event_type.astype(str).str.strip().str.upper().eq("CLASSIFY_REQUEST")].copy()
    times = pd.to_datetime(rows.event_time, errors="coerce", utc=True)
    cutoff = pd.to_datetime(audit_at, errors="coerce", utc=True)
    if pd.notna(cutoff):
        rows = rows.loc[times.notna() & (times <= cutoff)]
    resources = {str(v).strip().casefold() for v in (_get(case, "resource_ids", ()) or ()) if str(v).strip()}
    resources.update(str(v).strip().casefold() for v in identity.linked_resources)

    ledger = getattr(ds, "ledger", None)
    fact_index = getattr(ds, "_intent_fact_index", None)
    if ledger is not None and fact_index is None:
        fact_index = {}
        for fact in getattr(ledger, "facts", ()):
            rid = str(getattr(fact, "resource_id", "")).strip().casefold()
            if rid:
                fact_index.setdefault(rid, []).append(fact)
        try:
            ds._intent_fact_index = fact_index
        except (AttributeError, TypeError):
            pass
    for _, row in rows.iterrows():
        rid = _text(row.get("resource_id", "")).casefold()
        linked = rid in resources
        if not linked and fact_index is not None:
            for fact in fact_index.get(rid, ()):
                observed = pd.to_datetime(fact.observed_at, errors="coerce", utc=True)
                if (pd.isna(cutoff) or (pd.notna(observed) and observed <= cutoff)) and _fact_matches(fact, identity):
                    linked = True
                    break
        details = _text(row.get("details", ""))
        details_lower = details.casefold()
        linked = linked or any(email.casefold() in details_lower for email in identity.emails if email)
        linked = linked or any(re.search(rf"(?<![\w]){re.escape(str(uid).casefold())}(?![\w])", details_lower)
                               for uid in identity.user_ids)
        linked = linked or any(len(digest) >= 16 and digest.casefold() in details_lower
                               for digest in identity.hashes)
        detail_digits = re.sub(r"\D", "", details_lower)
        linked = linked or any(
            (digits := re.sub(r"\D", "", str(phone)))
            and len(digits) >= 7 and digits in detail_digits
            for phone in identity.phones
        )
        if linked and re.search(r"\bnon[- ]deletion\b|\bno\s+destructive\s+action\b", details, re.I):
            return False, f"Linked CLASSIFY_REQUEST {row.get('activity_id', '')} says non-deletion."
    return None


def _deterministic(case: Any, ds: Any, templates: tuple[str, ...]) -> tuple[bool, str, str] | None:
    event = _event(case, ds)
    if event:
        return event[0], "EVENT", event[1]
    text = _text(_get(case, "request_text"))
    templated = _template_match(text, templates)
    limiter = _limiter(text)
    if templated and limiter is None:
        return True, "TEMPLATE", "First sentence matches a labeled deletion template; no limiting phrase found."
    if limiter is not None and not templated:
        return False, "NEGATION", f"Non-deletion or limiting phrase ({limiter[0]}: {limiter[1]})."
    return None


def _batch_schema(ids: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": {"items": {"type": "array", "minItems": len(ids), "maxItems": len(ids),
            "items": {"type": "object", "properties": {"id": {"type": "string", "enum": ids},
                "deletion_requested": {"type": "boolean"}, "reason": {"type": "string"}},
                "required": ["id", "deletion_requested", "reason"], "additionalProperties": False}}},
            "required": ["items"], "additionalProperties": False}


def _validate_batch(response: Any, expected: set[str]) -> dict[str, tuple[bool, str]]:
    if not isinstance(response, dict) or not isinstance(response.get("items"), list):
        raise ValueError("Expected an items array")
    result: dict[str, tuple[bool, str]] = {}
    for item in response["items"]:
        if not isinstance(item, dict):
            raise ValueError("Batch item is not an object")
        item_id, decision, reason = item.get("id"), item.get("deletion_requested"), item.get("reason")
        if item_id not in expected or item_id in result:
            raise ValueError("Unknown or duplicate batch id")
        if not isinstance(decision, bool) or not isinstance(reason, str):
            raise ValueError("Invalid batch item fields")
        result[item_id] = (decision, reason.strip())
    if set(result) != expected:
        raise ValueError("Each batch id must appear exactly once")
    return result


def _llm_classify(texts: list[str], llm: Any, ds: Any) -> dict[str, tuple[bool, str]]:
    unique = {_normalize(text): text for text in texts}
    rows = sorted(unique.items())
    decisions: dict[str, tuple[bool, str]] = {}
    calls = 0
    for start in range(0, len(rows), _BATCH_SIZE):
        batch = rows[start:start + _BATCH_SIZE]
        ids = [hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16] for norm, _ in batch]
        expected = set(ids)
        prompt = ("Classify each request as an explicit request to delete or erase the person's account or data. "
                  "Return exactly one {id, deletion_requested, reason} item per supplied id.\n\n" +
                  "\n\n".join(f"id: {item_id}\nrequest: {text}" for item_id, (_, text) in zip(ids, batch)))
        schema = _batch_schema(ids)
        try:
            calls += 1
            response = llm.generate_json(prompt, schema)
            parsed = _validate_batch(response, expected)
            for (norm, _), item_id in zip(batch, ids):
                decisions[norm] = parsed[item_id]
        except Exception as exc:
            fallback = f"NEEDS_REVIEW: LLM unavailable or invalid batch ({type(exc).__name__}); defaulted to NOT_APPLICABLE."
            for norm, _ in batch:
                decisions[norm] = (False, fallback)
    try:
        ds._intent_llm_call_count = getattr(ds, "_intent_llm_call_count", 0) + calls
    except (AttributeError, TypeError):
        pass
    return decisions


def classify_many(cases: Iterable[Any], ds: Any, llm: Any) -> list[tuple[bool, str, str]]:
    """Classify cases and submit unique ambiguous texts in batches of at most 40."""
    rows = list(cases)
    templates = _templates(ds)
    results: list[tuple[bool, str, str] | None] = [_deterministic(case, ds, templates) for case in rows]
    pending = [i for i, result in enumerate(results) if result is None]
    texts = [_text(_get(rows[i], "request_text")) for i in pending]
    if texts:
        llm_results = _llm_classify(texts, llm, ds) if llm is not None else {}
        for i, text in zip(pending, texts):
            decision, reason = llm_results.get(_normalize(text),
                (False, "NEEDS_REVIEW: no LLMClient; defaulted to NOT_APPLICABLE."))
            results[i] = (decision, "LLM", reason)
    return [result for result in results if result is not None]


def _case_key(case: Any) -> tuple[str, str, str]:
    return (_text(_get(case, "case_id")), _text(_get(case, "email")).casefold(),
            _normalize(_text(_get(case, "request_text"))))


def classify(case: Any, ds: Any, llm: Any) -> tuple[bool, str, str]:
    """Classify one row; the first call batches all requests already in Dataset."""
    key = _case_key(case)
    cache = getattr(ds, "_intent_case_results", None)
    if cache is None:
        rows: list[Any] = []
        for name in ("deletion_requests", "sample_deletion_requests"):
            frame = getattr(ds, name, pd.DataFrame())
            if not frame.empty:
                rows.extend(frame.itertuples(index=False))
        if rows:
            output = classify_many(rows, ds, llm)
            cache = {_case_key(row): result for row, result in zip(rows, output)}
        else:
            cache = {}
        try:
            ds._intent_case_results = cache
        except (AttributeError, TypeError):
            pass
    if key in cache:
        return cache[key]
    return classify_many([case], ds, llm)[0]
