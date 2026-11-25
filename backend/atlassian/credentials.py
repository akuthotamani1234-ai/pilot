"""Atlassian API tokens entered in the Studio: write-only, per tenant, never returned.

  where     runs/.requirements-credentials.json: {"<tenant>|<secret name>": {"value", "protection", "updated_at"}}
  how       backend/secret_store.protect: Windows DPAPI (only this Windows user on this PC can decrypt it); on other
            systems the file is readable by its owner only (chmod 600) and status() says so
  read      resolver(tenant) -> the function client.Client calls with a connection's token_ref, at request time.
            The tenant's own stored token comes first. Environment variables (.env) are used ONLY by the local
            single-user tenant: with Studio login on, one tenant can never use the token of the server's owner.
  never     an API answer, a log line, a report or the browser gets the token; status() says only whether it is set
"""
from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ..migrate import sqlite_path_is_linked
from ..safety import register_secret_names, register_secret_values
from ..secret_store import protect, unprotect
from .models import LOOKS_LIKE_SECRET, READ_SECRET_NAME

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_FILE = ROOT / "runs" / ".requirements-credentials.json"
LOCAL_TENANT = "local"  # the tenant of the single-user Studio (login off) and of the command line
_lock = threading.Lock()


def _file(path: Path | None) -> Path:
    f = Path(path) if path else DEFAULT_FILE
    if sqlite_path_is_linked(f) or f.is_symlink():
        raise ValueError("The credentials file is a link.")
    return f


def _load(path: Path | None) -> dict:
    f = _file(path)
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise ValueError("The credentials file cannot be read; replace the tokens.") from None
    return data if isinstance(data, dict) else {}


def _save(data: dict, path: Path | None) -> None:
    f = _file(path)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, f)


def _key(tenant_id: str, name: str) -> str:
    tenant = (tenant_id or "").strip()
    if not tenant or "|" in tenant:
        raise ValueError("a tenant is required")
    if not READ_SECRET_NAME.match(name or ""):
        raise ValueError("not an Atlassian read secret name")
    return f"{tenant}|{name}"


def site_of(url: str) -> str:
    """The host a token belongs to ('' for none)."""
    from urllib.parse import urlparse
    return (urlparse((url or "").strip()).hostname or "").lower()


def set_token(tenant_id: str, name: str, value: str, *, path: Path | None = None, site: str = "") -> dict:
    """Store (or replace) a tenant's token. Returns status only. With site, the token is bound to that Atlassian
    site: it is never handed out for another one (a connection whose address changes never sends it elsewhere)."""
    value = (value or "").strip()
    if len(value) < 8 or len(value) > 4000 or any(c.isspace() for c in value):
        raise ValueError("that does not look like an API token (no spaces, at least 8 characters)")
    key = _key(tenant_id, name)
    stored, method = protect(value)
    with _lock:
        data = _load(path)
        data[key] = {"value": stored, "protection": method, "updated_at": datetime.now(UTC).isoformat(),
                     **({"site": site_of(site)} if site_of(site) else {})}
        _save(data, path)
    register_secret_names(name)
    register_secret_values(value)
    return status(tenant_id, name, path=path, site=site)


def delete_token(tenant_id: str, name: str, *, path: Path | None = None) -> bool:
    key = _key(tenant_id, name)
    with _lock:
        data = _load(path)
        found = data.pop(key, None) is not None
        if found:
            _save(data, path)
    return found


ACCOUNT_SLOT = re.compile(r"^[A-Z][A-Z0-9_]{0,19}:(test|staging)$")


def _account_key(tenant_id: str, slot: str) -> str:
    tenant = (tenant_id or "").strip()
    if not tenant or "|" in tenant or not ACCOUNT_SLOT.match(slot or ""):
        raise ValueError("a tenant and a PROJECT:environment slot are required")
    return f"{tenant}|account:{slot}"


def set_account(tenant_id: str, slot: str, username: str, password: str, *, path: Path | None = None) -> None:
    """A saved test account of a project's website (the guided workflow's credential reuse). Kept in this file, the
    same way as the Jira token - never in the requirements database."""
    stored, method = protect(json.dumps({"u": username, "p": password}))
    with _lock:
        data = _load(path)
        data[_account_key(tenant_id, slot)] = {"value": stored, "protection": method,
                                               "updated_at": datetime.now(UTC).isoformat()}
        _save(data, path)
    register_secret_values(password)


def get_account(tenant_id: str, slot: str, *, path: Path | None = None) -> tuple[str, str]:
    try:
        entry = _load(path).get(_account_key(tenant_id, slot))
        raw = json.loads(unprotect(entry["value"], entry.get("protection", "dpapi"))) if entry else {}
    except (OSError, ValueError, KeyError, TypeError):
        return "", ""
    if raw.get("p"):
        register_secret_values(str(raw["p"]))
    return str(raw.get("u", "")), str(raw.get("p", ""))


def delete_account(tenant_id: str, slot: str, *, path: Path | None = None) -> bool:
    with _lock:
        data = _load(path)
        found = data.pop(_account_key(tenant_id, slot), None) is not None
        if found:
            _save(data, path)
    return found


def _stored(tenant_id: str, name: str, path: Path | None, site: str = "") -> str:
    try:
        entry = _load(path).get(_key(tenant_id, name))
    except ValueError:
        return ""
    if not entry:
        return ""
    if site and entry.get("site") and entry["site"] != site_of(site):
        return ""  # (saved for another Atlassian site: never sent to this one)
    try:
        value = unprotect(entry["value"], entry.get("protection", "dpapi"))
    except (OSError, ValueError, KeyError):
        return ""  # (made by another Windows user / PC)
    register_secret_values(value)
    return value


def status(tenant_id: str, name: str, *, path: Path | None = None, site: str = "") -> dict:
    """{'configured', 'source': 'studio' | 'environment' | '', 'protection', 'updated_at'} - never the token."""
    try:
        entry = _load(path).get(_key(tenant_id, name)) or {}
    except ValueError:
        entry = {}
    if entry and _stored(tenant_id, name, path, site):
        return {"configured": True, "source": "studio", "protection": entry.get("protection", ""),
                "updated_at": entry.get("updated_at", "")}
    if tenant_id == LOCAL_TENANT and os.environ.get(name, "").strip():
        return {"configured": True, "source": "environment", "protection": "", "updated_at": ""}
    return {"configured": False, "source": "", "protection": "", "updated_at": ""}


def resolver(tenant_id: str, *, path: Path | None = None, allow_env: bool | None = None,
             site: str = "") -> Callable[[str], str]:
    """The secret function for client.Client(secret=...): the tenant's stored token, else the environment variable
    of that name - by default only for the local tenant. The command line (run by the machine's owner) passes
    allow_env=True."""
    env_ok = (tenant_id == LOCAL_TENANT) if allow_env is None else allow_env

    def secret(name: str) -> str:
        value = _stored(tenant_id, name, path, site)
        if not value and env_ok:
            value = os.environ.get(name, "").strip()
        return value
    return secret


def looks_like_token(text: str) -> bool:
    return bool(LOOKS_LIKE_SECRET.search(text or ""))
