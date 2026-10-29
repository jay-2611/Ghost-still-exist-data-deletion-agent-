import sys
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
import os
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
from usage import (LLMClient, LLMRequestError, MissingAPIKeyError, UsageTracker,
                   _diagnostic_error, _load_dotenv)  # noqa: E402


def _memory_cache(client):
    entries = {}
    client._read_cache = lambda key: entries.get(key)
    client._write_cache = lambda key, result, provider, model, in_tokens, out_tokens, latency: entries.__setitem__(
        key, {"result": result, "provider": provider, "model": model,
              "input_tokens": in_tokens, "output_tokens": out_tokens, "latency": latency}
    )
    return entries


def test_identical_call_uses_cache_and_usage_report_renders():
    with tempfile.TemporaryDirectory(dir=ROOT / "code") as temp:
        tracker = UsageTracker({("gemini", "test-model"): (1.0, 2.0)})
        client = LLMClient(usage_tracker=tracker, cache_dir=temp, no_llm=False,
                           gemini_model="test-model", groq_model="test-fallback")
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
                  "required": ["ok"], "additionalProperties": False}
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key", "LLM_API_KEY": "", "GROQ_API_KEY": ""}):
            with patch.object(client, "_request_provider", return_value=('{"ok":true}', 12, 3)) as live_call:
                first = client.generate_json("check", schema)
            replay_client = LLMClient(usage_tracker=tracker, cache_dir=temp, no_llm=True,
                                      gemini_model="test-model", groq_model="test-fallback")
            second = replay_client.generate_json("check", schema)
        assert first == second == {"ok": True}
        assert live_call.call_count == 1
        assert tracker.records[0].cached is False
        assert tracker.records[1].cached is True
        assert tracker.records[1].input_tokens == 12
        assert tracker.records[1].output_tokens == 3
        cache_entry = json.loads(next(Path(temp).glob("*.json")).read_text(encoding="utf-8"))
        assert cache_entry["provider"] == "gemini"
        assert cache_entry["model"] == "test-model"
        assert cache_entry["input_tokens"] == 12
        assert cache_entry["output_tokens"] == 3
        assert cache_entry["latency"] >= 0
        report = tracker.render_markdown()
        assert "Overall" in report
        assert "test-model" in report
        assert "Cache hits" in report
        assert "| gemini | test-model | 2 | 1 | 12 | 3 | 12 | 3 | 24 | 6 |" in report
        assert "$0.000036" in report


def test_no_llm_returns_none_and_records_warning(caplog):
    tracker = UsageTracker()
    client = LLMClient(usage_tracker=tracker, cache_dir=ROOT / "code" / "unused-cache", no_llm=True)
    assert client.generate_json("prompt", {"type": "object"}) is None
    assert tracker.records[-1].provider == "none"
    assert "LLM disabled" in caplog.text


def test_invalid_json_gets_one_schema_repair_retry():
    tracker = UsageTracker()
    client = LLMClient(usage_tracker=tracker, no_llm=False, gemini_model="test-model")
    _memory_cache(client)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"], "additionalProperties": False}
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key", "LLM_API_KEY": "", "GROQ_API_KEY": ""}):
        with patch.object(client, "_request_provider", side_effect=[
            ('{"ok":"yes"}', 8, 2), ('{"ok":true}', 9, 3),
        ]) as live_call:
            result = client.generate_json("check", schema)
    assert result == {"ok": True}
    assert live_call.call_count == 2
    assert len(tracker.records) == 2
    assert tracker.request_count == 1


def test_dotenv_loads_missing_values_only_and_accepts_llm_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "environment-value")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with patch("usage.REPO_ROOT", ROOT / "code"), \
            patch.object(Path, "is_file", return_value=True), \
            patch.object(Path, "read_text", return_value='# ignored\nLLM_API_KEY="fixture-secret"\nGROQ_API_KEY=groq-fixture\n'), \
            patch.dict(sys.modules, {"dotenv": None}):
        assert _load_dotenv(ROOT / "code" / ".env") is True
        assert os.environ["LLM_API_KEY"] == "environment-value"
        assert os.environ["GROQ_API_KEY"] == "groq-fixture"
        client = LLMClient(no_llm=False, cache_dir=ROOT / "code" / "unused-cache")
        assert client._providers()[0][2] == "environment-value"


def test_missing_key_raises_and_network_errors_are_redacted(monkeypatch):
    import requests
    import usage

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with patch("usage.REPO_ROOT", ROOT / "code"):
        client = LLMClient(no_llm=False, cache_dir=ROOT / "code" / "unused-cache")
    with pytest.raises(MissingAPIKeyError, match="GEMINI_API_KEY or LLM_API_KEY"):
        client.generate_json("p", {"type": "object"})

    monkeypatch.setenv("GEMINI_API_KEY", "fixture-secret")
    with patch.object(client, "_request_provider", side_effect=requests.ConnectionError("network failed fixture-secret")):
        with pytest.raises(LLMRequestError) as caught:
            client.generate_json("network-check", {"type": "object"})
    assert caught.value.network_blocked is True
    assert "fixture-secret" not in str(caught.value)
    assert "network unavailable or blocked" in str(caught.value)


def test_llmcheck_prints_only_key_names_and_result(monkeypatch, capsys):
    import main

    class FakeClient:
        env_file_found = True

        def __init__(self, no_llm=False):
            pass

        @staticmethod
        def configured_key_names():
            return ["GEMINI_API_KEY", "LLM_API_KEY"]

        @staticmethod
        def diagnostic_model_checks(prompt, schema):
            return [("gemini/gemini-3.1-flash-lite", "ok"),
                    ("groq/openai/gpt-oss-20b", "ok")]

    monkeypatch.setattr(main, "LLMClient", FakeClient)
    assert main._llmcheck() == 0
    output = capsys.readouterr().out
    assert output.splitlines() == [
        "env file found: yes",
        "key names set: GEMINI_API_KEY, LLM_API_KEY",
        "gemini/gemini-3.1-flash-lite: ok",
        "groq/openai/gpt-oss-20b: ok",
    ]
    assert "fixture-secret" not in output


def test_404_model_not_found_falls_through_to_next_model(monkeypatch, caplog):
    import requests

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"], "additionalProperties": False}
    response = requests.Response()
    response.status_code = 404
    not_found = requests.HTTPError("model not found", response=response)
    client = LLMClient(no_llm=False, gemini_models=("missing-model", "working-model"),
                       groq_model="fallback-model")
    _memory_cache(client)
    caplog.set_level("INFO", logger="usage")
    with patch.dict("os.environ", {"GEMINI_API_KEY": "fixture-key", "LLM_API_KEY": "",
                                   "GROQ_API_KEY": ""}):
        with patch.object(client, "_request_provider", side_effect=[
                not_found, ('{"ok":true}', 8, 2)]) as live_call:
            assert client.generate_json("fallback", schema) == {"ok": True}
    assert [call.args[1] for call in live_call.call_args_list] == ["missing-model", "working-model"]
    assert "LLM model succeeded: gemini/working-model" in caplog.text


def test_429_retries_with_exponential_backoff_and_counts_each_attempt(monkeypatch):
    import requests
    import usage

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"], "additionalProperties": False}
    response = requests.Response()
    response.status_code = 429
    rate_limited = requests.HTTPError("rate limit", response=response)
    delays = []
    class CountingLimiter:
        calls = 0

        def acquire(self):
            self.calls += 1

    limiter = CountingLimiter()
    monkeypatch.setattr(usage, "_GLOBAL_RATE_LIMITER", limiter)
    assert usage.REQUESTS_PER_MINUTE == 8
    assert usage.MAX_CONCURRENT_LLM_CALLS == 1
    client = LLMClient(no_llm=False, gemini_model="test-model", max_429_retries=2,
                       backoff_base=0.25, sleeper=delays.append)
    _memory_cache(client)
    with patch.dict("os.environ", {"GEMINI_API_KEY": "fixture-key", "LLM_API_KEY": "",
                                   "GROQ_API_KEY": ""}):
        with patch.object(client, "_request_provider", side_effect=[
                rate_limited, ('{"ok":true}', 11, 4)]) as live_call:
            assert client.generate_json("retry", schema) == {"ok": True}
    assert live_call.call_count == 2
    assert delays == [0.25]
    assert limiter.calls == 2


def test_default_model_order_and_safe_diagnostic_categories(monkeypatch):
    import requests

    monkeypatch.setenv("GEMINI_MODELS", "")
    client = LLMClient(no_llm=True)
    assert client.gemini_models == ("gemini-3.1-flash-lite",)
    assert all("3.8" not in model for model in client.gemini_models)
    for status, expected in ((401, "bad key"), (403, "bad key"), (404, "model not found"),
                             (429, "rate limit")):
        response = requests.Response()
        response.status_code = status
        error = requests.HTTPError("fixture error", response=response)
        assert expected in _diagnostic_error(error, status)
    assert "network unavailable or blocked" in _diagnostic_error(
        requests.ConnectionError("fixture"), None
    )


def test_prefetch_visits_all_media_and_only_ambiguous_intents(monkeypatch, capsys):
    import main

    intent_calls = []

    class FakeClient:
        def __init__(self, no_llm=False):
            self.prompts = []

        def generate_json(self, prompt, schema, file=None):
            self.prompts.append((prompt, schema, file))
            intent_calls.append(prompt)
            return {"is_deletion": True}

    media_calls = []
    monkeypatch.setattr(main, "LLMClient", FakeClient)
    monkeypatch.setattr(main, "parse_file", lambda row, dataset_dir, llm: media_calls.append(row.file_path))
    assert main._prefetch() == 0
    assert sum(path.lower().endswith(".png") for path in media_calls) == 11
    assert sum(path.lower().endswith(".pdf") for path in media_calls) == 4
    assert "prefetch complete: media=15; ambiguous_intent=" in capsys.readouterr().out
    ds = main.load_all(main.DATASET_DIR)
    expected_ambiguous = sum(main.is_ambiguous_intent(str(text))
                             for text in ds.deletion_requests["request_text"].fillna(""))
    assert main.INTENT_BATCH_SIZE == 40
    assert len(intent_calls) == (expected_ambiguous + 39) // 40
