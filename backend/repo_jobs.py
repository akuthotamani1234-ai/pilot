"""Isolate repository AI preparation from server settings, credentials and active QA jobs."""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from .finalization import read_json
from .safety import redact

_ACTIVE: dict[str, subprocess.Popen] = {}
_LOCK = threading.Lock()


def status(root: Path) -> dict:
    path = root / ".private" / "repo_fix_status.json"
    value = read_json(path, {"status": "idle"})
    if value.get("status") == "running" and path.exists() and time.time() - path.stat().st_mtime > 450:
        return {"status": "error", "detail": "The preparation worker stopped responding. Prepare the changes again."}
    return value


def _write(root: Path, value: dict) -> None:
    dest = root / ".private" / "repo_fix_status.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix(".tmp")
    temp.write_text(json.dumps(value), encoding="utf-8")
    os.replace(temp, dest)


def start(root: Path, repo_url: str, token: str, selected: list[str]) -> dict:
    from .config import settings
    from .privacy import guard_provider, runtime_mode
    from .repo_fix import RepoFixError, parse_repo
    parse_repo(repo_url)
    guard_provider(settings.llm_provider, settings.ollama_url)
    from .llm import llm_enabled
    if not llm_enabled():
        raise RepoFixError("An available AI provider is required for repository preparation.")
    from .repo_proposals import candidates
    eligible = {item["id"] for item in candidates(root) if item["eligible"]}
    if not selected or len(selected) > 5 or not set(selected) <= eligible:
        raise RepoFixError("Select one to five supported product findings from this report.")
    with _LOCK:
        key = str(root.resolve())
        if (key in _ACTIVE and _ACTIVE[key].poll() is None) or status(root).get("status") == "running":
            raise RepoFixError("Repository preparation is already running.")
        env = dict(os.environ, QPILOT_REPO_TOKEN=token, BLOWAI_PRIVACY_MODE=runtime_mode())
        command = [sys.executable, "-m", "backend.repo_jobs", str(root.resolve()), repo_url, json.dumps(selected)]
        _write(root, {"status": "running", "stage": "Reading repository snapshot"})
        try:
            process = subprocess.Popen(command, cwd=Path(__file__).resolve().parent.parent, env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            _write(root, {"status": "error", "detail": "Repository preparation worker could not start."})
            raise RepoFixError("Repository preparation worker could not start.") from exc
        _ACTIVE[key] = process

    def monitor():
        try:
            process.wait(timeout=420)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            _write(root, {"status": "error", "detail": "AI preparation exceeded its seven-minute budget. The QA report remains available."})
        with _LOCK:
            if _ACTIVE.get(key) is process:
                if status(root).get("status") == "running":
                    _write(root, {"status": "error", "detail": "Preparation ended before a proposal was ready. Review provider configuration and try again."})
                _ACTIVE.pop(key, None)
    threading.Thread(target=monitor, daemon=True, name="qpilot-repo-fix").start()
    return status(root)


def _worker():
    root, url, selected_json = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    token = os.environ.pop("QPILOT_REPO_TOKEN", "")
    def expire():
        _write(root, {"status": "error", "detail": "AI preparation exceeded its seven-minute budget."})
        os._exit(1)  # this isolated worker must remain bounded even if the UI server was restarted
    deadline = threading.Timer(420, expire)
    deadline.daemon = True
    deadline.start()
    try:
        from .cost import set_run_dir
        from .repo_fix import _local_copy
        from .repo_proposals import prepare_ai
        cost_dir = root / ".private" / "repo_cost"
        cost_dir.mkdir(parents=True, exist_ok=True)
        set_run_dir(cost_dir)
        snapshot = _local_copy(url, token, root)
        from .config import settings
        settings.github_token = token  # isolated worker only; include an ephemeral token in prompt redaction
        _write(root, {"status": "running", "stage": "Matching findings to source and preparing AI changes"})
        plan = prepare_ai(root, snapshot, json.loads(selected_json))
        _write(root, {"status": "ready", "stage": "Review the diff and validation", "plan": plan})
    except Exception as exc:
        _write(root, {"status": "error", "detail": redact(str(exc), values=[token])[:600]})
    finally:
        deadline.cancel()


if __name__ == "__main__":
    _worker()
