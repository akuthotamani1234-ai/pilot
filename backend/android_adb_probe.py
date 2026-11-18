"""Gate D: local ADB connectivity probe (not a live emulator matrix).

Records whether ``adb`` is on PATH and which devices answer. Never verifies
android.emulator / api24+ profiles without an online device + executed run.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "android_adb_probe.json"


def _enrich_api_levels(adb: str, devices: list[dict]) -> list[dict]:
    """Attach ro.build.version.sdk when a device is online."""
    import subprocess

    enriched = []
    for raw in devices:
        row = dict(raw or {})
        serial = str(row.get("device_id") or row.get("id") or row.get("serial") or "")
        status = str(row.get("status") or "").lower()
        if serial and status in {"device", "online"} and adb:
            try:
                proc = subprocess.run(
                    [adb, "-s", serial, "shell", "getprop", "ro.build.version.sdk"],
                    capture_output=True, text=True, timeout=15, check=False,
                )
                sdk = (proc.stdout or "").strip().splitlines()
                if sdk and sdk[0].isdigit():
                    row["api_level"] = int(sdk[0])
            except Exception:
                pass
        enriched.append(row)
    return enriched


def run_adb_probe(*, ops_dir: Path | None = None) -> dict:
    from .android import android_environment

    env = android_environment()
    devices = env.get("devices") if isinstance(env.get("devices"), list) else []
    adb_path = str(env.get("adb") or "")
    devices = _enrich_api_levels(adb_path, devices)
    online = [
        d for d in devices
        if str((d or {}).get("status") or "").lower() in {"device", "online"}
    ]
    evidence = {
        "gate_d_complete": False,
        "drill": "android_adb_probe",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "adb": env.get("adb"),
        "adb_present": bool(env.get("adb")),
        "appium_reachable": bool(env.get("appium_ok") or env.get("appium_reachable")),
        "devices_listed": len(devices),
        "devices_online": len(online),
        "device_ids": [
            str((d or {}).get("device_id") or (d or {}).get("id") or (d or {}).get("serial") or "")
            for d in devices
        ][:20],
        "api_levels": [
            {"device_id": str(d.get("device_id") or ""), "api_level": d.get("api_level")}
            for d in online if d.get("api_level") is not None
        ][:20],
        "errors": list(env.get("errors") or [])[:10],
        "ok": bool(env.get("adb")),
        "reason": (
            "ADB present with online device(s); live Appium product matrix still required"
            if online else
            "ADB present but no online emulator/device — Gate D Android rows stay unverified"
            if env.get("adb") else
            "ADB not on PATH — install platform-tools / start an emulator before Gate D can advance"
        ),
    }
    dest_dir = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "android_adb_probe.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "android_adb_probe.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
