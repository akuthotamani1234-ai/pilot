"""Discover installed AVDs and boot only the emulator selected by the user."""
import os
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

from .android import DEVICE_ABSENCE_ERRORS, AndroidEnvironmentError, _adb_path, _run_cli, _sdk_path, parse_devices

ROOT = Path(__file__).resolve().parent.parent
AVD_NAME = re.compile(r"[A-Za-z0-9_.-]{1,160}\Z")
EMULATOR_ID = re.compile(r"emulator-(\d{4,5})\Z")
_startup_lock = threading.Lock()
_launches = {}


def list_emulators(sdk):
    """Read installed AVD names. Never launch an emulator during discovery."""
    if not sdk:
        return []
    binary = Path(sdk) / "emulator" / ("emulator.exe" if os.name == "nt" else "emulator")
    if not binary.is_file():
        return []
    try:
        result = _run_cli(str(binary), ["-list-avds"], 8)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode:
        return []
    return [{"name": name, "device_id": "avd:" + name}
            for name in dict.fromkeys(result.stdout.splitlines()) if AVD_NAME.fullmatch(name)]


def connected_avd_name(adb, serial):
    if not adb or not EMULATOR_ID.fullmatch(serial):
        return None
    try:
        result = _run_cli(adb, ["-s", serial, "emu", "avd", "name"], 3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    names = [name.strip() for name in result.stdout.splitlines() if name.strip() != "OK"]
    return names[0] if result.returncode == 0 and names and AVD_NAME.fullmatch(names[0]) else None


def startup_choices(environment):
    """Enrich the setup response without changing the core environment probe."""
    environment = {**environment, "devices": [dict(d) for d in environment.get("devices", [])]}
    emulators = list_emulators(environment.get("android_sdk"))
    for device in environment["devices"]:
        if device["status"] == "device":
            device["avd_name"] = connected_avd_name(environment.get("adb"), device["device_id"])
    # Device absence/unreadiness alone must not block the Start Emulator affordance.
    can_start = bool(emulators and environment.get("android_sdk") and environment.get("adb")
                     and environment.get("java") and environment.get("uiautomator2")
                     and environment.get("appium", {}).get("available")
                     and not any(not error.startswith(DEVICE_ABSENCE_ERRORS)
                                 for error in environment.get("errors", [])))
    return {**environment, "emulators": emulators, "can_start_emulator": can_start}


def _devices(adb):
    try:
        result = _run_cli(adb, ["devices", "-l"], 8)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AndroidEnvironmentError("Could not reach ADB. Check the Android SDK connection and retry.") from error
    if result.returncode:
        raise AndroidEnvironmentError("Could not read connected Android devices. Check ADB and retry.")
    return parse_devices(result.stdout)


def _port_available(port):
    try:
        for number in (port, port + 1):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", number))
    except OSError:
        return False
    return True


def _launch(sdk, name, serial):
    port = int(EMULATOR_ID.fullmatch(serial)[1])
    folder = ROOT / "logs" / "android"
    folder.mkdir(parents=True, exist_ok=True)
    log_path = folder / ("autostart-" + name + ".log")
    binary = Path(sdk) / "emulator" / ("emulator.exe" if os.name == "nt" else "emulator")
    command = [str(binary), "-avd", name, "-port", str(port), "-gpu", "auto", "-memory", "2048",
               "-cores", "2", "-no-snapshot-load", "-no-snapshot-save", "-no-boot-anim"]
    env = {**os.environ, "ANDROID_HOME": str(sdk), "ANDROID_SDK_ROOT": str(sdk)}
    options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    try:
        # Hide the logging console on Windows; the emulator's own GUI stays visible.
        with log_path.open("ab") as log:
            process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT, **options)
    except OSError as error:
        raise AndroidEnvironmentError("Could not start the selected Android emulator. Check the SDK installation.") from error
    _launches[serial] = {"process": process, "name": name}
    return process


def ensure_device_ready(device_id, avd_name="", timeout_s=240):
    """Reuse a device, or boot its known AVD; never substitute a disconnected phone."""
    if not isinstance(device_id, str) or not device_id or len(device_id) > 200 or any(c in device_id for c in "\r\n"):
        raise AndroidEnvironmentError("Select an Android device or an installed emulator.")
    sdk, adb = _sdk_path(), _adb_path()
    if not sdk or not adb:
        missing = []
        if not sdk:
            missing.append("Android SDK (set ANDROID_HOME or ANDROID_SDK_ROOT)")
        if not adb:
            missing.append("ADB (install Platform-Tools and add platform-tools to PATH)")
        raise AndroidEnvironmentError(
            "Cannot start an emulator until these tools are available: " + "; ".join(missing) + "."
        )
    if device_id.startswith("avd:"):
        selected_name = device_id[4:]
        if not selected_name:
            raise AndroidEnvironmentError("Select an installed emulator.")
        if avd_name and selected_name != avd_name:
            raise AndroidEnvironmentError("The selected emulator names do not match.")
        avd_name = selected_name
        serial = None
    else:
        serial = device_id
    if avd_name and not AVD_NAME.fullmatch(avd_name):
        raise AndroidEnvironmentError("Select a valid installed emulator name.")
    if serial and EMULATOR_ID.fullmatch(serial):
        port = int(EMULATOR_ID.fullmatch(serial)[1])
        if not 5554 <= port <= 5682 or port % 2:
            raise AndroidEnvironmentError("Select an emulator using an even port between 5554 and 5682.")
    with _startup_lock:
        devices = _devices(adb)
        selected = next((d for d in devices if d["device_id"] == serial), None)
        if serial and not EMULATOR_ID.fullmatch(serial):
            if not selected or selected["status"] != "device":
                raise AndroidEnvironmentError("The selected phone is disconnected or unauthorized. Reconnect that phone and retry.")
            return {"device_id": serial, "started": False, "avd_name": None}
        names = {e["name"] for e in list_emulators(sdk)}
        if avd_name and avd_name not in names:
            raise AndroidEnvironmentError("The selected emulator is not installed. Create an AVD in Android Device Manager first.")
        if serial is None:
            for item in devices:
                if item["status"] == "device" and connected_avd_name(adb, item["device_id"]) == avd_name:
                    serial, selected = item["device_id"], item
                    break
            if serial is None:
                pending = next((sid for sid, item in _launches.items()
                                if item["name"] == avd_name and item["process"].poll() is None), None)
                if not pending and any(EMULATOR_ID.fullmatch(d["device_id"]) and d["status"] != "device" for d in devices):
                    raise AndroidEnvironmentError("An emulator is still connecting. Wait for Android to boot and refresh device status.")
                serial = pending or next((f"emulator-{port}" for port in range(5554, 5683, 2)
                                          if _port_available(port)), None)
                if serial is None:
                    raise AndroidEnvironmentError("No free emulator port is available.")
        if selected and selected["status"] == "device" and avd_name:
            actual = connected_avd_name(adb, serial)
            if actual != avd_name:
                raise AndroidEnvironmentError("The connected emulator does not match the selected AVD. Refresh device status.")
        process = None
        started = False
        if not selected:
            if not avd_name:
                raise AndroidEnvironmentError("This emulator is closed. Refresh device status and select an installed emulator to start automatically.")
            pending = _launches.get(serial)
            if pending and pending["process"].poll() is None:
                if pending["name"] != avd_name:
                    raise AndroidEnvironmentError("Another emulator is starting on the selected port.")
                process = pending["process"]
            else:
                if not _port_available(int(EMULATOR_ID.fullmatch(serial)[1])):
                    raise AndroidEnvironmentError("The emulator port is in use but Android is not connected yet. Wait and refresh device status.")
                process = _launch(sdk, avd_name, serial)
                started = True
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            online = any(d["device_id"] == serial and d["status"] == "device" for d in _devices(adb))
            if online:
                try:
                    boot = _run_cli(adb, ["-s", serial, "shell", "getprop", "sys.boot_completed"], 5)
                except subprocess.TimeoutExpired:
                    boot = None
                if boot and boot.returncode == 0 and boot.stdout.strip() == "1":
                    if avd_name and connected_avd_name(adb, serial) != avd_name:
                        raise AndroidEnvironmentError("Android booted on a different emulator than the selected AVD.")
                    return {"device_id": serial, "avd_name": avd_name or connected_avd_name(adb, serial), "started": started}
            if process and process.poll() not in (None, 0):
                raise AndroidEnvironmentError("The emulator exited before Android was ready. See logs/android/autostart-" + avd_name + ".log.")
            time.sleep(1)
        raise AndroidEnvironmentError("Android did not finish booting within four minutes. Keep the emulator open, wait for its home screen, then retry Start Android test.")
