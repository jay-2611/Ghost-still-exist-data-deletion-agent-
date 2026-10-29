from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sys
import threading
import time
from collections import deque
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import requests


LOGGER = logging.getLogger(__name__)
def _repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "AGENTS.md").is_file():
            return candidate
    raise FileNotFoundError(f"Could not find AGENTS.md above {start}")


REPO_ROOT = _repo_root(Path(__file__).resolve().parent)
DEFAULT_CACHE_DIR = REPO_ROOT / ".cache" / "llm"
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GEMINI_MODELS = ("gemini-3.1-flash-lite",)
DEFAULT_GEMINI_MODEL = DEFAULT_GEMINI_MODELS[0]
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
REQUESTS_PER_MINUTE = 8
MAX_CONCURRENT_LLM_CALLS = 1
# USD per million tokens. Configure current Gemini prices when supplying a custom model list.
DEFAULT_PRICE_TABLE = {
    ("groq", "openai/gpt-oss-20b"): (0.075, 0.30),
}


class _SlidingWindowRateLimiter:
    """Process-wide fixed rolling-window budget; each network attempt consumes a slot."""

    def __init__(self, requests_per_minute: int) -> None:
        if requests_per_minute < 1:
            raise ValueError("requests_per_minute must be positive")
        self.limit = requests_per_minute
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= 60.0:
                    self._calls.popleft()
                if len(self._calls) < self.limit:
                    self._calls.append(now)
                    return
                wait = max(0.0, 60.0 - (now - self._calls[0]))
            time.sleep(wait)


_GLOBAL_RATE_LIMITER = _SlidingWindowRateLimiter(REQUESTS_PER_MINUTE)
_GLOBAL_CALL_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_LLM_CALLS)


@dataclass(frozen=True)
class UsageRecord:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency: float
    cached: bool
    request_id: int | None = None


class UsageTracker:
    """In-memory per-call usage records and a Markdown cost summary."""

    def __init__(self, price_table: Mapping[Any, Any] | None = None) -> None:
        self.records: list[UsageRecord] = []
        self.price_table = dict(DEFAULT_PRICE_TABLE if price_table is None else price_table)
        self._request_count = 0

    def begin_request(self) -> int:
        """Count and identify one logical generate_json request."""
        self._request_count += 1
        return self._request_count

    def record(self, provider: str, model: str, input_tokens: int = 0,
               output_tokens: int = 0, latency: float = 0.0,
               cached: bool = False, request_id: int | None = None) -> None:
        self.records.append(UsageRecord(
            provider=str(provider), model=str(model),
            input_tokens=max(0, int(input_tokens or 0)),
            output_tokens=max(0, int(output_tokens or 0)),
            latency=max(0.0, float(latency or 0.0)), cached=bool(cached),
            request_id=request_id,
        ))

    @property
    def request_count(self) -> int:
        return self._request_count if self._request_count else len(self.records)

    def _price(self, provider: str, model: str) -> tuple[float, float] | None:
        value = self.price_table.get((provider, model), self.price_table.get(f"{provider}/{model}", self.price_table.get(model)))
        if value is None:
            return None
        if isinstance(value, Mapping):
            input_price = value.get("input_per_million", value.get("input"))
            output_price = value.get("output_per_million", value.get("output"))
            if input_price is None or output_price is None:
                return None
            return float(input_price), float(output_price)
        if isinstance(value, (tuple, list)) and len(value) == 2:
            return float(value[0]), float(value[1])
        raise ValueError(f"Invalid price table entry for {provider}/{model}")

    def _cost(self, records: list[UsageRecord]) -> float | None:
        total = 0.0
        for record in records:
            if record.input_tokens == 0 and record.output_tokens == 0:
                continue
            price = self._price(record.provider, record.model)
            if price is None:
                return None
            total += (record.input_tokens * price[0] + record.output_tokens * price[1]) / 1_000_000
        return total

    def render_markdown(self) -> str:
        groups: dict[tuple[str, str], list[UsageRecord]] = defaultdict(list)
        for record in self.records:
            groups[(record.provider, record.model)].append(record)
        total_input = sum(record.input_tokens for record in self.records)
        total_output = sum(record.output_tokens for record in self.records)
        denominator = max(1, self.request_count)
        lines = [
            "# LLM Usage Report", "",
            f"Requests: {self.request_count}", "",
            "| Provider | Model | Calls | Cache hits | Live input | Live output | Replayed input | Replayed output | Total input | Total output | Avg tokens/request | Avg latency (s) | Estimated cost (USD) |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for (provider, model), records in sorted(groups.items()):
            live_inputs = sum(r.input_tokens for r in records if not r.cached)
            live_outputs = sum(r.output_tokens for r in records if not r.cached)
            replay_inputs = sum(r.input_tokens for r in records if r.cached)
            replay_outputs = sum(r.output_tokens for r in records if r.cached)
            inputs, outputs = live_inputs + replay_inputs, live_outputs + replay_outputs
            cost = self._cost(records)
            cost_text = f"${cost:.6f}" if cost is not None else "unconfigured"
            request_ids = {r.request_id for r in records if r.request_id is not None}
            model_request_count = len(request_ids) or len(records)
            average_latency = sum(r.latency for r in records) / len(records)
            lines.append(
                f"| {provider} | {model} | {len(records)} | {sum(r.cached for r in records)} | "
                f"{live_inputs} | {live_outputs} | {replay_inputs} | {replay_outputs} | "
                f"{inputs} | {outputs} | {(inputs + outputs) / model_request_count:.2f} | "
                f"{average_latency:.3f} | {cost_text} |"
            )
        live_input = sum(r.input_tokens for r in self.records if not r.cached)
        live_output = sum(r.output_tokens for r in self.records if not r.cached)
        replay_input = sum(r.input_tokens for r in self.records if r.cached)
        replay_output = sum(r.output_tokens for r in self.records if r.cached)
        overall_cost = self._cost(self.records)
        cost_text = f"${overall_cost:.6f}" if overall_cost is not None else "unconfigured"
        overall_latency = sum(r.latency for r in self.records) / denominator
        lines.append(
            f"| **Overall** | — | {self.request_count} | {sum(r.cached for r in self.records)} | "
            f"{live_input} | {live_output} | {replay_input} | {replay_output} | "
            f"{total_input} | {total_output} | {(total_input + total_output) / denominator:.2f} | "
            f"{overall_latency:.3f} | {cost_text} |"
        )
        lines.extend(["", "Cache-replayed token counts reflect the original live request and are separated from live tokens. No-LLM calls record zero tokens. Costs use the configured USD-per-million-token price table; unconfigured models are shown as `unconfigured`."])
        return "\n".join(lines)

    def write_markdown(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.render_markdown() + "\n", encoding="utf-8")
        return target


def _schema_error(value: Any, schema: Mapping[str, Any], path: str = "$", depth: int = 0) -> str | None:
    if depth > 80:
        return f"{path}: schema nesting is too deep"
    if not isinstance(schema, Mapping):
        return f"{path}: invalid schema"
    expected = schema.get("type")
    if isinstance(expected, list):
        allowed = expected
    elif expected is None:
        allowed = []
    else:
        allowed = [expected]
    if allowed:
        matches = False
        for kind in allowed:
            if kind == "null" and value is None:
                matches = True
            elif kind == "object" and isinstance(value, dict):
                matches = True
            elif kind == "array" and isinstance(value, list):
                matches = True
            elif kind == "string" and isinstance(value, str):
                matches = True
            elif kind == "integer" and isinstance(value, int) and not isinstance(value, bool):
                matches = True
            elif kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
                matches = True
            elif kind == "boolean" and isinstance(value, bool):
                matches = True
        if not matches:
            return f"{path}: expected {allowed}, got {type(value).__name__}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}: value is not in enum"
    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                return f"{path}.{key}: required property is missing"
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = set(value) - set(properties)
            if extras:
                return f"{path}: unexpected properties {sorted(extras)}"
        for key, child in properties.items():
            if key in value:
                error = _schema_error(value[key], child, f"{path}.{key}", depth + 1)
                if error:
                    return error
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            return f"{path}: fewer than minItems"
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return f"{path}: more than maxItems"
        if "items" in schema:
            for index, item in enumerate(value):
                error = _schema_error(item, schema["items"], f"{path}[{index}]", depth + 1)
                if error:
                    return error
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            return f"{path}: shorter than minLength"
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            return f"{path}: longer than maxLength"
    return None


def _load_dotenv(path: Path) -> bool:
    """Load missing environment keys from .env without overriding the process env."""
    if not path.is_file():
        return False
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None
    if load_dotenv is not None:
        load_dotenv(dotenv_path=path, override=False)
        return True
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value
    return True


class MissingAPIKeyError(RuntimeError):
    """Raised when no supported provider credential is configured."""


class LLMRequestError(RuntimeError):
    """Raised when configured providers cannot complete a live request."""

    def __init__(self, message: str, *, error_class: str | None = None,
                 http_status: int | None = None, network_blocked: bool = False) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.http_status = http_status
        self.network_blocked = network_blocked


def _status_code(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _diagnostic_error(exc: BaseException, status: int | None) -> str:
    error_class = type(exc).__name__
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return f"{error_class} (HTTP status: none; network unavailable or blocked)"
    if status in {401, 403}:
        return f"{error_class} (HTTP status: {status}; bad key)"
    response = getattr(exc, "response", None)
    response_text = str(getattr(response, "text", "")).lower()
    message = str(exc).lower()
    if status == 404 or (status == 400 and "model" in response_text + message and
                         "not found" in response_text + message):
        return f"{error_class} (HTTP status: {status}; model not found)"
    if status == 429:
        return f"{error_class} (HTTP status: 429; rate limit)"
    return f"{error_class} (HTTP status: {status if status is not None else 'none'})"


def _media(file: Any) -> tuple[bytes, str] | None:
    if file is None:
        return None
    name = ""
    if isinstance(file, (str, Path)):
        path = Path(file)
        name = path.name.lower()
        data = path.read_bytes()
    elif isinstance(file, tuple) and len(file) == 2:
        data, mime = file
        data = bytes(data)
        return data, str(mime)
    else:
        data = bytes(file)
    if data.startswith(b"%PDF"):
        mime = "application/pdf"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif name.endswith(".pdf"):
        mime = "application/pdf"
    elif name.endswith(('.jpg', '.jpeg')):
        mime = "image/jpeg"
    elif name.endswith(".webp"):
        mime = "image/webp"
    else:
        mime = "image/png"
    return data, mime


class LLMClient:
    """Gemini-first JSON client with Groq fallback, validation, cache, and usage tracking."""

    def __init__(self, usage_tracker: UsageTracker | None = None,
                 cache_dir: str | Path | None = None,
                 price_table: Mapping[Any, Any] | None = None,
                 no_llm: bool | None = None,
                 gemini_model: str | None = None,
                 gemini_models: tuple[str, ...] | list[str] | None = None,
                 groq_model: str | None = None,
                 timeout: float = 60.0,
                 max_429_retries: int = 3,
                 backoff_base: float = 0.5,
                 sleeper: Callable[[float], None] = time.sleep) -> None:
        self.env_file = REPO_ROOT / ".env"
        self.env_file_found = _load_dotenv(self.env_file)
        self.usage = usage_tracker or UsageTracker(price_table)
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.no_llm = ("--no-llm" in sys.argv) if no_llm is None else bool(no_llm)
        if gemini_models:
            self.gemini_models = tuple(gemini_models)
        elif gemini_model:
            self.gemini_models = (gemini_model,)
        else:
            self.gemini_models = DEFAULT_GEMINI_MODELS
        self.gemini_model = self.gemini_models[0]
        self.groq_model = groq_model or os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)
        self.timeout = timeout
        self.max_429_retries = max(0, max_429_retries)
        self.backoff_base = max(0.0, backoff_base)
        self._sleep = sleeper

    def _providers(self) -> list[tuple[str, str, str | None]]:
        # Include keyless entries so a valid disk-cache result can still be read
        # without credentials; live calls are skipped when their key is missing.
        gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("LLM_API_KEY")
        return [*(("gemini", model, gemini_key) for model in self.gemini_models),
                ("groq", self.groq_model, os.getenv("GROQ_API_KEY"))]

    def selected_provider_model(self) -> tuple[str | None, str | None]:
        for provider, model, key in self._providers():
            if key:
                return provider, model
        return None, None

    def diagnostic_model_checks(self, prompt: str, schema: Mapping[str, Any]) -> list[tuple[str, str]]:
        """Make one small live call per configured model, returning safe summaries."""
        results: list[tuple[str, str]] = []
        for provider, model, key in self._providers():
            label = f"{provider}/{model}"
            if not key:
                results.append((label, "MissingAPIKeyError (HTTP status: none)"))
                continue
            request_id = self.usage.begin_request()
            try:
                self._generate_validated(provider, model, key, prompt, schema, None, request_id)
                LOGGER.info("LLM model succeeded: %s/%s", provider, model)
                results.append((label, "ok"))
            except Exception as exc:
                status = _status_code(exc)
                results.append((label, _diagnostic_error(exc, status)))
        return results

    @staticmethod
    def configured_key_names() -> list[str]:
        return [name for name in ("GEMINI_API_KEY", "LLM_API_KEY", "GROQ_API_KEY")
                if os.getenv(name)]

    @staticmethod
    def _cache_key(provider: str, model: str, prompt: str, schema: Mapping[str, Any], media: tuple[bytes, str] | None) -> str:
        digest = hashlib.sha256()
        for value in (provider, model, prompt, json.dumps(schema, sort_keys=True, separators=(",", ":"))):
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        if media:
            digest.update(media[1].encode("utf-8"))
            digest.update(media[0])
        return digest.hexdigest()

    def _read_cache(self, key: str) -> dict[str, Any] | None:
        try:
            value = json.loads((self.cache_dir / f"{key}.json").read_text(encoding="utf-8"))
            return value if isinstance(value, dict) and "result" in value else None
        except (OSError, ValueError):
            return None

    def _write_cache(self, key: str, result: Any, provider: str, model: str,
                     input_tokens: int, output_tokens: int, latency: float) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            target = self.cache_dir / f"{key}.json"
            temporary = target.with_suffix(f".{os.getpid()}.tmp")
            temporary.write_text(json.dumps({
                "result": result,
                "provider": provider,
                "model": model,
                "input_tokens": int(input_tokens),
                "output_tokens": int(output_tokens),
                "latency": float(latency),
            }, ensure_ascii=False), encoding="utf-8")
            temporary.replace(target)
        except OSError as exc:
            LOGGER.warning("Could not write LLM cache (%s)", type(exc).__name__)

    @staticmethod
    def _extract_json(text: str) -> Any:
        return json.loads(text.strip())

    def _request_provider(self, provider: str, model: str, api_key: str,
                          prompt: str, schema: Mapping[str, Any], media: tuple[bytes, str] | None,
                          repair_error: str | None = None) -> tuple[str, int, int]:
        request_prompt = prompt
        if repair_error:
            request_prompt += ("\n\nYour previous response did not satisfy the required JSON schema. "
                               f"Repair it. Validation error: {repair_error}")
        if provider == "gemini":
            parts: list[dict[str, Any]] = []
            if media:
                parts.append({"inline_data": {"mime_type": media[1], "data": base64.b64encode(media[0]).decode("ascii")}})
            parts.append({"text": request_prompt})
            payload = {
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "temperature": 0,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": schema,
                },
            }
            response = requests.post(
                GEMINI_ENDPOINT.format(model=model),
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=payload, timeout=self.timeout,
            )
            response.raise_for_status()
            body = response.json()
            text = "".join(part.get("text", "") for part in body["candidates"][0]["content"]["parts"] if "text" in part)
            usage = body.get("usageMetadata", {})
            return text, int(usage.get("promptTokenCount", 0)), int(usage.get("candidatesTokenCount", 0))

        content: Any = request_prompt
        if media:
            if media[1] == "application/pdf":
                raise ValueError("Groq fallback does not accept PDF bytes; PDF input is sent to Gemini")
            data_url = f"data:{media[1]};base64,{base64.b64encode(media[0]).decode('ascii')}"
            content = [
                {"type": "text", "text": request_prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "structured_response", "strict": True, "schema": schema,
            }},
        }
        response = requests.post(
            GROQ_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload, timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.json()
        text = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        return text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))

    def _request_with_backoff(self, provider: str, model: str, api_key: str,
                              *args: Any, request_id: int | None = None,
                              **kwargs: Any) -> tuple[str, int, int]:
        for attempt in range(self.max_429_retries + 1):
            started = time.perf_counter()
            try:
                _GLOBAL_RATE_LIMITER.acquire()
                with _GLOBAL_CALL_SEMAPHORE:
                    text, input_tokens, output_tokens = self._request_provider(
                        provider, model, api_key, *args, **kwargs
                    )
                self.usage.record(provider, model, input_tokens, output_tokens,
                                  time.perf_counter() - started, cached=False,
                                  request_id=request_id)
                return text, input_tokens, output_tokens
            except requests.HTTPError as exc:
                self.usage.record(provider, model, latency=time.perf_counter() - started,
                                  cached=False, request_id=request_id)
                response = exc.response
                status = response.status_code if response is not None else None
                if status != 429 or attempt >= self.max_429_retries:
                    raise
                delay = self.backoff_base * (2 ** attempt)
                LOGGER.warning("LLM provider rate limited; retrying after %.2fs", delay)
                self._sleep(delay)
            except Exception:
                self.usage.record(provider, model, latency=time.perf_counter() - started,
                                  cached=False, request_id=request_id)
                raise
        raise RuntimeError("unreachable retry loop")

    def _generate_validated(self, provider: str, model: str, api_key: str,
                            prompt: str, schema: Mapping[str, Any], media: tuple[bytes, str] | None,
                            request_id: int) -> tuple[Any, int, int]:
        text, input_tokens, output_tokens = self._request_with_backoff(
            provider, model, api_key, prompt, schema, media, request_id=request_id
        )
        try:
            result = self._extract_json(text)
            error = _schema_error(result, schema)
        except (ValueError, TypeError) as exc:
            result, error = None, f"Invalid JSON: {exc}"
        if error is None:
            return result, input_tokens, output_tokens
        repair_prompt = prompt
        repair_text, repair_in, repair_out = self._request_with_backoff(
            provider, model, api_key, repair_prompt, schema, media, error,
            request_id=request_id,
        )
        try:
            repaired = self._extract_json(repair_text)
            repair_error = _schema_error(repaired, schema)
        except (ValueError, TypeError) as exc:
            repaired, repair_error = None, f"Invalid JSON: {exc}"
        if repair_error:
            raise ValueError(f"JSON schema repair failed: {repair_error}")
        return repaired, input_tokens + repair_in, output_tokens + repair_out

    def generate_json(self, prompt: str, schema: Mapping[str, Any], file: Any = None) -> Any:
        """Generate JSON, replaying cached results before honoring no-LLM mode."""
        started = time.perf_counter()
        request_id = self.usage.begin_request()
        media = _media(file)
        providers = self._providers()
        for provider, model, key in providers:
            cache_key = self._cache_key(provider, model, prompt, schema, media)
            cached_result = self._read_cache(cache_key)
            if cached_result is not None:
                self.usage.record(
                    cached_result.get("provider", provider),
                    cached_result.get("model", model),
                    cached_result.get("input_tokens", 0),
                    cached_result.get("output_tokens", 0),
                    cached_result.get("latency", 0.0),
                                  cached=True, request_id=request_id)
                return cached_result["result"]

        if self.no_llm:
            LOGGER.warning("LLM disabled by --no-llm; returning None for uncached request")
            self.usage.record("none", "no-llm", latency=time.perf_counter() - started,
                              request_id=request_id)
            return None

        configured = False
        failures: list[BaseException] = []
        for provider, model, key in providers:
            if not key:
                continue
            configured = True
            try:
                record_start = len(self.usage.records)
                result, input_tokens, output_tokens = self._generate_validated(
                    provider, model, key, prompt, schema, media, request_id
                )
                original_latency = sum(record.latency for record in self.usage.records[record_start:])
                cache_key = self._cache_key(provider, model, prompt, schema, media)
                self._write_cache(cache_key, result, provider, model,
                                  input_tokens, output_tokens, original_latency)
                LOGGER.info("LLM model succeeded: %s/%s", provider, model)
                return result
            except Exception as exc:
                failures.append(exc)
                LOGGER.warning("LLM model %s/%s failed (%s); trying next model if available",
                               provider, model, type(exc).__name__)
        if not configured:
            self.usage.record("none", "unconfigured", latency=time.perf_counter() - started,
                              request_id=request_id)
            raise MissingAPIKeyError(
                "No LLM provider key configured. Set GEMINI_API_KEY or LLM_API_KEY; "
                "GROQ_API_KEY is optional."
            )
        failures_text = [_diagnostic_error(exc, _status_code(exc)) for exc in failures]
        detail = "; ".join(failures_text) or "no provider accepted the request"
        primary = failures[0] if failures else None
        raise LLMRequestError(
            f"All configured LLM providers failed: {detail}",
            error_class=type(primary).__name__ if primary is not None else None,
            http_status=_status_code(primary) if primary is not None else None,
            network_blocked=isinstance(primary, (requests.ConnectionError, requests.Timeout)) if primary is not None else False,
        ) from None
