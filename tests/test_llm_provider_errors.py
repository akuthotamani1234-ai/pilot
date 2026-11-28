"""Offline AI provider error messages and rules-fallback safety. No paid/cloud calls."""
from __future__ import annotations

import json

import pytest
import requests
from pydantic import BaseModel

from backend import llm, privacy


class _Item(BaseModel):
    title: str
    steps: list[str]


@pytest.fixture
def quiet_cost(monkeypatch):
    from backend import cost, runctl
    monkeypatch.setattr(runctl, "stopping", lambda: False)
    monkeypatch.setattr(cost, "record", lambda *a, **k: None)
    monkeypatch.setattr(cost, "_calls", [])
    monkeypatch.delenv("QA_ALLOW_RULES_FALLBACK", raising=False)
    # Provider-message tests need cloud allowed; they still never contact a real vendor.
    monkeypatch.setattr(privacy, "runtime_mode", lambda: "cloud")
    monkeypatch.setattr(privacy, "guard_provider", lambda *a, **k: None)


@pytest.mark.parametrize("provider,attr,needle", [
    ("openai", "openai_api_key", "OPENAI_API_KEY"),
    ("anthropic", "anthropic_api_key", "ANTHROPIC_API_KEY"),
    ("gemini", "gemini_api_key", "GEMINI_API_KEY"),
])
def test_missing_api_key_is_clear_and_never_contacts_provider(provider, attr, needle, monkeypatch, quiet_cost):
    monkeypatch.setattr(llm.settings, "llm_provider", provider)
    monkeypatch.setattr(llm.settings, attr, "")
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: pytest.fail("must not contact provider without a key"))
    with pytest.raises(llm.LLMError, match=rf"{needle}|API key is missing"):
        llm._ask_once("secret page text", "system", 0.0)


def test_timeout_and_invalid_json_messages_preserve_llmerror_cause(monkeypatch, quiet_cost):
    monkeypatch.setattr(llm.settings, "llm_provider", "openai")
    monkeypatch.setattr(llm.settings, "openai_api_key", "fixture-key-not-real")
    monkeypatch.setattr(llm.settings, "llm_timeout", 12)

    def timeout(*_a, **_k):
        raise requests.Timeout("simulated")

    monkeypatch.setattr(llm.requests, "post", timeout)
    with pytest.raises(llm.LLMError, match=r"timed out after 12s") as timed:
        llm._ask_once("x", "", 0)
    assert isinstance(timed.value.__cause__, requests.Timeout)

    class BadJson:
        def raise_for_status(self):
            return None

        def json(self):
            raise requests.exceptions.JSONDecodeError("Expecting value", "not-json", 0)

    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: BadJson())
    with pytest.raises(llm.LLMError, match="invalid JSON"):
        llm._ask_once("x", "", 0)


@pytest.mark.parametrize("status,needle", [
    (401, r"rejected the API key \(HTTP 401\)"),
    (429, r"rate-limited \(HTTP 429\)"),
    (503, r"temporarily unavailable \(HTTP 503\)"),
])
def test_http_status_messages_do_not_echo_secrets(status, needle, monkeypatch, quiet_cost):
    monkeypatch.setattr(llm.settings, "llm_provider", "openai")
    monkeypatch.setattr(llm.settings, "openai_api_key", "sk-secret-fixture-value")
    monkeypatch.setattr(llm.settings, "llm_model", "gpt-test")

    class Resp:
        status_code = status
        text = "upstream"

        def raise_for_status(self):
            raise requests.HTTPError(f"{status} error", response=self)

        def json(self):
            return {"error": {"message": "provider said no"}}

    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: Resp())
    with pytest.raises(llm.LLMError, match=needle) as err:
        llm._ask_once("page with sk-secret-fixture-value", "", 0)
    assert "sk-secret-fixture-value" not in str(err.value)


def test_extract_json_and_structured_validation_messages(monkeypatch, quiet_cost):
    with pytest.raises(llm.LLMError, match="No JSON found"):
        llm.extract_json("hello there")
    with pytest.raises(llm.LLMError, match="Invalid JSON"):
        llm.extract_json("{not-json")

    answers = iter(["not json at all", "still not json {"])
    monkeypatch.setattr(llm, "ask_llm", lambda *a, **k: next(answers))
    with pytest.raises(llm.LLMError, match="not valid JSON after a corrective retry"):
        llm.ask_structured("return cases", list[_Item])

    answers2 = iter([
        json.dumps([{"title": "ok", "steps": "bad"}]),
        json.dumps([{"title": "still", "steps": 3}]),
    ])
    monkeypatch.setattr(llm, "ask_llm", lambda *a, **k: next(answers2))
    with pytest.raises(llm.LLMError, match="structured-response validation after a corrective retry"):
        llm.ask_structured("return cases", list[_Item])


def test_provider_failure_still_allows_rules_fallback_path(monkeypatch, quiet_cost):
    """Callers that catch LLMError (Android readiness, design, web agents) keep working."""
    monkeypatch.setattr(llm.settings, "llm_provider", "openai")
    monkeypatch.setattr(llm.settings, "openai_api_key", "")
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: pytest.fail("no network"))

    fallback = {"used": False}
    try:
        llm.ask_llm("probe", max_attempts=1)
    except llm.LLMError as error:
        assert "API key is missing" in str(error)
        fallback["used"] = True  # same branch agents take when falling back to rules
    assert fallback["used"] is True


def test_ask_llm_provider_none_is_turned_off_not_unknown(monkeypatch, quiet_cost):
    """LLM_PROVIDER=none must not reach provider routing or claim 'none' is an unknown provider."""
    monkeypatch.setattr(llm.settings, "llm_provider", "none")
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: pytest.fail("must not contact any provider"))
    with pytest.raises(llm.LLMError, match=r"(?i)turned off|rules") as err:
        llm.ask_llm("probe", max_attempts=1)
    assert "Unknown LLM_PROVIDER" not in str(err.value)


def test_unknown_provider_and_unexpected_shape_are_llmerror(monkeypatch, quiet_cost):
    monkeypatch.setattr(llm.settings, "llm_provider", "not-a-provider")
    with pytest.raises(llm.LLMError, match="Unknown LLM_PROVIDER|Supported providers for AI calls"):
        llm._ask_once("x", "", 0)

    monkeypatch.setattr(llm.settings, "llm_provider", "openai")
    monkeypatch.setattr(llm.settings, "openai_api_key", "fixture-key")

    class Odd:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": []}  # missing message content -> IndexError/KeyError path

    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: Odd())
    with pytest.raises(llm.LLMError, match="Unexpected openai response format"):
        llm._ask_once("x", "", 0)


@pytest.mark.parametrize("code,expected_calls", [("insufficient_quota", 1), ("rate_limit_exceeded", 2)])
def test_openai_429_distinguishes_quota_and_retry_after(code, expected_calls, monkeypatch, quiet_cost):
    monkeypatch.setattr(llm.settings, "llm_provider", "openai")
    monkeypatch.setattr(llm.settings, "openai_api_key", "fixture-secret")
    response = requests.Response()
    response.status_code = 429
    response.headers.update({"x-request-id": "req_fixture123", "Retry-After": "2"})
    response._content = json.dumps({"error": {"code": code, "type": code, "message": "fixture-secret"}}).encode()
    calls, delays = [], []

    def post(*args, **kwargs):
        calls.append(kwargs)
        return response

    monkeypatch.setattr(llm.requests, "post", post)
    monkeypatch.setattr(llm.time, "sleep", delays.append)
    with pytest.raises(llm.LLMError) as failure:
        llm.ask_llm("fixture", max_attempts=2)

    assert len(calls) == expected_calls
    assert "fixture-secret" not in str(failure.value)
    assert failure.value.diagnostics["request_id"] == "req_fixture123"
    assert failure.value.diagnostics["attempts"] == expected_calls
    if expected_calls == 2:
        assert sum(delays) >= 2
    else:
        assert delays == []
        assert "quota" in str(failure.value)


def test_rate_limit_recovers_and_records_real_retry_event(tmp_path, monkeypatch, quiet_cost):
    monkeypatch.setattr(llm.settings, "llm_provider", "openai")
    monkeypatch.setattr(llm.settings, "openai_api_key", "fixture-secret")
    limited = requests.Response()
    limited.status_code = 429
    limited.headers.update({"x-request-id": "req_fixture_recovered", "Retry-After": "1",
                            "x-ratelimit-remaining-tokens": "0"})
    limited._content = b'{"error":{"code":"rate_limit_exceeded","message":"fixture-secret"}}'
    success = requests.Response()
    success.status_code = 200
    success._content = b'{"choices":[{"message":{"content":"ready"}}],"usage":{"prompt_tokens":6,"completion_tokens":1}}'
    replies = iter((limited, success))
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: next(replies))
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)

    with llm.design_batch(tmp_path, 24):
        assert llm.ask_llm("fixture", max_attempts=2) == "ready"

    raw = next(tmp_path.glob("events.test_design*.jsonl")).read_text()
    assert "fixture-secret" not in raw
    event = json.loads(raw)
    assert event["status"] == "retrying"
    assert event["diagnostics"]["batch_size"] == 24
    assert event["diagnostics"]["x-ratelimit-remaining-tokens"] == "0"


def test_concurrent_provider_calls_wait_for_the_configured_slot(monkeypatch, quiet_cost):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    monkeypatch.setattr(llm.settings, "llm_provider", "openai")
    monkeypatch.setattr(llm.settings, "llm_max_in_flight", 1)
    first_in, release, second_in = Event(), Event(), Event()

    def ask_once(prompt, *_args, **_kwargs):
        if prompt == "first":
            first_in.set()
            assert release.wait(5)
        else:
            second_in.set()
        return prompt, 1, 1

    monkeypatch.setattr(llm, "_ask_once", ask_once)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(llm.ask_llm, "first")
        assert first_in.wait(5)
        second = pool.submit(llm.ask_llm, "second")
        try:
            assert not second_in.wait(0.1)
        finally:
            release.set()
        assert first.result(5) == "first" and second.result(5) == "second"


def test_ordered_batch_corrects_count_and_preserves_invalid_items(monkeypatch, quiet_cost):
    valid = {"title": "Second approved test", "steps": ["Check the expected value"]}
    replies = iter([json.dumps([valid]), json.dumps([{"title": "invalid", "steps": 4}, valid])])
    monkeypatch.setattr(llm, "ask_llm", lambda *a, **k: next(replies))
    results = llm.ask_structured("Design the two tests in order", list[_Item], expected_items=2)
    assert results == [None, _Item(**valid)]
