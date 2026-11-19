"""Your own tests, in plain English (TestOptim: "add a test in plain English").

  One test per line, e.g. "Search for 'Blue Top', add it to the cart - the cart shows it with its price". They are kept
  per website (baseline/<site>/my_tests.json, kept by --fresh too) and EVERY run of that website includes them: the AI
  turns each one into steps and checks from what exploring really found (test_design.my_test_cases), and the scripts
  are written like the AI's own journeys. A test the website has no page / control for, or a run without an AI, keeps
  it in the test cases as 'Not automated' with the reason - it is never silently dropped.
  Where you write them: the chat's start card ('Your own tests'), the review step, or main.py --my-test "...".
"""
import contextvars
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .config import settings

MAX_TESTS = 30  # per website
FILE = "my_tests.json"
_baseline_tenant: contextvars.ContextVar[str] = contextvars.ContextVar("qpilot_baseline_tenant", default="")


def push_baseline_tenant(tenant_id: str):
    """Use this tenant's baseline until the token is reset. A bad id uses the shared folder."""
    tenant = (tenant_id or "").strip()
    if tenant and not re.fullmatch(r"[\w.-]+", tenant):
        tenant = ""
    return _baseline_tenant.set(tenant)


def pop_baseline_tenant(token) -> None:
    _baseline_tenant.reset(token)


def current_baseline_tenant() -> str:
    return _baseline_tenant.get()


def site_key_of(url: str) -> str:
    """The baseline name of a website address (the same as main.py: host, plus the port when it has one)."""
    p = urlparse(url if "://" in url else "https://" + url)
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", (p.hostname or "") + (f"_{p.port}" if p.port else ""))


def baseline_folder(site_key: str, tenant_id: str | None = None) -> Path:
    """baseline/<site>, or baseline/<tenant>/<site> when a tenant is signed in.

    An explicit tenant id never falls back to the shared folder. A missing id uses
    QPILOT_TENANT_ID from the worker, then the shared folder.
    """
    key = site_key or "site"
    if tenant_id is None:
        tenant = (_baseline_tenant.get() or os.getenv("QPILOT_TENANT_ID") or "").strip()
        if tenant and re.fullmatch(r"[\w.-]+", tenant):
            return settings.baseline_dir / tenant / key
        return settings.baseline_dir / key
    tenant = tenant_id.strip()
    if not re.fullmatch(r"[\w.-]+", tenant):
        return settings.baseline_dir / ".none" / key
    return settings.baseline_dir / tenant / key


def _file(site_key: str, tenant_id: str | None = None) -> Path:
    return baseline_folder(site_key, tenant_id) / FILE


def baseline_dirs_saved_by(run_id: str, tenant_id: str = "") -> list[Path]:
    """Site folders whose meta names this run.

    A tenant only matches baseline/<tenant>/<site>. A run with no tenant only
    matches the shared baseline/<site>. A link is left in place.
    """
    root = Path(settings.baseline_dir)
    tenant = (tenant_id or "").strip()
    parent = root / tenant if tenant and re.fullmatch(r"[\w.-]+", tenant) else root
    if not parent.is_dir() or baseline_is_linked(parent):
        return []
    found: list[Path] = []
    for meta in parent.glob("*/meta.json"):
        if baseline_is_linked(meta):
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        site = meta.parent
        if isinstance(data, dict) and data.get("run_id") == run_id and not site.is_symlink():
            found.append(site)
    return found


def baseline_is_linked(path: Path) -> bool:
    """True when a baseline path follows a symlink.

    A tenant folder that is a link can point at another tenant. Reading or
    writing that path would use the other tenant's files.
    """
    root = Path(settings.baseline_dir)
    try:
        rel = Path(os.path.normpath(path)).relative_to(Path(os.path.normpath(root)))
    except ValueError:
        return True
    cursor = root
    for part in rel.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return True
    return False


def load(site_key: str, tenant_id: str | None = None) -> list[dict]:
    path = _file(site_key, tenant_id)
    if baseline_is_linked(path):
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _clean(texts) -> list[str]:
    out = []
    for t in texts or []:
        t = " ".join(str(t).split())[:300]
        if len(t) >= 5 and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out[:MAX_TESTS]


def _entry(text: str, old: dict | None = None) -> dict:
    return old or {"id": "MY-" + hashlib.sha1(text.lower().encode(), usedforsecurity=False).hexdigest()[:8].upper(),
                   "text": text, "added": datetime.now().strftime("%Y-%m-%d %H:%M")}


def save(site_key: str, texts, tenant_id: str | None = None) -> list[dict]:
    """The list becomes exactly these tests (the chat's box: what is in it is the list; empty = none)."""
    f = _file(site_key, tenant_id)
    if baseline_is_linked(f):
        return []
    known = {t["text"].lower(): t for t in load(site_key, tenant_id)}
    tests = [_entry(t, known.get(t.lower())) for t in _clean(texts)]
    if tests or f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(tests, indent=1), encoding="utf-8")
    return tests


def add(site_key: str, texts, tenant_id: str | None = None) -> list[dict]:
    """More tests on top of the saved ones (the review step, main.py --my-test)."""
    return save(site_key, [t["text"] for t in load(site_key, tenant_id)] + list(texts or []), tenant_id)


def lines(text: str) -> list[str]:
    """The box's text -> one test per line (bullets / numbers in front are left out)."""
    return _clean(re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", x) for x in (text or "").splitlines())
