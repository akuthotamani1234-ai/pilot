"""A one-time code (OTP) a PERSON types for an Android run.

When an app shows a code screen (a box for the code sent by SMS or e-mail), the run cannot read that code itself. It
asks the person instead and waits:

  runs/<run>/needs_code.json   {"screen": ..., "field": ..., "asked_at": ..., "wait_s": ...}  -> the Studio shows a box
  runs/<run>/code.txt          what the person typed (written by POST /api/runs/<run>/code), read once and deleted

The code is typed into the app and never written to a test, a flow, a report or a log. Nothing waits when the run
was given no time for a person (human_wait_s = 0): the screen is then reported as needing a person.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

CODE_FIELD = re.compile(r"\b(otp|one[- ]?time|verification code|verify code|security code|confirmation code|"
                        r"enter (?:the |your )?(?:\d[- ]digit )?code|\d[- ]digit code|sms code|code sent|"
                        r"passcode|pin sent)\b", re.I)
CODE = re.compile(r"[A-Za-z0-9]{3,12}")
REQUEST, ANSWER = "needs_code.json", "code.txt"


def code_field(screen: dict) -> dict | None:
    """The box on this screen that asks for a one-time code, or None."""
    if not isinstance(screen, dict):
        return None
    elements = [e for e in screen.get("elements") or [] if isinstance(e, dict)]
    words = " ".join(str(e.get(k) or "") for e in elements if e.get("visible", True)
                     for k in ("text", "accessibility_id", "hint"))
    boxes = [e for e in elements if e.get("input_capable") and e.get("locators") and not e.get("password")]
    if not boxes:
        return None
    for box in boxes:
        if CODE_FIELD.search(" ".join(str(box.get(k) or "") for k in ("hint", "text", "accessibility_id", "resource_id"))):
            return box
    return boxes[0] if CODE_FIELD.search(words) and len(boxes) <= 6 else None


def ask_person(run_dir: Path, screen_name: str, field: str, wait_s: int, stop_path: Path | None = None,
               sleep=time.sleep) -> str:
    """Ask for the code and wait for it. '' = nobody answered in time (or the run was stopped)."""
    if wait_s <= 0:
        return ""
    run_dir = Path(run_dir)
    answer = run_dir / ANSWER
    answer.unlink(missing_ok=True)
    request = run_dir / REQUEST
    request.write_text(json.dumps({"screen": screen_name[:80], "field": field[:80], "asked_at": time.time(),
                                   "wait_s": wait_s}), encoding="utf-8")
    print(f"::need_code::{screen_name[:80]}", flush=True)
    print(f"[android] '{screen_name[:80]}' asks for a one-time code: waiting up to {wait_s} s for you to type it "
          "in Qpilot (it is never saved).", flush=True)
    deadline = time.monotonic() + wait_s
    try:
        while time.monotonic() < deadline:
            if stop_path is not None and Path(stop_path).exists():
                return ""
            if answer.exists():
                code = answer.read_text(encoding="utf-8").strip()
                answer.unlink(missing_ok=True)
                if CODE.fullmatch(code):
                    return code
            sleep(1)
        return ""
    finally:
        request.unlink(missing_ok=True)


def give_code(run_dir: Path, code: str) -> None:
    """The Studio's answer: only while the run is asking, only a plausible code, readable by this user only."""
    run_dir = Path(run_dir)
    code = (code or "").strip()
    if not (run_dir / REQUEST).exists():
        raise ValueError("This run is not waiting for a code.")
    if not CODE.fullmatch(code):
        raise ValueError("Enter the code as it was sent: 3 to 12 letters or digits.")
    path = run_dir / ANSWER
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(code)


def waiting(run_dir: Path) -> dict | None:
    """What the Studio shows while a run waits for a code (never the code)."""
    try:
        data = json.loads((Path(run_dir) / REQUEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    left = max(0, int(data.get("asked_at", 0) + data.get("wait_s", 0) - time.time()))
    return {"screen": data.get("screen", ""), "field": data.get("field", ""), "seconds_left": left}
