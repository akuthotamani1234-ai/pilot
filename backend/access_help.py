"""When the application will not let the tester in: bot protection, a CAPTCHA wall, rate limits, access denied, SSO /
MFA that only a person can complete. The tester never solves, hides from or tricks such a check. It:

  1. recognises it (detect) - never reported as a functional defect of the application,
  2. pauses the run, durably: runs/<run>/pause.json says what blocks it, where, since when, and what helps,
  3. lets an authorized person help: sign in / pass the check in their OWN browser, then hand the tester that
     session (a Playwright storage state, or a Cookie header) through the Studio (POST /api/runs/{job}/help) - only
     cookies of the application's own domain are accepted, and they stay in the run's private folder,
  4. checks that access really works with that session, and resumes from where it stopped (the run's browser state,
     the selected requirements and the steps done so far are kept: it is the same run),
  5. or, when nobody helps within the wait, stops that part as Blocked with the exact blocker and what would help.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

PAUSE = "pause.json"
HELP = ".private/help.json"
KINDS = {
    "bot_protection": "a bot-protection check ({vendor}) stands in front of the application",
    "captcha": "the application shows a CAPTCHA",
    "rate_limited": "the application answers 'too many requests' (HTTP 429)",
    "access_denied": "the application refuses this network / browser (HTTP 403 'access denied')",
    "mfa_required": "the login asks for a one-time code (2-step verification)",
    "sso_redirect": "the login moves to a single sign-on provider",
}
HELPS = {
    "bot_protection": "ask the owner to allow the tester (IP allowlist / a test environment without the check), or "
                      "pass the check in your own browser and give the tester that session",
    "captcha": "switch the CAPTCHA off in the test environment, or sign in in your own browser and give the tester "
               "that session",
    "rate_limited": "wait, or ask the owner to raise the limit for the test environment",
    "access_denied": "ask the owner to allow this network (IP allowlist / VPN) for testing",
    "mfa_required": "give the test account's authenticator key (TOTP), or sign in in your own browser and give the "
                    "tester that session",
    "sso_redirect": "add the SSO provider to the approved scope, or sign in in your own browser and give the tester "
                    "that session",
}
DENIED = re.compile(r"access denied|you don't have permission to access|request blocked|forbidden|"
                    r"reference #\d+\.\w+|errors\.edgesuite\.net", re.I)


def detect(status: int | None, title: str = "", text: str = "", html: str = "") -> dict | None:
    """What keeps the tester out of this page, or None for a normal page."""
    from .android_web import BOT_TEXT, BOT_TITLE
    from .auth import CAPTCHA
    words = " ".join([title, text[:4000], html[:20000]]).casefold()
    vendor = ("Cloudflare" if "cloudflare" in words or "cf-chl" in words or "ray id" in words else
              "Akamai" if "akamai" in words or "edgesuite" in words or "reference #" in words else
              "Imperva" if "incapsula" in words or "imperva" in words else
              "DataDome" if "datadome" in words else "PerimeterX" if "perimeterx" in words or "px-captcha" in words
              else "")
    if BOT_TITLE.search(title or "") or BOT_TEXT.search(text or "") or (vendor and status in (403, 503)):
        return _found("bot_protection", vendor or "unknown vendor")
    if status == 429:
        return _found("rate_limited", vendor)
    if CAPTCHA.search(html or "") and len(re.findall(r"<input\b", html or "", re.I)) <= 3:
        return _found("captcha", vendor)
    if status == 403 and DENIED.search(" ".join([title, text[:2000]])):
        return _found("access_denied", vendor)
    return None


def _found(kind: str, vendor: str = "") -> dict:
    return {"kind": kind, "vendor": vendor, "message": KINDS[kind].format(vendor=vendor or "unknown vendor"),
            "help": HELPS[kind]}


def pause(run_dir: Path, block: dict, url: str, wait_s: int) -> None:
    data = {**block, "url": url[:300], "since": time.time(), "wait_s": wait_s, "state": "waiting",
            "how_to_help": "POST /api/runs/{job}/help with the session from your own browser (Playwright storage "
                           "state JSON, or a Cookie header) - only this application's own cookies are used"}
    _write(run_dir / PAUSE, data)


def wait_for_help(run_dir: Path, block: dict, url: str, wait_s: int, stop=None) -> dict | None:
    """Pause the run (pause.json) and wait up to wait_s for an authorized person's session. Returns the help
    ({"cookies": [...]}) or None when nobody helped in time (pause.json then says so)."""
    run_dir = Path(run_dir)
    pause(run_dir, block, url, wait_s)
    print(f"  [access] paused: {block['message']} at {url} - waiting up to {wait_s} s for help "
          f"({block['help']})", flush=True)
    deadline = time.monotonic() + max(0, wait_s)
    helped = None
    while time.monotonic() < deadline:
        if stop and stop():
            break
        f = run_dir / HELP
        if f.is_file() and not f.is_symlink():
            try:
                helped = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                helped = None
            try:
                f.unlink()
            except OSError:
                pass
            break
        time.sleep(1)
    state = json.loads((run_dir / PAUSE).read_text(encoding="utf-8"))
    state.update(state="resumed" if helped else "timed_out", ended=time.time())
    _write(run_dir / PAUSE, state)
    print(f"  [access] {'help received - resuming' if helped else 'nobody helped in time - this part is Blocked'}",
          flush=True)
    return helped


def accept_help(run_dir: Path, target_url: str, storage_state: dict | None = None, cookie_header: str = "") -> int:
    """Store an authorized person's session for the paused run: only cookies of the application's own domain are
    kept. Returns how many cookies were accepted (0 -> nothing usable was given)."""
    host = (urlparse(target_url).hostname or "").lower()
    site = ".".join(host.split(".")[-2:]) if host.count(".") >= 1 else host
    cookies = []
    for c in (storage_state or {}).get("cookies") or []:
        domain = str(c.get("domain") or "").lstrip(".").lower()
        if domain and (domain == host or host.endswith("." + domain) or domain.endswith("." + site) or domain == site):
            cookies.append({k: c[k] for k in ("name", "value", "domain", "path", "expires", "httpOnly", "secure",
                                              "sameSite") if k in c})
    for part in (cookie_header or "").split(";"):
        if "=" in part:
            name, value = part.split("=", 1)
            if name.strip():
                cookies.append({"name": name.strip(), "value": value.strip(), "domain": host, "path": "/"})
    if not cookies:
        return 0
    private = Path(run_dir) / ".private"
    private.mkdir(exist_ok=True)
    _write(Path(run_dir) / HELP, {"cookies": cookies[:200], "at": time.time()})
    return len(cookies[:200])


def apply(context, helped: dict) -> int:
    """Give the run's browser the person's session (its cookies)."""
    cookies = [c for c in (helped or {}).get("cookies") or [] if c.get("name") and c.get("domain")]
    if cookies:
        context.add_cookies([{**c, "path": c.get("path") or "/"} for c in cookies])
    return len(cookies)


def _write(path: Path, data: dict) -> None:
    from .finalization import folder_is_linked
    if folder_is_linked(path.parent) or path.is_symlink():
        return
    path.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
