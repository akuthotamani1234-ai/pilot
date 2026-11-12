"""One persisted privacy policy for the Studio, workers and MCP data access."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import requests
from pydantic import BaseModel, ConfigDict, model_validator

ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / ".private" / "privacy.json"
CLOUD_PROVIDERS = {"openai", "gemini", "anthropic"}
LOCAL_PROVIDERS = {"ollama", "none"}


class PrivacyError(ValueError):
    pass


class PrivacyPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["local", "cloud"] = "local"
    cloud_consent: bool = False
    allow_mcp: bool = False
    local_assistant_confirmed: bool = False

    @model_validator(mode="after")
    def consent_required(self):
        if self.mode == "cloud" and not self.cloud_consent:
            raise ValueError("Confirm which data may be shared before enabling cloud assistance.")
        if self.mode == "local" and self.allow_mcp and not self.local_assistant_confirmed:
            raise ValueError("For local-only MCP, confirm that your assistant processes data locally.")
        if self.mode == "local":
            self.cloud_consent = False
        else:
            self.local_assistant_confirmed = False
        return self


def load_policy() -> PrivacyPolicy:
    try:
        return PrivacyPolicy.model_validate_json(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return PrivacyPolicy()  # missing/corrupt preferences always fail closed


def save_policy(policy: PrivacyPolicy) -> None:
    POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = POLICY_PATH.with_suffix(".tmp")
    temp.write_text(policy.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temp, POLICY_PATH)


def public_policy(policy: PrivacyPolicy | None = None) -> dict:
    policy = policy or load_policy()
    return {**policy.model_dump(), "mcp_allowed": policy.allow_mcp,
            "allowed_providers": sorted(LOCAL_PROVIDERS | (CLOUD_PROVIDERS if policy.mode == "cloud" else set())),
            "assistant_location_verified": False}


def runtime_mode() -> str:
    # A local worker remains local even if the workspace is subsequently switched to cloud.
    policy = load_policy()
    if os.getenv("BLOWAI_PRIVACY_MODE") == "local":
        return "local"
    return policy.mode


def require_loopback_ai(url: str) -> str:
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                 and parsed.path in {"", "/"} and not parsed.username and not parsed.password
                 and not parsed.query and not parsed.fragment
                 and (parsed.port is None or 1 <= parsed.port <= 65535))
    except ValueError:
        valid = False
    if not valid:
        raise PrivacyError("Use a loopback Ollama address, such as http://127.0.0.1:11434.")
    return url.rstrip("/")


def guard_provider(provider: str, ollama_url: str, mode: str | None = None) -> None:
    mode = mode or runtime_mode()
    if provider not in LOCAL_PROVIDERS | CLOUD_PROVIDERS:
        raise PrivacyError("Choose a supported AI provider.")
    if mode == "local":
        if provider in CLOUD_PROVIDERS:
            raise PrivacyError("Cloud AI is disabled. Enable Cloud assisted in Privacy settings and confirm data sharing.")
    if provider == "ollama":
        require_loopback_ai(ollama_url)


def select_provider(requested: str | None, configured: str, ollama_url: str,
                    expected_mode: str | None = None) -> str:
    policy = load_policy()
    if expected_mode is not None and expected_mode != policy.mode:
        raise PrivacyError("Privacy settings changed. Review the current privacy mode before starting.")
    chosen = requested.lower() if requested else configured.lower()
    # A legacy .env may name a cloud model. Never silently send data or reinterpret that model as local.
    if not requested and policy.mode == "local" and chosen in CLOUD_PROVIDERS:
        chosen = "none"
    guard_provider(chosen, ollama_url, policy.mode)
    return chosen


def apply_worker_policy(env: dict, provider: str | None = None, expected_mode: str | None = None) -> dict:
    policy = load_policy()
    if expected_mode is not None and expected_mode != policy.mode:
        raise PrivacyError("Privacy settings changed. Review them and start again.")
    selected = select_provider(provider, env.get("LLM_PROVIDER", "ollama"),
                               env.get("OLLAMA_URL", "http://localhost:11434"), policy.mode)
    env["LLM_PROVIDER"] = selected
    env["BLOWAI_PRIVACY_MODE"] = policy.mode
    if policy.mode == "local":
        # Explicit blanks prevent the child .env loader from restoring these credentials.
        for key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY",
                    "SLACK_WEBHOOK_URL", "JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT"):
            env[key] = ""
    return public_policy(policy)


def local_ai_request(method: str, url: str, **kwargs):
    """Local model requests never use environment proxies or follow redirects."""
    require_loopback_ai(urlsplit(url)._replace(path="", query="", fragment="").geturl())
    with requests.Session() as session:
        session.trust_env = False
        response = session.request(method, url, allow_redirects=False, **kwargs)
        if 300 <= response.status_code < 400:
            response.close()
            raise PrivacyError("The local AI endpoint redirected the request; redirects are blocked.")
        return response
