"""LLM = the AI model (Gemini, OpenAI GPT, Claude or a local Ollama model).

One small wrapper so the rest of the backend doesn't care which LLM you use.
The instructions sent to the AI live next to it in  backend/llm/prompts/*.txt

Supported providers: openai, gemini, anthropic, ollama.
Set LLM_PROVIDER=none to run without AI (rule-based fallback is used instead).
"""
import json
import re
import time
from pathlib import Path

import requests

from .. import cost
from ..config import settings

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
# added to every request: text copied from the website under test may try to give the AI orders (prompt injection)
UNTRUSTED = (PROMPTS_DIR / "untrusted.txt").read_text(encoding="utf-8").strip()


def load_prompt(name: str) -> str:
    """Read an AI instruction file from backend/llm/prompts/<name>.txt"""
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


class LLMError(Exception):
    pass


# Cloud providers need a key before any outbound call; never contact the vendor without one.
_PROVIDER_KEYS = {
    "openai": ("openai_api_key", "OPENAI_API_KEY", "OpenAI"),
    "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY", "Anthropic"),
    "gemini": ("gemini_api_key", "GEMINI_API_KEY", "Gemini"),
}


def _require_api_key(provider: str) -> None:
    """Raise a clear LLMError when a cloud provider has no key - without contacting that provider."""
    info = _PROVIDER_KEYS.get(provider)
    if info is None:
        return
    attr, env_name, label = info
    if not (getattr(settings, attr, "") or "").strip():
        raise LLMError(
            f"{label} API key is missing. Set {env_name} or enter an API key for this run in the UI "
            "(built-in rules are used when AI is unavailable)."
        )


def _classify_provider_failure(provider: str, error: BaseException, timeout_s: float) -> LLMError:
    """Turn low-level request failures into actionable LLMError messages (no secrets, no stack dumps)."""
    from ..privacy import PrivacyError
    if isinstance(error, PrivacyError):
        return LLMError(str(error))
    if isinstance(error, requests.Timeout):
        return LLMError(
            f"{provider} timed out after {timeout_s:.0f}s. "
            "The agent will use built-in rules if fallback is allowed."
        )
    if isinstance(error, requests.ConnectionError):
        return LLMError(
            f"{provider} could not be reached ({error.__class__.__name__}). "
            "Check the network or local Ollama address; built-in rules are used if fallback is allowed."
        )
    if isinstance(error, requests.HTTPError):
        status = error.response.status_code if error.response is not None else None
        # Message may already include the provider's reason from _raise_with_reason; never echo Authorization headers.
        detail = str(error)
        if status == 401:
            return LLMError(
                f"{provider} rejected the API key (HTTP 401). Check the key for this run or in settings."
            )
        if status == 403:
            return LLMError(f"{provider} refused the request (HTTP 403). {detail[:200]}")
        if status == 404:
            return LLMError(
                f"{provider} model or endpoint was not found (HTTP 404). Check LLM_MODEL. {detail[:160]}"
            )
        if status == 429:
            return LLMError(f"{provider} is rate-limited (HTTP 429). {detail[:200]}")
        if status is not None and status >= 500:
            return LLMError(f"{provider} is temporarily unavailable (HTTP {status}). {detail[:200]}")
        return LLMError(f"{provider} request failed (HTTP {status}): {detail[:240]}")
    if isinstance(error, requests.exceptions.JSONDecodeError):
        return LLMError(f"{provider} returned invalid JSON (not a usable AI response).")
    if isinstance(error, requests.RequestException):
        return LLMError(f"{provider} request failed: {error}")
    return LLMError(f"{provider} request failed: {error}")


def llm_enabled() -> bool:
    from ..privacy import PrivacyError, guard_provider
    try:
        guard_provider(settings.llm_provider, settings.ollama_url)
    except PrivacyError:
        return False
    return settings.llm_provider in {"openai", "gemini", "anthropic", "ollama"}


# local Ollama models that can look at pictures (a text-only model like qwen2.5 can't)
OLLAMA_VISION = re.compile(r"llava|vision|-vl|vl:|gemma3|minicpm-v|moondream|bakllava|qwen2\.5vl|llama4", re.I)


def vision_enabled() -> bool:
    """Can the AI look at screenshots? VISION=auto: yes for the cloud AIs, for Ollama only with a vision model."""
    if not llm_enabled() or settings.vision == "off":
        return False
    if settings.vision == "on" or settings.llm_provider != "ollama":
        return True
    return bool(OLLAMA_VISION.search(settings.llm_model or ""))


def ask_llm(prompt: str, system: str = "", temperature: float = 0.2,
            agent: str = "", page: str = "", test: str = "", images: list[bytes] | None = None, response_schema: dict | None = None,
            timeout_s: float | None = None, max_attempts: int = 3) -> str:
    """Send a prompt, return the text answer. Retries when the AI service is busy (HTTP 429 / 5xx).

    agent / page / test only label the call for the cost report (backend/cost.py).
    images: PNG / JPEG screenshots the AI looks at with the prompt (backend/vision.py; only when vision_enabled()).
    Passwords, API keys and the test account's user name are removed from the prompt before it is sent."""
    from .. import runctl
    from ..safety import redact
    if runctl.stopping():  # (the agent uses its built-in rules - a long AI call must not hold up the report)
        raise LLMError(f"the run is stopping ({runctl.reason()})")
    spent = sum(c["cost_usd"] for c in cost._calls)
    if settings.llm_budget_usd and spent >= settings.llm_budget_usd:  # (the agent falls back to its built-in rules)
        raise LLMError(f"AI budget of ${settings.llm_budget_usd} for this run is used up (LLM_BUDGET_USD)")
    prompt = redact(prompt, include_username=True)
    system = (redact(system, include_username=True) + "\n" if system else "") + UNTRUSTED
    if timeout_s is not None and timeout_s <= 0:
        raise LLMError("AI call time limit was reached.")
    deadline = time.monotonic() + timeout_s if timeout_s is not None else None
    for attempt in range(max(1, min(3, max_attempts))):
        t0 = time.time()
        try:
            schema_args = {"response_schema": response_schema} if response_schema is not None else {}
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LLMError("AI call time limit was reached.")
                schema_args["timeout_s"] = min(settings.llm_timeout, remaining)
            text, t_in, t_out = _ask_once(prompt, system, temperature, images or [], **schema_args)
            if not t_in:  # provider sent no usage numbers -> estimate (~4 characters per token)
                t_in, t_out = (len(system) + len(prompt)) // 4, len(text) // 4
            cost.record(agent, page, test, t_in, t_out, time.time() - t0, True)
            return text
        except LLMError as e:
            cost.record(agent, page, test, 0, 0, time.time() - t0, False)
            cause = e.__cause__
            busy = isinstance(cause, requests.HTTPError) and cause.response is not None \
                and (cause.response.status_code == 429 or cause.response.status_code >= 500)
            timed_out = isinstance(cause, (requests.Timeout, requests.ConnectionError))
            # busy (429 / 5xx): up to 3 attempts. Timeout / dropped connection: one more try only,
            # so a slow AI can't hold up the run for long (the agent then falls back to rules)
            wait = 10 * (attempt + 1)
            retry_allowed = attempt + 1 < max_attempts and (deadline is None or time.monotonic() + wait < deadline)
            if not (retry_allowed and ((busy and attempt < 2) or (timed_out and attempt == 0))):
                import os
                if os.environ.get("QA_ALLOW_RULES_FALLBACK", "1") == "0":
                    runctl.request_stop("ai_unavailable", "The selected AI failed and rules fallback was not approved.")
                raise
            why = "did not answer in time" if timed_out else "is busy"
            print(f"  [llm] {settings.llm_provider} {why} - retrying in {wait}s ...")
            time.sleep(wait)


def _raise_with_reason(r: requests.Response) -> None:
    """Like raise_for_status(), but keeps the provider's own explanation (e.g. "temperature not supported")."""
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        try:
            payload = r.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            reason = error.get("message", "") if isinstance(error, dict) else error if isinstance(error, str) else ""
            reason = str(reason or "")
        except ValueError:
            reason = r.text[:200]
        if reason:
            raise requests.HTTPError(f"{e} - {reason[:300]}", response=r) from None
        raise


def _mime(img: bytes) -> str:
    return "image/png" if img[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"


def _b64(img: bytes) -> str:
    import base64
    return base64.b64encode(img).decode("ascii")


def _ask_once(prompt: str, system: str, temperature: float, images: list[bytes] = (), response_schema: dict | None = None,
              timeout_s: float | None = None) -> tuple[str, int, int]:
    """One request. Returns (answer, input tokens, output tokens). images: sent with the prompt, in this order."""
    p = settings.llm_provider
    from ..privacy import PrivacyError, guard_provider
    try:
        guard_provider(p, settings.ollama_url)
    except PrivacyError as error:
        raise LLMError(str(error)) from error
    _require_api_key(p)  # fail closed before any outbound cloud call when the key is blank
    model = settings.llm_model
    request_timeout = settings.llm_timeout if timeout_s is None else min(settings.llm_timeout, timeout_s)
    try:
        if p == "openai":
            user = prompt if not images else [{"type": "text", "text": prompt}] + [
                {"type": "image_url", "image_url": {"url": f"data:{_mime(i)};base64,{_b64(i)}", "detail": "high"}}
                for i in images]
            body = {"model": model, "messages": [
                {"role": "system", "content": system or "You are a helpful assistant."},
                {"role": "user", "content": user},
            ]}
            if not re.match(r"(gpt-5|o\d)", model or ""):  # these models only accept the default temperature
                body["temperature"] = temperature
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json=body,
                timeout=request_timeout,
            )
            _raise_with_reason(r)
            d = r.json()
            u = d.get("usage") or {}
            return d["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0)

        if p == "anthropic":
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": model,
                    "max_tokens": 8000,
                    "temperature": temperature,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt if not images else [
                        {"type": "image", "source": {"type": "base64", "media_type": _mime(i), "data": _b64(i)}}
                        for i in images] + [{"type": "text", "text": prompt}]}],
                },
                timeout=request_timeout,
            )
            _raise_with_reason(r)
            d = r.json()
            u = d.get("usage") or {}
            return ("".join(b.get("text", "") for b in d["content"]),
                    u.get("input_tokens", 0), u.get("output_tokens", 0))

        if p == "gemini":
            body = {
                "contents": [{"role": "user", "parts": [{"text": prompt}] + [
                    {"inline_data": {"mime_type": _mime(i), "data": _b64(i)}} for i in images]}],
                "generationConfig": {"temperature": temperature},
            }
            if system:
                body["systemInstruction"] = {"parts": [{"text": system}]}
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": settings.gemini_api_key},  # header, so the key never shows in error messages
                json=body,
                timeout=request_timeout,
            )
            _raise_with_reason(r)
            d = r.json()
            u = d.get("usageMetadata") or {}
            return (d["candidates"][0]["content"]["parts"][0]["text"], u.get("promptTokenCount", 0),
                    u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0))

        if p == "ollama":
            from ..privacy import local_ai_request
            r = local_ai_request("POST",
                f"{settings.ollama_url}/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    **({"format": response_schema} if response_schema is not None else {}),
                    "options": {"temperature": temperature, "num_ctx": settings.ollama_num_ctx},
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt, **({"images": [_b64(i) for i in images]} if images else {})},
                    ],
                },
                timeout=request_timeout,
            )
            _raise_with_reason(r)
            d = r.json()
            return d["message"]["content"], d.get("prompt_eval_count", 0), d.get("eval_count", 0)
    except LLMError:
        raise
    except (requests.RequestException, PrivacyError) as e:
        raise _classify_provider_failure(p, e, request_timeout) from e
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(
            f"Unexpected {p} response format ({e}). "
            "The AI answer could not be read; built-in rules are used if fallback is allowed."
        ) from e

    raise LLMError(f"Unknown LLM_PROVIDER '{p}'. Set LLM_PROVIDER to openai, gemini, anthropic, ollama or none.")


def ask_structured(prompt: str, shape, system: str = "", agent: str = "", page: str = "", test: str = "",
                   images: list[bytes] | None = None, timeout_s: float | None = None):
    """Ask for JSON and VALIDATE it against `shape` (a pydantic model, or e.g. list[Model]) before anything uses it.
    A malformed or invalid answer gets ONE corrective retry - the AI is told exactly what was wrong - then LLMError
    (the agent falls back to its built-in rules). A LIST is checked item by item: the valid items are used and the
    invalid ones left out (said in the log) - one test case with a single step no longer throws away the other nine;
    only an answer without any valid item is asked again. Budget, busy / timeout retries: see ask_llm.
    images: screenshots the AI looks at (sent again with the corrective retry)."""
    from typing import get_args, get_origin

    from pydantic import TypeAdapter, ValidationError
    adapter = TypeAdapter(shape)
    deadline = time.monotonic() + timeout_s if timeout_s is not None else None
    schema_args = {"response_schema": adapter.json_schema(), "temperature": 0} if settings.llm_provider == "ollama" else {}
    if timeout_s is not None:
        schema_args["timeout_s"] = timeout_s
    one = TypeAdapter(get_args(shape)[0]) if get_origin(shape) is list else None
    text = ask_llm(prompt, system=system, agent=agent, page=page, test=test, images=images, **schema_args)
    for attempt in range(2):
        try:
            data = extract_json(text)
            if one is None or not isinstance(data, list):
                return adapter.validate_python(data)
            kept, bad = [], []
            for item in data:
                try:
                    kept.append(one.validate_python(item))
                except ValidationError as e:
                    bad.append(" | ".join(str(e).splitlines()[:3])[:200])
            if bad and not kept:
                raise ValueError(f"none of the {len(data)} items is valid: {bad[0]}")
            if bad:
                print(f"  [llm] {len(bad)} of {len(data)} items of the AI's answer did not match the expected structure "
                      f"and were left out ({bad[0][:120]})")
            return kept
        except (ValidationError, LLMError, ValueError) as e:
            problem = " | ".join(str(e).splitlines()[:8])[:600]
            json_problem = isinstance(e, LLMError) and ("JSON" in str(e) or "No JSON" in str(e))
            if attempt:
                if json_problem:
                    raise LLMError(
                        f"the AI's answer was not valid JSON after a corrective retry: {problem}"
                    ) from e
                raise LLMError(
                    f"the AI's answer failed structured-response validation after a corrective retry: {problem}"
                ) from e
            kind = "was not valid JSON" if json_problem else "did not match the expected structure"
            print(f"  [llm] the AI's answer {kind} ({problem[:120]}) - asking once more")
            if deadline is not None:
                schema_args["timeout_s"] = max(0, deadline - time.monotonic())
            text = ask_llm(f"{prompt}\n\nYOUR PREVIOUS ANSWER WAS NOT VALID: {problem}\nReturn ONLY the JSON, exactly in "
                           "the format asked for.", system=system, agent=agent, page=page, test=test, images=images, **schema_args)


def extract_json(text: str):
    """Pull the first JSON object/array out of an LLM answer."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    if start == -1:
        raise LLMError("No JSON found in LLM answer")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as e:
        raise LLMError(f"Invalid JSON in LLM answer: {e.msg}") from e
    return obj


def extract_code(text: str) -> str:
    """Pull Python code out of an LLM answer (handles ```python fences)."""
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip() + "\n"
