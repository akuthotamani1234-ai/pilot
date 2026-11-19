"""Your own tests, in plain English (TestOptim: "add a test in plain English").

  One test per line, e.g. "Search for 'Blue Top', add it to the cart - the cart shows it with its price". They are kept
  per website (baseline/<site>/my_tests.json, kept by --fresh too) and EVERY run of that website includes them: the AI
  turns each one into steps and checks from what exploring really found (test_design.my_test_cases), and the scripts
  are written like the AI's own journeys. A test the website has no page / control for, or a run without an AI, keeps
  it in the test cases as 'Not automated' with the reason - it is never silently dropped.
  Where you write them: the chat's start card ('Your own tests'), the review step, or main.py --my-test "...".
"""
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
        tenant = (os.getenv("QPILOT_TENANT_ID") or "").strip()
        if tenant and re.fullmatch(r"[\w.-]+", tenant):
            return settings.baseline_dir / tenant / key
        return settings.baseline_dir / key
    tenant = tenant_id.strip()
    if not re.fullmatch(r"[\w.-]+", tenant):
        return settings.baseline_dir / ".none" / key
    return settings.baseline_dir / tenant / key


def _file(site_key: str, tenant_id: str | None = None) -> Path:
    return baseline_folder(site_key, tenant_id) / FILE


def load(site_key: str, tenant_id: str | None = None) -> list[dict]:
    try:
        return json.loads(_file(site_key, tenant_id).read_text(encoding="utf-8"))
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
    known = {t["text"].lower(): t for t in load(site_key, tenant_id)}
    tests = [_entry(t, known.get(t.lower())) for t in _clean(texts)]
    f = _file(site_key, tenant_id)
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
