"""Gate C: DemoStore cart add → remove lifecycle confirmation.

Localhost DemoStore only (session cookie). Broader live portal paths still
open — gate_c_complete stays False.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .data_lifecycle import Lifecycle, demo_store_cart_delete, save_lifecycle, to_state

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "demo_store_cart_lifecycle_drill.json"


def _post(url: str, data: dict, *, cookie: str | None = None, allow_redirects: bool = False):
    body = urllib.parse.urlencode(data).encode()
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            raw = resp.read()
            headers_out = {k.lower(): v for k, v in resp.headers.items()}
            return int(getattr(resp, "status", None) or resp.getcode()), raw, headers_out
    except urllib.error.HTTPError as exc:
        if allow_redirects and exc.code in {302, 303}:
            return int(exc.code), b"", {k.lower(): v for k, v in (exc.headers or {}).items()}
        raise


def _signin(base: str) -> str:
    from tests.demo_store import EMAIL, PASSWORD

    # Two-step login: email continue, then password → Set-Cookie sid=
    _post(f"{base}/signin", {"email": EMAIL})
    code, _raw, headers = _post(
        f"{base}/signin/password",
        {"email": EMAIL, "password": PASSWORD},
        allow_redirects=True,
    )
    # urllib follows redirects by default; cookie may be on intermediate. Prefer opener jar.
    # Fallback: parse Set-Cookie from error redirect response when follow is off.
    set_cookie = headers.get("set-cookie") or ""
    if "sid=" in set_cookie:
        return "sid=" + set_cookie.split("sid=")[1].split(";")[0]
    # When redirects are followed, cookie may already be in jar — use CookieProcessor.
    jar = urllib.request.HTTPCookieProcessor()
    opener = urllib.request.build_opener(jar)
    body1 = urllib.parse.urlencode({"email": EMAIL}).encode()
    opener.open(urllib.request.Request(  # noqa: S310
        f"{base}/signin", data=body1,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
    ), timeout=10).read()
    body2 = urllib.parse.urlencode({"email": EMAIL, "password": PASSWORD}).encode()
    opener.open(urllib.request.Request(  # noqa: S310
        f"{base}/signin/password", data=body2,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
    ), timeout=10).read()
    for cookie in jar.cookiejar:
        if cookie.name == "sid" and cookie.value:
            return f"sid={cookie.value}"
    raise RuntimeError(f"DemoStore sign-in did not yield sid (HTTP {code})")


def run_demo_store_cart_lifecycle_drill(*, ops_dir: Path | None = None) -> dict:
    from tests.demo_store import DemoStore

    store = DemoStore(bugs=False).start()
    work = Path(ops_dir) / "demo_store_cart_lifecycle_work" if ops_dir else (
        ROOT / "artifacts" / "ops" / "demo_store_cart_lifecycle_work"
    )
    work.mkdir(parents=True, exist_ok=True)
    run_dir = work / f"run_{int(time.time())}"
    run_dir.mkdir(parents=True, exist_ok=True)
    evidence: dict = {}
    try:
        base = store.url.rstrip("/")
        sid_cookie = _signin(base)
        code, raw, _ = _post(f"{base}/cart/add", {"id": "1", "qty": "1", "size": "M"}, cookie=sid_cookie)
        payload = json.loads(raw.decode() or "{}")
        cart_count = int(payload.get("cart") or 0)
        if code != 200 or cart_count < 1:
            raise RuntimeError(f"cart add failed: HTTP {code} body={raw[:200]!r}")

        life = Lifecycle(run_id=run_dir.name, environment="test")
        life.prepare(1)
        life._by_worker[1] = [{
            "tag": "cart:line:0",
            "kind": "cart",
            "state": "ready",
            "run_id": run_dir.name,
            "remote_id": "0",
            "line": 0,
            "source": "demo_store",
        }]
        adapter = demo_store_cart_delete(base, sid_cookie)
        cleanup = life.cleanup_confirmed(1, remote_delete=adapter)
        save_lifecycle(run_dir, life)

        # Confirm cart empty via session state on the fixture.
        remaining = 0
        for session in store.sessions.values():
            remaining += sum(int(i.get("qty") or 0) for i in (session.get("cart") or []))
        confirmed_n = len(cleanup.get("confirmed") or [])
        failed_n = len(cleanup.get("failed") or [])
        evidence = {
            "gate_c_complete": False,
            "drill": "demo_store_cart_lifecycle_cleanup",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "fixture": "DemoStore",
            "cart_added": cart_count,
            "confirmed": confirmed_n,
            "failed": failed_n,
            "complete": bool(cleanup.get("complete")),
            "cart_empty": remaining == 0,
            "sample_proofs": [
                row.get("cleanup_proof") for row in (cleanup.get("confirmed") or [])[:5]
            ],
            "ok": (
                confirmed_n > 0
                and failed_n == 0
                and bool(cleanup.get("complete"))
                and remaining == 0
            ),
            "state_run_id": to_state(life).get("run_id"),
            "reason": (
                "DemoStore cart add→remove cleanup confirmed on localhost fixture; "
                "broader live portal paths still open"
            ),
        }
    finally:
        try:
            store.stop()
        except Exception:
            pass

    if not evidence:
        evidence = {
            "gate_c_complete": False,
            "drill": "demo_store_cart_lifecycle_cleanup",
            "ok": False,
            "reason": "DemoStore cart lifecycle drill aborted before evidence",
        }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "demo_store_cart_lifecycle_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "demo_store_cart_lifecycle_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
