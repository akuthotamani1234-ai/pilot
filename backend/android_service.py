"""Start an installed local Appium server only after an explicit test request."""
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from .android import AndroidEnvironmentError, _appium_path, _java_path, _local_appium_url, _sdk_path

ROOT = Path(__file__).resolve().parent.parent
APPIUM_STARTUP_ERRORS = ("Appium server is not running", "Appium answered at")
_startup_lock = threading.Lock()
_launches = {}


def _ready(url: str) -> bool:
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(url + "/status", timeout=(0.5, 2))
            response.raise_for_status()
            return response.json().get("value", {}).get("ready") is True
    except (requests.RequestException, ValueError, AttributeError):
        return False


def _listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _command(program: str) -> list[str]:
    if os.name != "nt" or not program.lower().endswith((".cmd", ".bat")):
        return [program]
    # Run npm's entrypoint directly: no shell quoting and no visible cmd window.
    shim = Path(program)
    node = shim.parent / "node.exe"
    node = str(node) if node.is_file() else shutil.which("node")
    for entrypoint in (shim.parent / "node_modules/appium/build/lib/main.js",
                       shim.parent.parent / "appium/build/lib/main.js"):
        if node and entrypoint.is_file():
            return [node, str(entrypoint)]
    raise AndroidEnvironmentError(
        "Could not locate Appium's Node.js entrypoint. Repair the Appium installation or start Appium manually."
    )


def ensure_appium_ready(server_url: str, timeout_s: int = 60) -> dict:
    """Reuse a healthy server; serialize startup and retain a slow launch for retries."""
    url = _local_appium_url(server_url)
    parsed = urlparse(url)
    host = "127.0.0.1" if parsed.hostname == "localhost" else parsed.hostname
    port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
    if port == 0:
        raise AndroidEnvironmentError("Enter an Appium server port between 1 and 65535.")
    key = (host, port)
    with _startup_lock:
        if _ready(url):
            return {"url": url, "started": False}
        if parsed.scheme != "http":
            raise AndroidEnvironmentError(
                "Automatic Appium startup uses HTTP on this computer. Use http://127.0.0.1:4723 or start your HTTPS server manually."
            )
        started = False
        process = _launches.get(key)
        if process and process.poll() is not None:
            process = None
        if not process and not _listening(host, port):
            program = _appium_path()
            if not program:
                raise AndroidEnvironmentError("Appium is not installed. Install Appium before starting an Android test.")
            folder = ROOT / "logs" / "android"
            folder.mkdir(parents=True, exist_ok=True)
            command = [*_command(program), "--address", host, "--port", str(port),
                       "--base-path", parsed.path or "/", "--log-level", "warn"]
            env = dict(os.environ)
            sdk, java = _sdk_path(), _java_path()
            if sdk:
                env.update(ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk))
            if java:
                env["JAVA_HOME"] = str(Path(java).resolve().parent.parent)
            options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
            try:
                with (folder / f"appium-{port}.log").open("ab") as log:
                    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                               stderr=subprocess.STDOUT, env=env, **options)
            except OSError as error:
                raise AndroidEnvironmentError("Could not launch Appium. Check the installed Node.js and Appium commands.") from error
            _launches[key] = process
            started = True
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if _ready(url):
                return {"url": url, "started": started}
            if process and process.poll() is not None:
                raise AndroidEnvironmentError(f"Appium exited during startup. See logs/android/appium-{port}.log.")
            time.sleep(0.5)
        raise AndroidEnvironmentError(
            f"Appium did not become ready at {url} within {timeout_s} seconds. "
            f"Check whether another program is using port {port} and see logs/android/appium-{port}.log, then retry."
        )
