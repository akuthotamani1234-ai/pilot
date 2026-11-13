"""Android/Appium environment, APK validation and UI hierarchy helpers."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import requests
from defusedxml import ElementTree

DEFAULT_APPIUM_URL = "http://127.0.0.1:4723"
ANDROID_EXECUTION_REVISION = 2
MAX_APK_BYTES = 500 * 1024 * 1024
PACKAGE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")
RISKY_ACTION = re.compile(
    r"\b(pay|purchase|buy|checkout|delete|remove|transfer|send|submit|save|create|update|confirm|"
    r"place order|change password|log ?out|sign ?out|sign ?in|log ?in|sign ?up|register|unsubscribe|deactivate|"
    r"accept|allow|share|invite|post|publish|upload|install|grant|erase|reset|wipe|add|increase|decrease|clear|register|book|order|subscribe|"
    r"toggle|favorite|favourite|bookmark|pin|star|permission|camera|photo|gallery|microphone|location|contact|scanner|"
    r"crash|force close)\b",
    re.I,
)


def repeat_family(element: dict):
    """Unlabelled look-alike controls on one screen (rating stars start1..start5, the same icon in every card):
    trying one of them shows what they do; tapping all of them only spends the exploration time."""
    if element.get("navigation_role") or element.get("text") or element.get("accessibility_id"):
        return None  # labelled controls and tabs/menu items each lead somewhere of their own
    resource = re.sub(r"\d+", "#", (element.get("resource_id") or "").rsplit("/", 1)[-1])
    return (element.get("class_name"), resource) if resource else None
# Android's runtime ("dangerous") permissions: the ones a user grants in a prompt, and the only ones `pm grant` can give.
RUNTIME_PERMISSIONS = {
    "CAMERA", "RECORD_AUDIO", "ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION", "ACCESS_BACKGROUND_LOCATION",
    "ACCESS_MEDIA_LOCATION", "POST_NOTIFICATIONS", "READ_MEDIA_IMAGES", "READ_MEDIA_VIDEO", "READ_MEDIA_AUDIO",
    "READ_MEDIA_VISUAL_USER_SELECTED", "READ_EXTERNAL_STORAGE", "WRITE_EXTERNAL_STORAGE", "READ_CONTACTS",
    "WRITE_CONTACTS", "GET_ACCOUNTS", "READ_CALENDAR", "WRITE_CALENDAR", "READ_PHONE_STATE", "READ_PHONE_NUMBERS",
    "CALL_PHONE", "READ_CALL_LOG", "WRITE_CALL_LOG", "SEND_SMS", "RECEIVE_SMS", "READ_SMS", "BODY_SENSORS",
    "ACTIVITY_RECOGNITION", "BLUETOOTH_CONNECT", "BLUETOOTH_SCAN", "BLUETOOTH_ADVERTISE", "NEARBY_WIFI_DEVICES",
}
SAFE_NAVIGATION = re.compile(
    r"\b(home|dashboard|menu|tab|back|close|about|settings|profile|search|navigation|"
    r"expand|collapse|drawer|products?|details?|cart|catalog|help|"
    r"registration|validation|broken)\b",
    re.I,
)


class AndroidEnvironmentError(RuntimeError):
    """A missing or invalid Android/Appium prerequisite, with a user-facing explanation."""


def _local_appium_url(server_url: str) -> str:
    parsed = urlparse(server_url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise AndroidEnvironmentError("For safety, Appium must be reachable only on this computer.")
    if parsed.username or parsed.password:
        raise AndroidEnvironmentError("Do not put credentials in the Appium server URL.")
    if parsed.query or parsed.fragment:
        raise AndroidEnvironmentError("The Appium URL cannot include a query or fragment.")
    try:
        _ = parsed.port
    except ValueError as e:
        raise AndroidEnvironmentError("Enter a valid Appium server port.") from e
    return server_url.rstrip("/")


def _adb_path() -> str | None:
    found = shutil.which("adb")
    if found:
        return found
    sdk = _sdk_path()
    if sdk:
        candidate = Path(sdk) / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
        if candidate.is_file():
            return str(candidate)
    return None


def _sdk_path() -> str | None:
    sdk = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    if sdk and Path(sdk).is_dir():
        return sdk
    local = os.environ.get("LOCALAPPDATA")
    candidate = Path(local) / "Android" / "Sdk" if local else None
    return str(candidate) if candidate and candidate.is_dir() else sdk


def _appium_path() -> str | None:
    found = shutil.which("appium")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    candidate = (
        Path(local)
        / "BlowAI"
        / "AndroidTools"
        / "node_modules"
        / ".bin"
        / ("appium.cmd" if os.name == "nt" else "appium")
        if local
        else None
    )
    return str(candidate) if candidate and candidate.is_file() else None


def _java_path() -> str | None:
    home = os.environ.get("JAVA_HOME")
    candidate = Path(home) / "bin" / ("java.exe" if os.name == "nt" else "java") if home else None
    if candidate and candidate.is_file():
        return str(candidate)
    found = shutil.which("java")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    candidate = (
        Path(local) / "BlowAI" / "jdk-21" / "bin" / ("java.exe" if os.name == "nt" else "java") if local else None
    )
    return str(candidate) if candidate and candidate.is_file() else None


def _run_cli(program: str, args: list[str], timeout: int) -> subprocess.CompletedProcess:
    command = [program, *args]
    if os.name == "nt" and program.lower().endswith((".cmd", ".bat")):
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", subprocess.list2cmdline(command)]
    return subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False
    )


def parse_devices(output: str) -> list[dict]:
    """Parse `adb devices -l` rows without depending on localized descriptions."""
    devices = []
    for line in output.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 2:
            continue
        devices.append({"device_id": fields[0], "status": fields[1], "details": " ".join(fields[2:])[:300]})
    return devices


def _uiautomator_installation() -> str | None:
    """Confirm the registered package and entrypoint without starting another Node CLI."""
    home = Path(os.environ.get("APPIUM_HOME") or Path.home() / ".appium")
    package = home / "node_modules" / "appium-uiautomator2-driver"
    manifest = home / "node_modules" / ".cache" / "appium" / "extensions.yaml"
    try:
        if manifest.stat().st_size > 262144:
            return None
        drivers = manifest.read_text(encoding="utf-8").split("\nplugins:", 1)[0]
        if not re.search(r"(?m)^  uiautomator2:\s*$", drivers):
            return None
        if not re.search(r"(?m)^    pkgName: appium-uiautomator2-driver\s*$", drivers):
            return None
        metadata = json.loads((package / "package.json").read_text(encoding="utf-8"))
        if metadata.get("name") != "appium-uiautomator2-driver" or metadata.get("appium", {}).get("driverName") != "uiautomator2":
            return None
        entrypoint = (package / metadata["main"]).resolve()
        entrypoint.relative_to(package.resolve())
        if entrypoint.is_file():
            return f"UiAutomator2 {metadata['version']} registered package and entrypoint verified in Appium home."
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


# Soft environment errors: the setup UI may still offer "start emulator" when these are the only failures.
DEVICE_ABSENCE_ERRORS = (
    "No Android device is connected.",
    "No authorized Android device is ready",
)


def android_environment(server_url: str = DEFAULT_APPIUM_URL) -> dict:
    """Return prerequisite status; missing components are explicit, not treated as success."""
    url = _local_appium_url(server_url)
    sdk = _sdk_path()
    adb = _adb_path()
    appium = _appium_path()
    java = _java_path()
    errors = []
    if not sdk or not Path(sdk).is_dir():
        errors.append(
            "Android SDK not found. Set ANDROID_HOME or ANDROID_SDK_ROOT to the SDK root "
            "(the folder that contains platform-tools/), then restart the UI."
        )
    if not adb:
        errors.append(
            "ADB not found. Install Android SDK Platform-Tools, ensure platform-tools is on PATH "
            "(or under ANDROID_HOME), then restart the UI."
        )
    if not java:
        errors.append(
            "Java not found. Install JDK 17 or newer, set JAVA_HOME to that JDK, and ensure java is on PATH."
        )
    elif java:
        try:
            result = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=10, check=False)
            version_text = result.stdout + result.stderr
            match = re.search(r'version "?(?:1\.)?(\d+)', version_text)
            if result.returncode or (match and int(match.group(1)) < 17):
                errors.append(
                    "Appium requires JDK 17 or newer. Check JAVA_HOME points at JDK 17+ "
                    f"(current probe: {java})."
                )
            elif not match:
                errors.append(
                    "Could not read the Java version string. Check JAVA_HOME points at a JDK 17+ installation."
                )
        except (OSError, subprocess.TimeoutExpired) as e:
            errors.append(f"Could not check the Java version ({java}): {e}")

    devices = []
    if adb:
        try:
            result = _run_cli(adb, ["devices", "-l"], timeout=10)
        except (OSError, subprocess.TimeoutExpired) as e:
            errors.append(
                f"Could not query Android devices via ADB ({adb}): {e}. "
                "Confirm the Android SDK Platform-Tools install and retry."
            )
        else:
            if result.returncode:
                detail = (result.stderr or result.stdout or "").strip()[:300] or f"exit code {result.returncode}"
                errors.append(f"ADB device query failed ({adb}): {detail}")
            else:
                devices = parse_devices(result.stdout)

    server = {"available": False, "url": url}
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(f"{url}/status", timeout=(0.5, 2))
            response.raise_for_status()
            payload = response.json()
        server["available"] = payload.get("value", {}).get("ready") is True
        if not server["available"]:
            errors.append(
                f"Appium answered at {url} but is not ready to create a session. "
                "Wait for the server to finish starting, or restart Appium."
            )
        server["message"] = payload.get("value", {}).get("message", "")
    except (requests.RequestException, ValueError) as e:
        server["error"] = str(e).splitlines()[0][:200]
        errors.append(
            f"Appium server is not running at {url}. Start it with "
            "`appium --address 127.0.0.1 --port 4723`, then refresh environment status."
        )

    driver_installed = False
    driver_output = ""
    driver_probe_failed = False
    if appium:
        installed = _uiautomator_installation()
        if installed:
            driver_installed, driver_output = True, installed
        else:
            try:
                result = _run_cli(appium, ["driver", "list", "--installed"], timeout=20)
                driver_output = (result.stdout + result.stderr)[:2000]
                driver_installed = result.returncode == 0 and bool(re.search(r"\buiautomator2\b", driver_output, re.I))
                driver_probe_failed = result.returncode != 0
            except (OSError, subprocess.TimeoutExpired) as e:
                driver_output = str(e)[:300]
                driver_probe_failed = True
    else:
        errors.append(
            "Appium CLI not found. Install Node.js, then install Appium 2/3 with "
            "`npm install -g appium`, and ensure the appium command is on PATH."
        )
    if appium and not driver_installed:
        appium_home = os.environ.get("APPIUM_HOME") or str(Path.home() / ".appium")
        if driver_probe_failed:
            errors.append(
                "Could not verify UiAutomator2 installation. "
                f"Check APPIUM_HOME ({appium_home}), then run `appium driver list --installed`."
            )
        else:
            errors.append(
                "UiAutomator2 driver is not installed. "
                f"With APPIUM_HOME={appium_home}, run `appium driver install uiautomator2`."
            )
    if adb:
        ready = [d for d in devices if d.get("status") == "device"]
        if not ready:
            if devices:
                seen = ", ".join(f"{d['device_id']} ({d['status']})" for d in devices[:8])
                errors.append(
                    "No authorized Android device is ready for testing. "
                    f"Seen: {seen}. Unlock the device, accept the USB debugging prompt, "
                    "or wait for the emulator home screen, then run `adb devices`."
                )
            else:
                errors.append(
                    "No Android device is connected. Start an emulator or enable USB debugging, "
                    "then run `adb devices`."
                )

    return {
        "ok": not errors,
        "appium": server,
        "appium_cli": bool(appium),
        "java": java,
        "uiautomator2": driver_installed,
        "android_sdk": str(sdk) if sdk and Path(sdk).is_dir() else None,
        "adb": adb,
        "devices": devices,
        "errors": errors,
        "driver_output": driver_output,
    }


def require_device(device_id: str, devices: list[dict]) -> None:
    selected = next((d for d in devices if d["device_id"] == device_id), None)
    if selected is None:
        raise AndroidEnvironmentError(
            f"Android device '{device_id}' is not connected. Refresh with `adb devices`, "
            "or select an installed emulator to start automatically."
        )
    status = selected["status"]
    if status == "device":
        return
    if status == "unauthorized":
        raise AndroidEnvironmentError(
            f"Android device '{device_id}' is unauthorized. Unlock it, accept the USB debugging prompt, "
            "then run `adb devices` and retry."
        )
    if status == "offline":
        raise AndroidEnvironmentError(
            f"Android device '{device_id}' is offline. Wait for the emulator to finish booting "
            "or reconnect the phone, then retry."
        )
    raise AndroidEnvironmentError(
        f"Android device '{device_id}' is {status}; reconnect or authorize it before testing."
    )


def validate_apk(path: Path) -> Path:
    """Validate an APK from controlled storage, including archive structure and size."""
    path = path.resolve()
    if path.suffix.lower() != ".apk":
        raise AndroidEnvironmentError("Upload an Android .apk file (filename must end with .apk).")
    if not path.is_file():
        raise AndroidEnvironmentError(
            f"The uploaded APK could not be found at {path}. Re-upload the file and retry."
        )
    size = path.stat().st_size
    if not size:
        raise AndroidEnvironmentError("The uploaded APK is empty (0 bytes). Choose a real Android package file.")
    if size > MAX_APK_BYTES:
        raise AndroidEnvironmentError(f"APK must be between 1 byte and {MAX_APK_BYTES // (1024 * 1024)} MB.")
    try:
        with zipfile.ZipFile(path) as apk:
            names = apk.namelist()
            if len(names) > 100000 or sum(item.file_size for item in apk.infolist()) > 2 * 1024 * 1024 * 1024:
                raise AndroidEnvironmentError("The APK archive exceeds safe content limits.")
            if "AndroidManifest.xml" not in names:
                raise AndroidEnvironmentError("This ZIP file is not a valid Android APK (manifest missing).")
            if not any(name == "classes.dex" or re.fullmatch(r"classes\d+\.dex", name) for name in names):
                raise AndroidEnvironmentError(
                    "This ZIP file is not a valid Android APK (DEX bytecode missing). "
                    "Upload a complete app package, not a stripped or corrupted archive."
                )
            if any(
                name.startswith(("/", "\\"))
                or re.match(r"^[A-Za-z]:", name)
                or ".." in name.replace("\\", "/").split("/")
                for name in names
            ):
                raise AndroidEnvironmentError("The APK contains an unsafe archive path.")
    except zipfile.BadZipFile as e:
        raise AndroidEnvironmentError(
            "The uploaded file is not a valid APK archive (it must be a ZIP-based Android package)."
        ) from e
    return path


def validate_mobile_config(config: dict) -> dict:
    if not isinstance(config, dict):
        raise AndroidEnvironmentError('Android configuration must be an object')
    if {'api_key', 'test_username', 'test_password', 'private_inputs'} & config.keys():
        raise AndroidEnvironmentError('Keep private inputs in the per-run UI fields or environment references, not Android configuration files')
    mode = config.get("app_mode")
    if mode not in ("apk", "installed", "web"):
        raise AndroidEnvironmentError("Choose APK upload, an installed app or Android Chrome.")
    package = (config.get("package_name") or "").strip()
    start_url = (config.get("start_url") or "").strip()
    if mode == "web":
        from .safety import check_target, search_redirect, unwrap_link
        # A link copied from Bing/Google results only redirects to the site. Testing it would start on the
        # search engine and stop as soon as Chrome reached the real website (a different origin).
        start_url = unwrap_link(start_url)
        if search_redirect(start_url):
            raise AndroidEnvironmentError(
                "This is a search-engine link, not the website's address. Open the website, "
                "then copy the address shown in the browser's address bar.")
        try:
            check_target(start_url)
        except ValueError as e:
            raise AndroidEnvironmentError("Enter a valid authorized website URL: " + str(e)) from e
        if config.get("apk_path") or package not in ("", "com.android.chrome") or config.get("app_activity"):
            raise AndroidEnvironmentError("Android Chrome accepts a website URL, not APK/package/activity settings.")
        package = "com.android.chrome"
    if mode == "installed" and not PACKAGE_NAME.fullmatch(package):
        raise AndroidEnvironmentError("Enter a valid Android package name, for example com.example.myapp.")
    # APK upload mode: the server requires the UploadFile and validate_apk checks the saved path after write.
    # Do not require apk_path here — start_mobile_run validates config before the upload is stored.
    if mode == "apk" and package and not PACKAGE_NAME.fullmatch(package):
        raise AndroidEnvironmentError(
            "The APK package name is invalid. Leave it blank for upload mode, or use a name like com.example.myapp."
        )
    activity = (config.get("app_activity") or "").strip()
    if activity and not re.fullmatch(r"[A-Za-z0-9_.$]+", activity):
        raise AndroidEnvironmentError("The Android activity name contains unsupported characters.")
    device_id = (config.get("device_id") or "").strip()
    if not device_id or len(device_id) > 200 or any(c in device_id for c in "\r\n"):
        raise AndroidEnvironmentError("Select a connected Android device.")
    server_url = _local_appium_url(config.get("appium_url") or DEFAULT_APPIUM_URL)
    try:
        max_screens = int(config.get("max_screens", 40))
        max_actions = int(config.get("max_actions", 60))
    except (TypeError, ValueError) as e:
        raise AndroidEnvironmentError("Exploration limits must be whole numbers.") from e
    if not 1 <= max_screens <= 100 or not 0 <= max_actions <= 200:
        raise AndroidEnvironmentError("Exploration limits must be 1-100 screens and 0-200 actions.")
    limits = {}
    for key, default, low, high in (
        ("max_depth", 5, 0, 10),
        ("discovery_timeout_s", 600, 10, 900),
        ("command_timeout_s", 60, 10, 120),
        ("session_timeout_s", 300, 60, 300),
        ("max_test_cases", 300, 1, 300),
        ("max_scroll_actions", 30, 0, 100),
        ("max_scrolls_per_screen", 4, 0, 12),
        # Native discovery: controls explored per screen (menu items and tabs first); the rest are listed
        ("max_candidates_per_screen", 12, 1, 100),
        # User-like testing of a test build or test website: tries (probe + replay each count) and its own time
        # budget. The defaults cover a demo shop such as nopCommerce (about 10 menu entries, 20 footer links and the
        # shop's features); the maximums keep every run finite so it always ends with a report.
        ("max_interactions", 300, 0, 500),
        ("interaction_timeout_s", 2700, 30, 3600),
        # A website's bot check: how long to wait for it to finish by itself, then for a person to complete it
        ("bot_check_wait_s", 30, 0, 120),
        ("human_wait_s", 180, 0, 900),
    ):
        try:
            value = int(config.get(key, default))
        except (TypeError, ValueError) as e:
            raise AndroidEnvironmentError(f"{key} must be a whole number.") from e
        if not low <= value <= high:
            raise AndroidEnvironmentError(f"{key} must be between {low} and {high}.")
        limits[key] = value
    expectations = config.get("expected_destinations") or {}
    if isinstance(expectations, str):
        entries = [line.split("=", 1) for line in expectations.splitlines() if line.strip()]
        if any(len(entry) != 2 for entry in entries):
            raise AndroidEnvironmentError("Use one navigation expectation per line: control = screen title.")
        expectations = dict(entries)
    if not isinstance(expectations, dict) or len(expectations) > 100:
        raise AndroidEnvironmentError("Provide at most 100 navigation expectations.")
    if any(
        not isinstance(k, str)
        or not isinstance(v, str)
        or not k.strip()
        or not v.strip()
        or len(k) > 160
        or len(v) > 160
        for k, v in expectations.items()
    ):
        raise AndroidEnvironmentError("Navigation expectations must contain nonempty control and screen titles.")
    expectations = {k.strip().casefold(): v.strip() for k, v in expectations.items()}
    if len(str(config.get("requirements") or "")) > 12000:
        raise AndroidEnvironmentError("Requirements must be no longer than 12000 characters.")
    expected_values = config.get("expected_values") or {}
    if isinstance(expected_values, str):
        entries = [line.split("=", 1) for line in expected_values.splitlines() if line.strip()]
        if any(len(entry) != 2 for entry in entries):
            raise AndroidEnvironmentError(
                "Use one displayed-value expectation per line: accessibility label = expected text."
            )
        expected_values = dict(entries)
    if (
        not isinstance(expected_values, dict)
        or len(expected_values) > 100
        or any(
            not isinstance(k, str) or not isinstance(v, str) or not k.strip() or len(k) > 160 or len(v) > 300
            for k, v in expected_values.items()
        )
    ):
        raise AndroidEnvironmentError("Expected displayed values must contain at most 100 short label/text pairs.")
    expected_values = {k.strip().casefold(): v.strip() for k, v in expected_values.items()}
    from .qa_contracts import parse_contract

    try:
        contract = parse_contract(config.get("qa_contract")).model_dump(mode="json")
    except ValueError as e:
        raise AndroidEnvironmentError("Invalid QA contract: " + str(e)[:500]) from e
    if contract.get('android_package') and (mode == 'web' or package and contract['android_package'] != package):
        raise AndroidEnvironmentError('The configured flows target a different native Android app')
    if (contract.get('test_environment') and any(flow.get('approved') and any(step.get('permission') for step in flow['steps'])
                                               for flow in contract['flows']) and not re.fullmatch(r'emulator-\d+', device_id)):
        raise AndroidEnvironmentError('Approved Android permission flows require a selected emulator, not a physical phone')
    if not isinstance(config.get("contract_only", False), bool):
        raise AndroidEnvironmentError("Contract-only mode must be true or false.")
    if not isinstance(config.get("interaction_testing", False), bool):
        raise AndroidEnvironmentError("Test-build mode must be true or false.")
    if contract.get("test_mode") and not config.get("interaction_testing"):
        # Flows recorded in test mode may press undoable shop actions; they run only when this run is confirmed too.
        raise AndroidEnvironmentError("These flows were recorded in test mode. Tick the test-mode box to run them.")
    if config.get("contract_only") and not any(contract[k] for k in ("flows", "rules", "checks")):
        raise AndroidEnvironmentError("Contract-only mode needs at least one configured check.")
    return {
        **config,
        "qa_contract": contract,
        **limits,
        "expected_values": expected_values,
        "expected_destinations": expectations,
        "app_mode": mode,
        "start_url": start_url,
        "package_name": package,
        "app_activity": activity,
        "device_id": device_id,
        "appium_url": server_url,
        "max_screens": max_screens,
        "max_actions": max_actions,
        "verify_observed_navigation": bool(config.get("verify_observed_navigation", True)),
    }


def _managed_web_chromedriver(config: dict) -> str | None:
    """Reuse an installed managed driver only when its major matches device Chrome."""
    root = Path(__file__).resolve().parent.parent
    candidates = [root / "tools" / "chromedriver" / "chromedriver.exe",
                  root / "runs" / "android_verification_tools" / "chromedriver.exe"]
    adb = _adb_path()
    if not adb or not any(p.is_file() for p in candidates):
        return None
    try:
        installed = _run_cli(adb, ["-s", config["device_id"], "shell", "dumpsys", "package", "com.android.chrome"], 10)
        chrome = re.search(r"versionName=(\d+)\.", installed.stdout)
        for candidate in candidates:
            if not candidate.is_file():
                continue
            version = _run_cli(str(candidate), ["--version"], 5)
            driver = re.search(r"ChromeDriver (\d+)\.", version.stdout)
            if chrome and driver and chrome[1] == driver[1] and version.returncode == 0:
                return str(candidate.resolve())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def build_capabilities(config: dict) -> dict:
    config = validate_mobile_config(config)
    caps = {
        "platformName": "Android",
        "appium:automationName": "UiAutomator2",
        "appium:udid": config["device_id"],
        "appium:newCommandTimeout": 120,
        "appium:uiautomator2ServerLaunchTimeout": 90000,
        "appium:uiautomator2ServerInstallTimeout": 60000,
        "appium:adbExecTimeout": 60000,
        "appium:autoGrantPermissions": False,
        "appium:settings[disableIdLocatorAutocompletion]": True,
        "appium:settings[enableMultiWindows]": True,
    }
    if os.environ.get("BLOWAI_CHROMEDRIVER"):
        caps["appium:chromedriverExecutable"] = str(Path(os.environ["BLOWAI_CHROMEDRIVER"]).resolve(strict=True))
    if config["app_mode"] == "web":
        caps["browserName"] = "Chrome"
        if "appium:chromedriverExecutable" not in caps:
            managed = _managed_web_chromedriver(config)
            if managed:
                caps["appium:chromedriverExecutable"] = managed
        caps["appium:noReset"] = True
        caps["appium:chromeOptions"] = {"args": ["--no-first-run", "--no-default-browser-check", "--disable-fre"]}
        return caps
    if config["app_mode"] == "apk":
        caps["appium:app"] = str(validate_apk(Path(config["apk_path"])))
    else:
        caps["appium:appPackage"] = config["package_name"]
        caps["appium:noReset"] = True
        caps["appium:forceAppLaunch"] = True
    if config["app_activity"]:
        caps["appium:appActivity"] = config["app_activity"]
    # The launcher can be a short-lived splash activity. Accept a handoff only
    # within this app; inspect_driver still verifies the foreground package.
    caps["appium:appWaitActivity"] = "*"
    caps["appium:appWaitDuration"] = 60000
    if config.get("package_name"):
        caps["appium:appWaitPackage"] = config["package_name"]
    return caps


class DeviceLock:
    """OS-held lock: it is automatically released even if the controlling process dies."""

    def __init__(self, device_id: str):
        key = hashlib.sha256(device_id.encode()).hexdigest()
        self.path = Path(tempfile.gettempdir()) / "blowai-device-locks" / (key + ".lock")
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(exist_ok=True)
        self.stream = self.path.open("a+b")
        try:
            self.stream.seek(0, 2)
            if not self.stream.tell():
                self.stream.write(b"0")
                self.stream.flush()
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            self.stream.close()
            self.stream = None
            raise AndroidEnvironmentError(
                "The selected Android device is already controlled by another session."
            ) from e
        return self

    def __exit__(self, *_args):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


class _LockedDriver:
    def __init__(self, driver, device_lock):
        self.driver = driver
        self.device_lock = device_lock

    def __getattr__(self, name):
        return getattr(self.driver, name)

    def quit(self):
        try:
            self.driver.quit()
        finally:
            self.device_lock.__exit__()


def _normalize_resolved_activity(package: str, component_line: str) -> str | None:
    """Turn `com.app/.Splash` or `com.app/com.app.Splash` into an Appium appActivity value."""
    if "/" not in component_line:
        return None
    activity = component_line.split("/", 1)[1].strip()
    if not activity:
        return None
    if activity.startswith("."):
        return activity
    if activity.startswith(package):
        return activity
    return activity


def launchable_activity(device_id: str, package: str) -> str | None:
    """Resolve the LAUNCHER activity for an installed package (SplashActivity, not a non-exported MainActivity)."""
    if not device_id or not PACKAGE_NAME.fullmatch(package or ""):
        return None
    adb = shutil.which("adb")
    if not adb:
        return None
    try:
        completed = subprocess.run(
            [adb, "-s", device_id, "shell", "cmd", "package", "resolve-activity", "--brief",
             "-c", "android.intent.category.LAUNCHER", package],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in (completed.stdout or "").splitlines():
        line = line.strip()
        if package in line and "/" in line:
            return _normalize_resolved_activity(package, line)
    return None


def create_session(config: dict):
    """One bounded UiAutomator2 session; all callers share the same device lock."""
    original = config
    config = validate_mobile_config(config)
    try:
        from appium import webdriver
        from appium.options.android import UiAutomator2Options
        from appium.webdriver.appium_connection import AppiumConnection
        from appium.webdriver.client_config import AppiumClientConfig
    except ImportError as e:
        raise AndroidEnvironmentError("Appium Python Client is missing. Install requirements.txt.") from e

    def _connect(cfg):
        options = UiAutomator2Options().load_capabilities(build_capabilities(cfg))
        # Chrome/UiAutomator startup can exceed an ordinary element-command timeout.
        client = AppiumClientConfig(remote_server_addr=cfg["appium_url"], timeout=cfg["session_timeout_s"])
        # AppiumConnection owns a separate class-level header dictionary, which
        # can shadow Selenium ClientConfig.extra_headers. Use an isolated class
        # so every request carries masking intent without changing other clients.
        class SensitiveConnection(AppiumConnection):
            extra_headers = {"X-Appium-Is-Sensitive": "1"}

        connection = SensitiveConnection(client_config=client)
        driver = webdriver.Remote(connection, options=options, client_config=client)
        client.timeout = cfg["command_timeout_s"]
        if cfg["app_mode"] == "web":
            try:
                driver.set_page_load_timeout(45)
                driver.get(cfg["start_url"])
            except BaseException:
                close_session(driver)
                raise
        return driver

    device_lock = DeviceLock(config["device_id"])
    device_lock.__enter__()
    try:
        try:
            driver = _connect(config)
        except BaseException as first:
            # MainActivity is often not exported; retry with the real LAUNCHER activity (SplashActivity).
            detail = str(first)
            if (
                config.get("app_mode") in ("installed", "apk")
                and config.get("package_name")
                and ("not exported" in detail or "Permission Denial" in detail)
            ):
                launcher = launchable_activity(config["device_id"], config["package_name"])
                current = (config.get("app_activity") or "").strip()
                aliases = {current, current.lstrip(".")}
                if current.startswith("."):
                    aliases.add(config["package_name"] + current)
                if launcher and launcher not in aliases:
                    retry = dict(config)
                    retry["app_activity"] = launcher
                    driver = _connect(retry)
                    # Persist onto both the validated config and the caller dict used by discovery/pytest.
                    config["app_activity"] = launcher
                    original["app_activity"] = launcher
                else:
                    raise
            else:
                raise
        return _LockedDriver(driver, device_lock)
    except BaseException as e:
        device_lock.__exit__()
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        from .safety import redact

        hint = ""
        if "not exported" in str(e) or "Permission Denial" in str(e):
            hint = (
                " The configured activity is not exported; use the LAUNCHER/splash activity "
                "(leave activity blank or pick the app's launchable activity)."
            )
        raise AndroidEnvironmentError(
            f"Could not create an Appium session or launch the app: {redact(str(e))[:300]}{hint}"
        ) from e


def _driver_context(driver) -> str:
    """Appium context name; missing context is treated as native UI."""
    context = getattr(driver, "current_context", None)
    return context if isinstance(context, str) and context else "NATIVE_APP"


def native_ui_context(driver) -> bool:
    """True when CSS selectors must not be used (native UiAutomator hierarchy)."""
    context = _driver_context(driver)
    return context == "NATIVE_APP" or context.startswith("NATIVE")


def find_unique(driver, locator: dict):
    """A locator must select exactly one displayed element before it is usable."""
    from appium.webdriver.common.appiumby import AppiumBy

    if not isinstance(locator, dict) or "strategy" not in locator or "value" not in locator:
        raise ValueError("A locator needs strategy and value.")
    strategy = locator["strategy"]
    if strategy == "css" and native_ui_context(driver):
        raise ValueError(
            "CSS selectors belong to WebView or Android Chrome contexts, not native UI. "
            "Use accessibility_id, resource_id, text or xpath, or switch to a WebView context first."
        )
    strategies = {
        "accessibility_id": AppiumBy.ACCESSIBILITY_ID,
        "resource_id": AppiumBy.ID,
        "text": AppiumBy.ANDROID_UIAUTOMATOR,
        "xpath": AppiumBy.XPATH,
        "css": AppiumBy.CSS_SELECTOR,
    }
    if strategy not in strategies:
        raise ValueError(
            f"Unsupported locator strategy '{strategy}'. "
            "Native UI uses accessibility_id, resource_id, text or xpath; CSS is for WebView/Chrome only."
        )
    value = locator["value"]
    if strategy == "text":
        value = f"new UiSelector().text({json.dumps(value)})"
    found = [element for element in driver.find_elements(strategies[strategy], value)
             if element.is_displayed()]
    if len(found) != 1:
        from selenium.common.exceptions import NoSuchElementException

        raise NoSuchElementException(
            f"The discovered {strategy} locator does not select one visible element."
        )
    return found[0]


def interaction_blocker(config: dict) -> str:
    """'' when user-like testing may run for this run, otherwise the plain reason it may not."""
    if not config.get("interaction_testing"):
        return "Test-build mode is off."
    if config.get("app_mode") == "web":
        # The ticked box is the person's confirmation that this is a test or demo website they may test. Each check
        # clears only this website's cookies and storage in Chrome, and stays inside the approved origin.
        return ""
    if config.get("app_mode") == "installed" and not re.fullmatch(r"emulator-\d+", config.get("device_id", "")):
        # Each user-like test starts from cleared app data; never clear an app on someone's real phone.
        return "For an app already installed on a physical phone, user-like testing is off (it resets app data). Use an emulator or upload the APK."
    return ""


def reset_app_data(driver, package: str) -> None:
    """A fresh app, as after installation, so a test that changes data (a cart, a setting) starts from a known
    state. Runtime permissions the app already had are given back, so clearing does not add a permission prompt
    the app never showed before."""
    if not PACKAGE_NAME.fullmatch(package or ""):
        hint = (
            " The package looks corrupted by secret redaction; machine-readable Android artifacts must keep "
            "package identifiers intact."
            if package and "[REDACTED]" in package
            else ""
        )
        raise AndroidEnvironmentError("A valid app package is required before resetting its data." + hint)
    granted = []
    try:
        granted = [p for p in driver.execute_script("mobile: getPermissions", {"appPackage": package, "type": "granted"})
                   if isinstance(p, str) and p.removeprefix("android.permission.") in RUNTIME_PERMISSIONS][:40]
    except Exception:
        granted = []
    driver.execute_script("mobile: clearApp", {"appId": package})
    for permission in granted:  # one by one, so one refused permission does not stop the others
        try:
            driver.execute_script("mobile: changePermissions", {"appPackage": package, "permissions": [permission],
                                                                 "target": "pm", "action": "grant"})
        except Exception:
            pass
    driver.activate_app(package)


def close_session(driver) -> str:
    try:
        driver.quit()
    except Exception as e:
        from .safety import redact

        return "Session cleanup failed: " + redact(str(e))[:300]
    return ""


def capture_screenshot(driver, run_dir: Path, name: str, package_name: str | None = None) -> str | None:
    """Evidence stays inside the run. A failed capture must not mask the original failure."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("Invalid evidence name")
    path = run_dir / "screenshots" / (name + ".png")
    path.parent.mkdir(exist_ok=True)
    try:
        if getattr(driver, "current_context", "NATIVE_APP") != "NATIVE_APP":
            # Like the native rule: a page is left out only while a box holds typed text, not because it has a box
            # (nearly every shop page has an empty search box).
            if driver.execute_script(
                    "const skip = ['hidden','submit','button','reset','image','checkbox','radio','range','color'];"
                    "return [...document.querySelectorAll('input,textarea')].some(e => !skip.includes((e.type || '')"
                    ".toLowerCase()) && e.value) || [...document.querySelectorAll('[contenteditable=true]')]"
                    ".some(e => (e.innerText || '').trim());"):
                return None
            if driver.save_screenshot(str(path)):
                return path.relative_to(run_dir).as_posix()
            return None
        if package_name and driver.current_package != package_name:
            return None
        hierarchy = ElementTree.fromstring(driver.page_source)
        if any(
            node.attrib.get("text")
            and (node.attrib.get("password") == "true" or "edittext" in node.attrib.get("class", "").lower())
            for node in hierarchy.iter()
        ):
            return None
        if driver.save_screenshot(str(path)):
            return path.relative_to(run_dir).as_posix()
    except Exception:
        pass
    return None


def _safe_text(node, kind: str) -> str:
    if kind == "input" or node.attrib.get("password", "false").lower() == "true":
        return ""
    return (node.attrib.get("text") or "")[:160]


def extract_screen(xml: str, package_name: str, device_id: str, activity: str = "") -> dict:
    """Normalize visible Android XML nodes; input contents are intentionally never copied."""
    try:
        root = ElementTree.fromstring(xml)
    except Exception as e:
        raise AndroidEnvironmentError(f"Could not parse Android UI hierarchy: {e}") from e
    elements = []
    element_nodes = []
    parents = {child: parent for parent in root.iter() for child in parent}
    def bounds(node):
        match = re.fullmatch(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", node.attrib.get("bounds", ""))
        return tuple(map(int, match.groups())) if match else None

    # Multi-window hierarchies may list the bottom system bar before the app.
    # Its bottom-right coordinates are large, but it is only a few pixels high.
    frames = [bounds(node) for node in root.iter()
              if node.attrib.get("class", "").endswith(("FrameLayout", "ViewGroup"))
              and node.attrib.get("package", package_name) == package_name
              and bounds(node) and bounds(node)[2] - bounds(node)[0] >= 300
              and bounds(node)[3] - bounds(node)[1] >= 300]
    viewport = max(frames, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]), default=None)

    def rendered(node):
        if node.attrib.get("displayed", node.attrib.get("visible", "true")).lower() != "true":
            return False
        rect = bounds(node)
        clips = [viewport] if viewport else []
        ancestor = parents.get(node)
        while ancestor is not None:
            if ancestor.attrib.get("displayed", ancestor.attrib.get("visible", "true")).lower() != "true":
                return False
            if ancestor.attrib.get("scrollable") == "true" or ancestor.attrib.get("class", "").endswith(("ScrollView", "RecyclerView", "ViewPager", "WebView")):
                clip = bounds(ancestor)
                if clip:
                    clips.append(clip)
            ancestor = parents.get(ancestor)
        if rect is None:
            return True
        left, top, right, bottom = rect
        for clip in clips:
            left, top, right, bottom = max(left, clip[0]), max(top, clip[1]), min(right, clip[2]), min(bottom, clip[3])
        return right > left and bottom > top
    drawer_nodes = set()
    for candidate in root.iter():
        attrs = candidate.attrib
        if (attrs.get("class", "").endswith(("ViewGroup", "NavigationView"))
                and re.search(r"menu[-_ ](?:panel|drawer)|navigation[-_ ]drawer", attrs.get("content-desc", ""), re.I)
                and rendered(candidate)):
            drawer_nodes.update(candidate.iter())
            continue
        if (not attrs.get("class", "").endswith(("RecyclerView", "ListView", "NavigationView"))
                or not re.search(r"\b(menu|navigation)\b", attrs.get("content-desc", ""), re.I)
                or attrs.get("displayed") == "false"):
            continue
        owner = parents.get(candidate)
        while owner is not None and "DrawerLayout" not in owner.attrib.get("class", ""):
            owner = parents.get(owner)
        if owner is not None:
            drawer_nodes.update(candidate.iter())
    # Native tab widgets and React Native bottom bars expose sibling buttons.
    # Require a Home anchor and at least three buttons in the same direct group;
    # a standalone Login/Submit button is never promoted to navigation.
    tab_nodes = set()
    for parent in root.iter():
        buttons = [child for child in parent if child.attrib.get("class") in
                   ("android.widget.Button", "android.widget.TabWidget")]
        if len(buttons) >= 3 and any((child.attrib.get("content-desc") or child.attrib.get("text") or "").casefold() == "home" for child in buttons):
            tab_nodes.update(buttons)
    for node in root.iter():
        attrs = node.attrib
        if attrs.get("package") and attrs["package"] != package_name:
            continue
        class_name = attrs.get("class", "")
        resource_id = attrs.get("resource-id", "")
        description = attrs.get("content-desc", "")
        text = attrs.get("text", "")
        if attrs.get("password", "false").lower() == "true":
            if description == text:
                description = ""
            text = ""
        if not (class_name or resource_id or description or text):
            continue
        lower = class_name.lower()
        kind = (
            "input"
            if any(word in lower for word in ("edittext", "textfield"))
            else "button"
            if "button" in lower or attrs.get("clickable") == "true"
            else "text"
            if "textview" in lower
            else "element"
        )
        visible = rendered(node)
        enabled = attrs.get("enabled", "true").lower() == "true"
        clickable = attrs.get("clickable", "false").lower() == "true"
        locators = []
        if description:
            locators.append({"strategy": "accessibility_id", "value": description})
        if resource_id:
            locators.append({"strategy": "resource_id", "value": resource_id})
        if text and kind != "input" and len(text) <= 160:
            locators.append({"strategy": "text", "value": text})
        if not locators and attrs.get("bounds") and re.fullmatch(r"[A-Za-z0-9_.$]+", class_name):
            locators.append({"strategy": "xpath", "value": f"//*[@class='{class_name}']"})
        ancestor = node
        within_webview = False
        while ancestor is not None:
            if ancestor.attrib.get("class", "").endswith("WebView"):
                within_webview = ancestor is not node
                break
            ancestor = parents.get(ancestor)
        elements.append(
            {
                "type": kind,
                "class_name": class_name,
                "resource_id": resource_id,
                "accessibility_id": description,
                "text": _safe_text(node, kind),
                "visible": visible,
                "enabled": enabled,
                "clickable": clickable,
                "scrollable": attrs.get("scrollable", "false").lower() == "true",
                "checkable": attrs.get("checkable", "false").lower() == "true",
                "checked": attrs.get("checked", "false").lower() == "true",
                "selected": attrs.get("selected", "false").lower() == "true",
                "input_capable": kind == "input",
                # What an input box is for (its hint, never its contents) and whether it hides what is typed.
                "password": attrs.get("password", "false").lower() == "true",
                "hint": (attrs.get("hint") or "")[:100] if kind == "input" else "",
                "navigation_role": "tab" if node in tab_nodes or class_name == "android.app.ActionBar$Tab"
                    else "menu_item" if node in drawer_nodes and clickable and kind != "input" else "",
                "outside_active_drawer": bool(drawer_nodes and node not in drawer_nodes),
                "bounds": attrs.get("bounds"),
                "within_webview": within_webview,
                "text_comparable": kind != "input" and len(text) <= 160 and any(c.isalnum() for c in text),
                "locators": locators,
            }
        )
        element_nodes.append(node)
    locator_counts = Counter((loc["strategy"], loc["value"]) for e in elements if e["visible"] for loc in e["locators"])
    text_counts = Counter(e["text"] for e in elements if e["visible"] and e["type"] == "text" and e["text"])

    def xpath_literal(value):
        if "'" not in value:
            return "'" + value + "'"
        if '"' not in value:
            return '"' + value + '"'
        return "concat(" + ', "\'", '.join("'" + part + "'" for part in value.split("'")) + ")"

    for node, element in zip(element_nodes, elements):
        unique = [loc for loc in element["locators"] if locator_counts[(loc["strategy"], loc["value"])] == 1]
        if not unique and (element["resource_id"] or element["accessibility_id"]):
            attribute = "resource-id" if element["resource_id"] else "content-desc"
            target_value = element["resource_id"] or element["accessibility_id"]
            ancestor = parents.get(node)
            for _ in range(3):
                if ancestor is None:
                    break
                matches = [n for n in ancestor.iter() if n.attrib.get(attribute) == target_value]
                if len(matches) == 1:
                    for anchor in ancestor.iter():
                        label = anchor.attrib.get("text", "")
                        anchor_attribute = "text"
                        if (not label or text_counts[label] != 1 or "textview" not in anchor.attrib.get("class", "").lower()):
                            label = anchor.attrib.get("content-desc", "")
                            anchor_attribute = "content-desc"
                            if locator_counts[("accessibility_id",label)] != 1:
                                continue
                        if (not label or len(label) > 160 or not any(c.isalnum() for c in label)
                                or "edittext" in anchor.attrib.get("class", "").lower()
                                or anchor.attrib.get("password") == "true"):
                            continue
                        cursor, hops = anchor, 0
                        while cursor is not ancestor and cursor in parents:
                            cursor, hops = parents[cursor], hops + 1
                        selector = "//*[@" + anchor_attribute + "=" + xpath_literal(label) + "]" + "/.." * hops
                        selector += "//*[@" + attribute + "=" + xpath_literal(target_value) + "]"
                        unique = [{"strategy":"xpath", "value":selector}]
                        break
                if unique:
                    break
                ancestor = parents.get(ancestor)
        element["locators"] = unique + [loc for loc in element["locators"] if loc not in unique]
        element["locator_unique"] = bool(unique)
        ancestor = parents.get(node)
        while ancestor is not None:
            if (ancestor.attrib.get('scrollable') == 'true'
                    and ancestor.attrib.get('class', '').endswith(('ScrollView', 'RecyclerView'))
                    and 'Horizontal' not in ancestor.attrib.get('class', '')):
                description = ancestor.attrib.get('content-desc', '')
                resource = ancestor.attrib.get('resource-id', '')
                container = ({'strategy': 'accessibility_id', 'value': description}
                             if description and locator_counts[('accessibility_id', description)] == 1 else
                             {'strategy': 'resource_id', 'value': resource}
                             if resource and locator_counts[('resource_id', resource)] == 1 else None)
                if container:
                    element['scroll_hint'] = {'container': container, 'direction': 'up' if element['visible'] else 'down'}
                element['in_scroller'] = description or resource or ancestor.attrib.get('class', '')
                break
            ancestor = parents.get(ancestor)
    signatures = sorted(
        (e["class_name"], e["resource_id"], e["accessibility_id"], e["text"]) for e in elements if e["visible"]
    )
    first_text = next((e["text"] for e in elements if e["type"] == "text" and e["visible"] and e["text"]), "")
    loading = bool(re.fullmatch(r"\s*(?:loading|please wait|starting|splash)[.\s…!]*", first_text, re.I))
    screen_name = first_text or activity or "Android screen"
    containers = sorted({e["accessibility_id"] for e in elements if e["visible"] and e["type"] == "element"
                         and re.search(r"(?:^|[-_\s])(?:screen|page)(?:$|[-_\s])", e["accessibility_id"], re.I)
                         and not e["within_webview"]})
    identity = ["container", *containers] if containers else []
    # Native apps often omit a labelled page container. A stable heading plus
    # activity keeps the same page identifiable while a scroll reveals new rows.
    # The heading comes from the app's own views: text inside an embedded web page (a rotating banner) changes
    # without the native screen changing.
    # Only text that stays put while the list scrolls (a toolbar title) names the screen: run
    # android_20261109_181718_321078 lost "the same screen" after a scroll because the first visible text had moved.
    fixed_heading = next((e["text"] for e in elements if e["type"] == "text" and e["visible"] and e["text"]
                          and not e["within_webview"] and not e.get("in_scroller")), "")
    scroller = next((e["in_scroller"] for e in elements if e.get("in_scroller")), "")
    native_heading = next((e["text"] for e in elements if e["type"] == "text" and e["visible"] and e["text"]
                           and not e["within_webview"]), "")
    if identity and fixed_heading and not loading:
        # One scroll-view description can be shared by many screens (My Demo App: "Scrollview manages views in
        # given screen size" on Products AND Login, run android_20261110_110821_90cd6d, so Login was taken for
        # Products and its form never tested): the fixed heading tells them apart.
        identity = [*identity, "heading", fixed_heading.casefold()[:120]]
    if not identity and activity and not loading:
        if fixed_heading:
            identity = ["activity", activity, "heading", fixed_heading.casefold()[:120]]
        elif scroller and native_heading:
            identity = ["activity", activity, "scroller", scroller[:120]]
        elif native_heading:
            identity = ["activity", activity, "heading", native_heading.casefold()[:120]]
    # A shared scroll-view shell can contain a product, Login or Signup. Keep
    # forms distinct without putting entered values into the screen identity.
    form_fields = sorted((e["class_name"], e["resource_id"] or e["accessibility_id"] or e.get("hint", ""), e["password"])
                         for e in elements if e["input_capable"] and not e["within_webview"]
                         and not e["outside_active_drawer"])
    if form_fields and not drawer_nodes and not loading:
        form_actions = sorted((e["resource_id"] or e["accessibility_id"], e["text"].casefold())
                              for e in elements if e["clickable"] and not e["input_capable"]
                              and not e["within_webview"] and re.fullmatch(
                                  r"\s*(?:log ?in|sign ?in|sign ?up|register|create (?:an? )?account|submit|continue|next|search|save|send)\s*",
                                  e["text"], re.I))
        schema = json.dumps({"fields": form_fields, "actions": form_actions}, ensure_ascii=True, separators=(",", ":"))
        identity = [*identity, "form", hashlib.sha256(schema.encode()).hexdigest()[:16]]
    if any(e["visible"] and e["class_name"].endswith("WebView") for e in elements):
        identity, screen_name = ["embedded_webview", *identity], "Embedded web content"
    if drawer_nodes:
        screen_name = "Navigation menu"
        identity = ["drawer", *sorted({e["accessibility_id"] for e in elements if not e["outside_active_drawer"] and e["accessibility_id"]})]
    if any(e["visible"] and e["resource_id"] in ("android:id/alertTitle", "android:id/parentPanel") for e in elements):
        identity = ["dialog", *identity]
    fingerprint = json.dumps(signatures, ensure_ascii=True, separators=(",", ":"))
    return {
        "platform": "android",
        "package_name": package_name,
        "device_id": device_id,
        "activity": activity,
        "screen_name": screen_name[:100],
        "identity": identity,
        "loading": loading,
        "fingerprint": fingerprint,
        "elements": elements,
    }


def safe_navigation_elements(screen: dict) -> list[dict]:
    """Clickable controls allowed for bounded exploration after risky-action filtering."""
    out = []
    has_visible_inputs = any(e.get("visible") and e.get("input_capable") for e in screen.get("elements", []))
    has_login_submit = any(e.get("visible") and e.get("clickable")
                           and re.search(r"\blog ?in\b|\bsign ?in\b", e.get("text", "") + " " + e.get("accessibility_id", ""), re.I)
                           for e in screen.get("elements", []))
    # A catalogue: a list widget, or several product pictures (one per card) on the screen. A single product
    # picture belongs to a detail screen, where it may open an image viewer outside the app.
    has_product_list = any(
        e.get("visible") and e.get("class_name", "").endswith(("RecyclerView", "GridView"))
        for e in screen.get("elements", [])
    ) or sum(bool(e.get("visible") and re.search(r"\bproduct image\b", " ".join(
        (e.get("text") or "", e.get("accessibility_id") or "")), re.I)) for e in screen.get("elements", [])) >= 2
    product_image_seen = False
    for element in screen.get("elements", []):
        if element.get("within_webview"):
            continue  # Embedded DOM interaction belongs to an explicitly approved hybrid flow.
        if screen.get("web_url"):
            if element.get("safe_web_navigation") and element.get("visible") and element.get("enabled"):
                out.append(element)
            continue
        resource = (element.get("resource_id") or "").rsplit("/", 1)[-1]
        primary = element.get("text") or element.get("accessibility_id") or ""
        label = " ".join((element.get("text") or "", element.get("accessibility_id") or "", resource))
        label = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", label).replace("_", " ")
        # Product images are navigation in a catalog, but can open external
        # image content from a product detail page. Keep discovery in-app.
        product_image = bool(re.search(r"\bproduct image\b", label, re.I))
        if product_image and (not has_product_list or product_image_seen):
            continue
        explicit_login_screen = primary.strip().casefold() in {
            "open login screen",
            "open log in screen",
            "open sign in screen",
        }
        risks = [re.sub(r"\s+", "", match.group().casefold()) for match in RISKY_ACTION.finditer(label)]
        navigation_tab = element.get("navigation_role") == "tab"
        navigation_menu = element.get("navigation_role") == "menu_item"
        login_menu = element.get("navigation_role") == "menu_item" and bool(re.search(r"\blog ?in\b|\bsign ?in\b", primary, re.I))
        signup_menu = element.get("navigation_role") == "menu_item" and bool(
            re.search(r"\bsign ?up\b|\bregister\b|\bregistration\b", primary, re.I)
        )
        signup_entry = bool(re.search(r"\bsign ?up\b|\bregister\b|\bregistration\b|\bcreate account\b", primary, re.I)) \
            and (not has_visible_inputs or signup_menu or has_login_submit)
        permitted = not risks or (explicit_login_screen or navigation_tab or login_menu) and set(risks) <= {"login", "signin"}
        permitted = permitted or signup_menu and set(risks) <= {"signup", "register"}
        permitted = permitted or signup_entry and set(risks) <= {"signup", "register", "create"}
        if (
            element.get("visible")
            and not element.get("outside_active_drawer")
            and element.get("enabled")
            and element.get("clickable")
            and not element.get("input_capable")
            and element.get("locators")
            and element.get("locator_unique", True)
            and permitted
            and (navigation_tab or navigation_menu or login_menu or signup_menu or signup_entry or explicit_login_screen
                 or SAFE_NAVIGATION.search(label))
        ):
            out.append(element)
            if product_image:
                product_image_seen = True
    return out


def recover_system_ui(driver, xml: str | None = None) -> bool:
    """Only the platform's known System UI ANR Wait button may be dismissed here."""
    source = xml if xml is not None else getattr(driver, "page_source", "")
    if not isinstance(source, str) or not source.strip():
        return False
    tree = ElementTree.fromstring(source)
    platform = [node for node in tree.iter() if node.attrib.get("package") in ("android", "com.android.systemui")]
    text = " ".join(node.attrib.get("text", "") for node in platform)
    if re.search(r"Process system\s+isn['’]t responding", text, re.I):
        raise AndroidEnvironmentError(
            "Android's system process is not responding. Restart the selected emulator/device before testing; "
            "the application has not been verified."
        )
    if not re.search(r"System UI\s+isn['’]t responding", text, re.I):
        return False
    nodes = [node for node in platform if node.attrib.get("resource-id") == "android:id/aerr_wait"]
    if len(nodes) != 1:
        raise AndroidEnvironmentError("Android System UI is unresponsive; its safe Wait control could not be identified")
    recoveries = getattr(driver, "_blowai_platform_recoveries", [])
    if len(recoveries) >= 2:
        raise AndroidEnvironmentError("Android System UI repeatedly stopped responding; restart the test device")
    buttons = [e for e in driver.find_elements("id", "android:id/aerr_wait") if e.is_displayed()]
    if len(buttons) != 1:
        raise AndroidEnvironmentError("The platform Wait control is not uniquely visible")
    buttons[0].click()
    driver._blowai_platform_recoveries = [*recoveries, {"kind": "system_ui_anr", "action": "Wait"}]
    print("[android] Recovered a blocking Android System UI dialog using its Wait control.", flush=True)
    return True


IME_PACKAGE = re.compile(r"inputmethod|keyboard|\.ime\b|honeyboard|swiftkey|gboard", re.I)
PERMISSION_PACKAGE = re.compile(r"permissioncontroller|packageinstaller", re.I)
DENY_BUTTONS = ("permission_deny_button", "permission_deny_and_dont_ask_again_button", "permission_deny_once_button")


def bring_app_back(driver, config: dict) -> str:
    """What is in front instead of the app, after the harmless cases were handled: '' when the app is in front.
    The soft keyboard reports its own package while a box has focus: it is hidden. In test mode an Android permission
    prompt is declined (never allowed) and noted. Anything else is another app: only its package name is returned,
    nothing of its screen is read."""
    expected = config.get("package_name")
    for _ in range(3):
        actual = getattr(driver, "current_package", expected)
        if not expected or actual == expected:
            return ""
        if IME_PACKAGE.search(actual or ""):
            try:
                driver.hide_keyboard()
            except Exception:
                driver.back()
            continue
        if PERMISSION_PACKAGE.search(actual or "") and config.get("interaction_testing") and not interaction_blocker(config):
            # The prompt can still be opening right after the tap (run android_20261110_110821_90cd6d): wait for
            # its Don't allow button for a few seconds before deciding it is another app.
            buttons, wait_until = [], time.monotonic() + 6
            while True:
                for button in DENY_BUTTONS:
                    buttons = [e for e in driver.find_elements("id", f"com.android.permissioncontroller:id/{button}")
                               if e.is_displayed()]
                    if buttons:
                        break
                if buttons or time.monotonic() >= wait_until or not PERMISSION_PACKAGE.search(
                        getattr(driver, "current_package", "") or ""):
                    break
                time.sleep(.5)
            if not buttons:
                actual = getattr(driver, "current_package", expected)
                if actual == expected:
                    return ""
                return actual
            prompt = ""
            try:
                found = driver.find_elements("id", "com.android.permissioncontroller:id/permission_message")
                prompt = found[0].text if found else ""
            except Exception:
                prompt = ""
            buttons[0].click()
            driver.__dict__.setdefault("_blowai_declined", []).append((prompt or "a permission")[:160])
            time.sleep(.5)
            continue
        return actual
    actual = getattr(driver, "current_package", expected)
    return "" if actual == expected else actual


def inspect_driver(driver, config: dict) -> dict:
    """Check the actual foreground package BEFORE reading the hierarchy of that app."""
    try:
        if config.get("app_mode") == "web":
            from .android_web import inspect_web
            return inspect_web(driver, config)
        actual = driver.current_package
        expected = config.get("package_name")
        if expected and actual != expected:
            actual = bring_app_back(driver, config) or expected
        if expected and actual != expected:
            # The package name only - nothing of the other app's screen is read.
            raise AndroidEnvironmentError(
                f"Navigation left the selected application ({actual} came to the front); external content was "
                "not inspected."
            )
        source = driver.page_source
        if recover_system_ui(driver, source):
            source = driver.page_source
        screen = extract_screen(source, actual, config["device_id"], driver.current_activity)
        screen["android_version"] = getattr(driver, "capabilities", {}).get("platformVersion")
        return screen
    except AndroidEnvironmentError:
        raise
    except Exception as e:
        from .safety import redact

        raise AndroidEnvironmentError("Could not inspect the Android screen: " + redact(str(e))[:300]) from e
