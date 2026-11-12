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


def test_unknown_provider_and_unexpected_shape_are_llmerror(monkeypatch, quiet_cost):
    monkeypatch.setattr(llm.settings, "llm_provider", "not-a-provider")
    with pytest.raises(llm.LLMError, match="Unknown LLM_PROVIDER|supported AI provider"):
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
