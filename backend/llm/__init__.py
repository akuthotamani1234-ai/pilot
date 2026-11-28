"""LLM = the AI model (Gemini, OpenAI GPT, Claude or a local Ollama model).

One small wrapper so the rest of the backend doesn't care which LLM you use.
The instructions sent to the AI live next to it in  backend/llm/prompts/*.txt

Supported providers: openai, gemini, anthropic, huggingface, ollama.
Set LLM_PROVIDER=none to run without AI (rule-based fallback is used instead).
"""
import contextlib as _contextlib
import contextvars as _contextvars
import json
import random
import re
import threading
import time
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from .. import cost
from ..config import settings

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _prompt_file(name: str) -> Path:
    """A real prompt file. A link, or a name that leaves the prompt folder, is refused."""
    from ..finalization import folder_is_linked
    path = PROMPTS_DIR / f"{name}.txt"
    if not name or Path(name).is_absolute() or ".." in Path(name).parts or folder_is_linked(path):
        raise OSError("The prompt is a link.")
    return path


# added to every request: text copied from the website under test may try to give the AI orders (prompt injection)
UNTRUSTED = _prompt_file("untrusted").read_text(encoding="utf-8").strip()


def load_prompt(name: str) -> str:
    """Read an AI instruction file from backend/llm/prompts/<name>.txt"""
    return _prompt_file(name).read_text(encoding="utf-8")


class LLMError(Exception):
    def __init__(self, message: str, *, diagnostics: dict | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


_QUOTA_ERRORS = {
    "insufficient_quota": "Check the API billing balance and project limits.",
    "billing_hard_limit_reached": "Check the API billing limit.",
    "credit_balance_exhausted": "Add API credits.",
    "organization_spend_limit_exceeded": "Check the organization spend limit.",
    "project_spend_limit_exceeded": "Check the project spend limit.",
    "organization_usage_limit_exceeded": "Check the organization usage limit.",
}
_RATE_FIELDS = (
    "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests", "x-ratelimit-reset-requests",
    "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens",
    "x-ratelimit-limit-project-tokens", "x-ratelimit-remaining-project-tokens",
    "x-ratelimit-reset-project-tokens",
)


def _retry_after(value: str) -> float | None:
    if re.fullmatch(r"[0-9]{1,9}(?:\.[0-9]{1,6})?", value):
        return float(value)
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _http_diagnostics(response) -> dict:
    from ..safety import redact

    headers = getattr(response, "headers", {})
    safe = {"http_status": response.status_code}
    try:
        body = response.json()
        error = body.get("error") if isinstance(body, dict) else None
    except ValueError:
        error = None
    if isinstance(error, dict):
        for field in ("code", "type"):
            value = error.get(field)
            if isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_]{1,80}", value):
                safe[f"error_{field}"] = redact(value, include_username=True)
    request_id = headers.get("x-request-id", "")
    if re.fullmatch(r"req_[a-zA-Z0-9_-]{1,96}", request_id):
        safe["request_id"] = redact(request_id, include_username=True)
    retry_after = _retry_after(headers.get("Retry-After", ""))
    if retry_after is not None:
        safe["retry_after_s"] = retry_after
    for field in _RATE_FIELDS:
        value = headers.get(field, "")
        if re.fullmatch(r"[0-9.hmsd]{1,32}", value):
            safe[field] = value
    return safe


# Cloud providers need a key before any outbound call; never contact the vendor without one.
_PROVIDER_KEYS = {
    "openai": ("openai_api_key", "OPENAI_API_KEY", "OpenAI"),
    "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY", "Anthropic"),
    "gemini": ("gemini_api_key", "GEMINI_API_KEY", "Gemini"),
    "huggingface": ("huggingface_api_key", "HF_TOKEN", "Hugging Face"),
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
        if status in (429, 503):
            diagnostics = _http_diagnostics(error.response)
            quota = _QUOTA_ERRORS.get(diagnostics.get("error_code")) or _QUOTA_ERRORS.get(
                diagnostics.get("error_type"))
            diagnostics["classification"] = "quota" if quota else "temporary"
            message = (f"{provider} API quota or billing limit reached (HTTP {status}). {quota}" if quota else
                       f"{provider} is rate-limited (HTTP 429). Retry when capacity is available." if status == 429
                       else f"{provider} is temporarily unavailable (HTTP {status}).")
            return LLMError(message, diagnostics=diagnostics)
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
    return settings.llm_provider in {"openai", "gemini", "anthropic", "huggingface", "ollama"}


# local Ollama models that can look at pictures (a text-only model like qwen2.5 can't)
OLLAMA_VISION = re.compile(r"llava|vision|-vl|vl:|gemma3|minicpm-v|moondream|bakllava|qwen2\.5vl|llama4", re.I)


def vision_enabled() -> bool:
    """Can the AI look at screenshots? VISION=auto: yes for the cloud AIs, for Ollama only with a vision model."""
    if not llm_enabled() or settings.vision == "off":
        return False
    if settings.llm_provider == "huggingface":  # only Hugging Face models that read images (…-VL-…, vision)
        return settings.vision == "on" or bool(re.search(r"-vl-|vision|-vl$|llama-4", settings.llm_model or "", re.I))
    if settings.vision == "on" or settings.llm_provider != "ollama":
        return True
    return bool(OLLAMA_VISION.search(settings.llm_model or ""))


_OPTIONAL = _contextvars.ContextVar("qpilot_optional_ai", default=False)
_DESIGN = _contextvars.ContextVar("qpilot_design_batch", default=None)
_PROVIDER_SLOTS = threading.Condition()
_IN_FLIGHT: dict[str, int] = {}


@_contextlib.contextmanager
def _provider_slot(provider: str, deadline: float | None, log):
    from .. import runctl

    wait_until = time.monotonic() + settings.llm_timeout
    if deadline is not None:
        wait_until = min(wait_until, deadline)
    with _PROVIDER_SLOTS:
        if _IN_FLIGHT.get(provider, 0) >= settings.llm_max_in_flight and log:
            log.emit(f"Waiting for a {provider} request slot", "queued", provider=provider)
        while _IN_FLIGHT.get(provider, 0) >= settings.llm_max_in_flight:
            if runctl.stopping():
                raise LLMError(f"the run is stopping ({runctl.reason()})")
            remaining = wait_until - time.monotonic()
            if remaining <= 0:
                raise LLMError(f"Timed out waiting for a {provider} request slot.",
                               diagnostics={"classification": "queue_timeout"})
            _PROVIDER_SLOTS.wait(min(0.25, remaining))
        if runctl.stopping():
            raise LLMError(f"the run is stopping ({runctl.reason()})")
        concurrency = _IN_FLIGHT[provider] = _IN_FLIGHT.get(provider, 0) + 1
    try:
        yield concurrency
    finally:
        with _PROVIDER_SLOTS:
            _IN_FLIGHT[provider] -= 1
            _PROVIDER_SLOTS.notify_all()



@_contextlib.contextmanager
def design_batch(run_dir, batch_size: int):
    """Attach provider retry and failure events to the run designing these cases."""
    from ..live_frames import EventLog

    log = EventLog(run_dir, "main", role="Test design", phase="test_design") if run_dir else None
    token = _DESIGN.set((log, batch_size))
    try:
        yield
    finally:
        _DESIGN.reset(token)



@_contextlib.contextmanager
def optional_ai():
    """A call whose answer only adds explanation (names for people, failure explanations) and that has its own
    fallback: when it fails, the run is NOT stopped by QA_ALLOW_RULES_FALLBACK=0. That rule is about tests - a Jira /
    owner test must never silently become a rule-based one - and stays in force for every call that designs,
    writes, repairs or judges a test."""
    token = _OPTIONAL.set(True)
    try:
        yield
    finally:
        _OPTIONAL.reset(token)


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
    if not llm_enabled():
        # none / privacy-blocked: fail before any provider routing so callers get a clear rules-fallback signal
        raise LLMError(
            "AI is turned off (LLM_PROVIDER=none or privacy blocks it). Built-in rules are used instead."
        )
    spent = sum(c["cost_usd"] for c in cost._calls)
    if settings.llm_budget_usd and spent >= settings.llm_budget_usd:  # (the agent falls back to its built-in rules)
        raise LLMError(f"AI budget of ${settings.llm_budget_usd} for this run is used up (LLM_BUDGET_USD)")
    prompt = redact(prompt, include_username=True)
    system = (redact(system, include_username=True) + "\n" if system else "") + UNTRUSTED
    if timeout_s is not None and timeout_s <= 0:
        raise LLMError("AI call time limit was reached.")
    deadline = time.monotonic() + timeout_s if timeout_s is not None else None
    attempts = max(1, min(3, max_attempts))
    provider = settings.llm_provider
    log, batch_size = _DESIGN.get() or (None, None)
    for attempt in range(attempts):
        t0 = time.time()
        concurrency = 0
        try:
            schema_args = {"response_schema": response_schema} if response_schema is not None else {}
            with _provider_slot(provider, deadline, log) as concurrency:
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
            diagnostics = e.diagnostics
            if diagnostics:
                diagnostics.update(attempts=attempt + int(concurrency > 0), concurrency=concurrency,
                                   input_tokens=None, output_tokens=None)
                if batch_size is not None:
                    diagnostics["batch_size"] = batch_size
                print(f"  [llm] {settings.llm_provider} {json.dumps(diagnostics, sort_keys=True)}", flush=True)
            hint = diagnostics.get("retry_after_s")
            wait = (hint if hint is not None else 2 ** attempt) + random.uniform(0.1, 0.5)
            retry_allowed = (attempt + 1 < attempts and wait <= 60 and not runctl.stopping()
                             and (deadline is None or time.monotonic() + wait < deadline))
            retryable = (busy and diagnostics.get("classification") != "quota") or (timed_out and attempt == 0)
            if not (retry_allowed and retryable):
                if log and diagnostics:
                    log.emit(str(e), "blocked", provider=settings.llm_provider, diagnostics=diagnostics)
                import os
                if os.environ.get("QA_ALLOW_RULES_FALLBACK", "1") == "0" and not _OPTIONAL.get():
                    reason = str(e) if diagnostics else "The selected AI failed and rules fallback was not approved."
                    runctl.request_stop("ai_unavailable", reason)
                raise
            retry_message = f"{settings.llm_provider} retrying in {wait:.1f}s"
            print(f"  [llm] {retry_message}", flush=True)
            if log:
                log.emit(retry_message, "retrying", provider=settings.llm_provider, diagnostics=diagnostics)
            while wait > 0:
                if runctl.stopping():
                    raise LLMError(f"the run is stopping ({runctl.reason()})") from None
                interval = min(wait, 0.25)
                time.sleep(interval)
                wait -= interval
            if runctl.stopping():
                raise LLMError(f"the run is stopping ({runctl.reason()})") from None


def _raise_with_reason(r: requests.Response) -> None:
    """Like raise_for_status(), but keeps the provider's own explanation (e.g. "temperature not supported")."""
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        status = getattr(r, "status_code", None)
        if status in (429, 503):
            raise requests.HTTPError(f"HTTP {status}", response=r) from None
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

        if p == "huggingface":  # OpenAI-compatible chat API of Hugging Face Inference Providers
            user = prompt if not images else [{"type": "text", "text": prompt}] + [
                {"type": "image_url", "image_url": {"url": f"data:{_mime(i)};base64,{_b64(i)}"}} for i in images]
            body = {"model": model, "temperature": temperature, "messages": [
                {"role": "system", "content": system or "You are a helpful assistant."},
                {"role": "user", "content": user},
            ]}
            r = requests.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.huggingface_api_key}"},
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

    raise LLMError(
        f"Unknown LLM_PROVIDER '{p}'. Supported providers for AI calls: openai, gemini, anthropic, huggingface, ollama."
    )


def ask_structured(prompt: str, shape, system: str = "", agent: str = "", page: str = "", test: str = "",
                   images: list[bytes] | None = None, timeout_s: float | None = None, *,
                   expected_items: int | None = None):
    """Ask for JSON and VALIDATE it against `shape` (a pydantic model, or e.g. list[Model]) before anything uses it.
    A malformed or invalid answer gets ONE corrective retry - the AI is told exactly what was wrong - then LLMError
    (the agent falls back to its built-in rules). A LIST is checked item by item: the valid items are used and the
    invalid ones left out (said in the log) - one test case with a single step no longer throws away the other nine;
    only an answer without any valid item is asked again. Budget, busy / timeout retries: see ask_llm.
    For ordered lists, expected_items enforces the count and preserves invalid items as empty positions.
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
            if expected_items is not None and len(data) != expected_items:
                raise ValueError(f"expected exactly {expected_items} ordered items; received {len(data)}")
            kept, bad = [], []
            for item in data:
                try:
                    kept.append(one.validate_python(item))
                except ValidationError as e:
                    bad.append(" | ".join(str(e).splitlines()[:3])[:200])
                    if expected_items is not None:
                        kept.append(None)
            if bad and len(bad) == len(data):
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
    body = text[start:]
    try:
        obj, _ = json.JSONDecoder().raw_decode(body)
    except json.JSONDecodeError as e:
        # the most common slip of a model: a comma before a closing } or ] - harmless, so it is accepted
        lenient = re.sub(r",(\s*[}\]])", r"\1", body)
        try:
            obj, _ = json.JSONDecoder().raw_decode(lenient)
        except json.JSONDecodeError:
            near = body[max(0, e.pos - 40):e.pos + 20].replace("\n", " ")
            raise LLMError(f"Invalid JSON in LLM answer: {e.msg} at line {e.lineno} column {e.colno}, near "
                           f"{near!r} (check for a missing comma or quote, or a comment)") from e
    return obj


def extract_code(text: str) -> str:
    """Pull Python code out of an LLM answer (handles ```python fences)."""
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip() + "\n"
