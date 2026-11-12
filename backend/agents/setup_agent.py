"""Agent 0 — Setup Agent.

Input can be:
  * a website URL                  -> nothing to do, go straight to Discovery
  * a GitHub link                  -> clone it into workspace/ (or download a .zip if git is not
                                      installed), then treat it like a local folder
  * a local project folder         -> detect the project type, install, start it on localhost

Supported project types (auto-detected):
  Node / React / Vite / Next / Angular   (package.json)
  Django                                 (manage.py)
  Flask / FastAPI                        (a .py file creating Flask(...) / FastAPI(...))
  Plain HTML                             (index.html in root, dist/, build/, public/, docs/)
You can always override with START_CMD / APP_PORT in .env or --start-cmd / --port.

WARNING: this runs someone else's code on your machine. Only use repos you trust.
(Phase 10 of the roadmap moves this into a Docker sandbox.)
"""
import io
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import requests

from ..config import settings
from ..state import QAState

GITHUB_RE = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([^/\s]+)/([^/\s#?]+?)(?:\.git)?(?:/tree/([^\s#?]+))?/?$")
URL_IN_OUTPUT = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1?\]):(\d+)[^\s]*")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
IS_WINDOWS = os.name == "nt"

_running: list[subprocess.Popen] = []   # servers we started (stopped at the end of the run)


# ------------------------------------------------------------------ input type

def is_github(source: str) -> bool:
    return bool(GITHUB_RE.match(source.strip()))


def is_local_project(source: str) -> bool:
    return Path(source).expanduser().is_dir()


def project_name(source: str) -> str:
    m = GITHUB_RE.match(source.strip())
    if m:
        return m.group(2)
    return Path(source).expanduser().resolve().name


# ------------------------------------------------------------------ helpers

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _mask(text: str) -> str:
    """Never show a token on screen or in logs."""
    return re.sub(r"//[^/@\s]+@github\.com", "//***@github.com", text)


def _run(cmd: str, cwd: Path, log_file: Path, timeout: int = 900) -> None:
    print(f"  [setup] $ {_mask(cmd)}")
    with log_file.open("a", encoding="utf-8", errors="replace") as log:
        log.write(f"\n$ {_mask(cmd)}\n")
        log.flush()
        from ..safety import clean_env  # (install scripts of the project never see your API keys / test password)
        # (a shell: the project's own install commands, e.g. `npm install` = npm.cmd on Windows)
        r = subprocess.run(cmd, check=False, cwd=cwd, shell=True, stdout=log,  # noqa: S602
                           stderr=subprocess.STDOUT, timeout=timeout, env=clean_env(os.environ.copy()))
    if r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {_mask(cmd)}  - see {log_file}")


def _download_zip(owner: str, repo: str, branch: str | None, dest: Path) -> Path:
    """No git on this PC -> download the repo as a .zip from GitHub and unpack it."""
    print(f"  [setup] git is not installed - downloading {owner}/{repo} as a zip instead")
    headers = {"Authorization": f"Bearer {settings.github_token}"} if settings.github_token else {}
    url = f"https://api.github.com/repos/{owner}/{repo}/zipball" + (f"/{branch}" if branch else "")
    r = requests.get(url, headers=headers, timeout=300)
    if r.status_code == 404:
        raise RuntimeError(f"GitHub repo not found: {owner}/{repo} (private repo? set GITHUB_TOKEN in .env)")
    r.raise_for_status()
    shutil.rmtree(dest, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        top = z.namelist()[0].split("/")[0]          # GitHub puts everything in one top folder
        z.extractall(dest.parent / f"_{repo}_zip")
    shutil.move(str(dest.parent / f"_{repo}_zip" / top), str(dest))
    shutil.rmtree(dest.parent / f"_{repo}_zip", ignore_errors=True)
    return dest


def _clone(source: str, log_file: Path) -> Path:
    owner, repo, branch = GITHUB_RE.match(source.strip()).groups()
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    dest = (settings.workspace_dir / repo).resolve()
    if not shutil.which("git"):
        return _download_zip(owner, repo, branch, dest)
    auth = f"x-access-token:{settings.github_token}@" if settings.github_token else ""
    url = f"https://{auth}github.com/{owner}/{repo}.git"
    if dest.exists():  # already downloaded before -> just get the latest changes
        try:
            _run("git pull --ff-only", dest, log_file, timeout=300)
            return dest
        except RuntimeError:
            shutil.rmtree(dest, ignore_errors=True)
    branch_opt = f"--branch {branch} " if branch else ""
    _run(f'git clone --depth 1 {branch_opt}"{url}" "{dest}"', settings.workspace_dir.resolve(), log_file, timeout=600)
    return dest


def _find_python_app(root: Path, marker: str) -> str | None:
    for f in sorted(root.glob("*.py")) + sorted(root.glob("app/*.py")) + sorted(root.glob("src/*.py")):
        try:
            if marker in f.read_text(encoding="utf-8", errors="ignore"):
                return ".".join(f.relative_to(root).with_suffix("").parts)
        except OSError:
            pass
    return None


def detect_project(root: Path, port: int) -> dict:
    """Decide how to install and start the project."""
    py = f'"{sys.executable}"'
    req = root / "requirements.txt"
    pip = [f"{py} -m pip install -r requirements.txt"] if req.exists() else []

    if settings.start_cmd:
        return {"type": "custom", "install": [], "start": settings.start_cmd.replace("{port}", str(port))}

    pkg = root / "package.json"
    if pkg.exists():
        scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {})
        install = ["npm install"]
        if "dev" in scripts:
            dev = scripts["dev"]
            extra = f" -- --port {port}" if re.search(r"\b(vite|next|nuxt|astro)\b", dev) else ""
            return {"type": "node (npm run dev)", "install": install, "start": f"npm run dev{extra}"}
        if "start" in scripts:
            start = scripts["start"]
            extra = f" -- --port {port}" if re.search(r"\bng serve\b", start) else ""
            return {"type": "node (npm start)", "install": install, "start": f"npm start{extra}"}
        if "serve" in scripts:
            return {"type": "node (npm run serve)", "install": install, "start": f"npm run serve -- --port {port}"}

    if (root / "manage.py").exists():
        return {"type": "django", "install": pip + [f"{py} manage.py migrate --noinput"],
                "start": f"{py} manage.py runserver 127.0.0.1:{port} --noreload"}

    mod = _find_python_app(root, "Flask(")
    if mod:
        return {"type": "flask", "install": pip, "start": f"{py} -m flask --app {mod} run --port {port}"}

    mod = _find_python_app(root, "FastAPI(")
    if mod:
        return {"type": "fastapi", "install": pip + [f"{py} -m pip install uvicorn"],
                "start": f"{py} -m uvicorn {mod}:app --port {port}"}

    for d in ("", "dist", "build", "public", "docs", "site", "www", "src"):
        if (root / d / "index.html").exists():
            folder = root / d
            return {"type": "static html", "install": [],
                    "start": f'{py} -m http.server {port} --bind 127.0.0.1 --directory "{folder}"'}

    raise RuntimeError("Could not detect how to run this project. Set START_CMD in .env "
                       "(or use --start-cmd), e.g.  --start-cmd \"npm run dev -- --port {port}\"")


def _start_server(cmd: str, cwd: Path, port: int, log_file: Path) -> subprocess.Popen:
    from ..safety import clean_env
    env = clean_env(os.environ.copy())  # the started app never sees your API keys, tokens or the test password
    env.update({"PORT": str(port), "BROWSER": "none", "CI": "true", "HOST": "127.0.0.1"})
    log = log_file.open("a", encoding="utf-8", errors="replace")
    log.write(f"\n$ {cmd}\n")
    log.flush()
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if IS_WINDOWS else {"start_new_session": True}
    print(f"  [setup] starting: {cmd}")
    # (a shell: the detected or given start command, e.g. `npm run dev -- --port 3000`)
    proc = subprocess.Popen(cmd, cwd=cwd, shell=True, env=env, stdout=log,  # noqa: S602
                            stderr=subprocess.STDOUT, **kwargs)
    _running.append(proc)
    return proc


def _wait_until_up(proc: subprocess.Popen, port: int, log_file: Path) -> str:
    """Wait until the website answers. Returns its URL."""
    deadline = time.time() + settings.server_start_timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            tail = log_file.read_text(encoding="utf-8", errors="replace")[-1500:]
            raise RuntimeError(f"The app stopped while starting (exit {proc.returncode}). Last output:\n{tail}")
        text = ANSI.sub("", log_file.read_text(encoding="utf-8", errors="replace"))
        candidates = [f"http://localhost:{port}"] + [f"http://localhost:{p}" for p in URL_IN_OUTPUT.findall(text)]
        for url in dict.fromkeys(candidates):
            try:
                requests.get(url, timeout=2)
                return url
            except requests.RequestException:
                pass
        time.sleep(1.5)
    raise RuntimeError(f"The app did not start within {settings.server_start_timeout}s. See {log_file}")


def stop_servers() -> None:
    """Stop every app we started (called at the end, even if the run crashes)."""
    stopped = 0
    while _running:
        proc = _running.pop()
        if proc.poll() is not None:
            continue
        stopped += 1
        try:
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    if stopped:
        print("  [setup] stopped the app server")


# ------------------------------------------------------------------ agent

def setup_agent(state: QAState) -> QAState:
    source = state["source"]
    if not (is_github(source) or is_local_project(source)):
        return {"log": state.get("log", []) + [f"Setup: testing website URL {state['url']}."]}

    run_dir = Path(state["run_dir"])
    log_file = run_dir / "setup.log"
    try:
        root = _clone(source, log_file) if is_github(source) else Path(source).expanduser().resolve()
        port = settings.app_port or _free_port()
        info = detect_project(root, port)
        print(f"  [setup] project: {root}  type: {info['type']}")
        for cmd in info["install"]:
            _run(cmd, root, log_file)
        proc = _start_server(info["start"], root, port, log_file)
        url = _wait_until_up(proc, port, log_file)
        print(f"  [setup] app is running at {url}")
        project = {"path": str(root), "type": info["type"], "install": info["install"],
                   "start": info["start"], "url": url}
        msg = f"Setup: {info['type']} project from {source} is running at {url}."
        return {"url": url, "project": project, "log": state.get("log", []) + [msg]}
    except Exception as e:
        stop_servers()
        print(f"  [setup] FAILED: {e}")
        return {"setup_error": str(e), "log": state.get("log", []) + [f"Setup FAILED: {str(e)[:300]}"]}
