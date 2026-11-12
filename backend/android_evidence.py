"""What a manual tester attaches to a bug report: app crashes / ANRs from the device log, and a screen recording.

Each test notes the device clock when it starts. Afterwards only the crash and system logs since then are read
(fast), and a crash or "not responding" of THIS app turns the test into a failure with the exception as evidence.
For failed tests the app's own log lines are saved (logcat/<case>.txt), and multi-step tests keep a screen recording
(videos/<case>.mp4). Recordings of tests that typed into fields are never kept (a password could be on screen).
"""

import base64
import re
import subprocess
from pathlib import Path

from .safety import redact

LINE = re.compile(r"^\s*(?P<time>\d+\.\d+)\s+(?P<pid>\d+)\s+\d+\s+(?P<level>[VDIWEFA])\s+(?P<tag>[^:]*?)\s*:\s?(?P<message>.*)$")
MAX_VIDEO_BYTES = 40 * 1024 * 1024


def _adb():
    from .android import _adb_path
    return _adb_path()


def device_time(device_id: str) -> float | None:
    """The device's own clock (log timestamps use it; the computer's clock can differ)."""
    adb = _adb()
    if not adb:
        return None
    from .android import _run_cli
    try:
        result = _run_cli(adb, ["-s", device_id, "shell", "date", "+%s"], 10)
        value = result.stdout.strip()
        return float(value) if result.returncode == 0 and value.isdigit() else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def read_log(device_id: str, since: float | None, buffers=("crash", "system")) -> list[str]:
    adb = _adb()
    if not adb or since is None:
        return []
    from .android import _run_cli
    args = ["-s", device_id, "logcat", "-d", "-v", "epoch", "-t", f"{max(0.0, since - 1):.3f}"]
    for buffer in buffers:
        args += ["-b", buffer]
    try:
        result = _run_cli(adb, args, 20)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return result.stdout.splitlines()[-20000:] if result.returncode == 0 else []


def _message(line: str) -> tuple[str, str, str]:
    match = LINE.match(line)
    return (match["pid"], match["tag"].strip(), match["message"]) if match else ("", "", line)


def app_problem(lines: list[str], package: str) -> dict | None:
    """A crash (FATAL EXCEPTION) or ANR of this app in these log lines, with a one-line summary."""
    if not package:
        return None
    process = re.compile(r"Process: " + re.escape(package) + r"(?:,|\s|$)")
    anr = re.compile(r"ANR in " + re.escape(package) + r"(?:\s|$)")
    for index, line in enumerate(lines):
        _, _, message = _message(line)
        if "FATAL EXCEPTION" in message:
            window = [_message(w)[2] for w in lines[index + 1:index + 8]]
            if not any(process.search(w) for w in window):
                continue
            after = window[next(i for i, w in enumerate(window) if process.search(w)) + 1:]
            summary = next((w.strip() for w in after if w.strip() and not w.strip().startswith("at ")), "")
            return {"kind": "crash", "summary": summary[:300] or "FATAL EXCEPTION"}
        if anr.search(message):
            window = [_message(w)[2] for w in lines[index + 1:index + 8]]
            reason = next((w.split("Reason:", 1)[1].strip() for w in window if "Reason:" in w), "")
            return {"kind": "anr", "summary": reason[:300] or "Application Not Responding"}
    return None


def save_log(run_dir: Path, case_id: str, lines: list[str], package: str, device_id: str) -> str | None:
    """Only this app's lines (its process, its crash and ANR entries), bounded and redacted."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", case_id):
        raise ValueError("Invalid evidence name")
    pids = {m.group(1) for line in lines for m in [re.search(r"Process: " + re.escape(package) + r", PID: (\d+)", line)] if m}
    adb = _adb()
    if adb:
        from .android import _run_cli
        try:
            result = _run_cli(adb, ["-s", device_id, "shell", "pidof", package], 10)
            pids.update(result.stdout.split())
        except (OSError, subprocess.TimeoutExpired):
            pass
    kept = [line for line in lines if package in line or "AndroidRuntime" in _message(line)[1]
            or "ANR in" in line or _message(line)[0] in pids]
    if not kept:
        return None
    path = run_dir / "logcat" / (case_id + ".txt")
    path.parent.mkdir(exist_ok=True)
    path.write_text(redact("\n".join(kept[-400:])) + "\n", encoding="utf-8")
    return path.relative_to(run_dir).as_posix()


def start_recording(driver) -> bool:
    try:
        driver.start_recording_screen(timeLimit=180, bitRate=1500000, forceRestart=True)
        return True
    except Exception:
        return False


def stop_recording(driver, run_dir: Path, case_id: str, keep: bool) -> str | None:
    """Always stop the recorder; write the video only when it is evidence for a failure."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", case_id):
        raise ValueError("Invalid evidence name")
    try:
        data = driver.stop_recording_screen()
    except Exception:
        return None
    if not keep or not data:
        return None
    try:
        raw = base64.b64decode(data)
    except ValueError:
        return None
    if not raw or len(raw) > MAX_VIDEO_BYTES:
        return None
    path = run_dir / "videos" / (case_id + ".mp4")
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(raw)
    return path.relative_to(run_dir).as_posix()
