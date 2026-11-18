"""Gate D: live Android emulator smoke when an online device is present.

Runs a trivial adb shell command on an online emulator, records API level, and
emits matrix evidence rows. Full Appium product matrix still open —
gate_d_complete stays False.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from .android import android_environment
from .device_matrix import evaluate_matrix

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "android_emulator_smoke_drill.json"


def _adb_shell(adb: str, serial: str, *args: str) -> str:
    proc = subprocess.run(
        [adb, "-s", serial, "shell", *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "adb shell failed")[:300])
    return (proc.stdout or "").strip()


def run_android_emulator_smoke_drill(*, ops_dir: Path | None = None) -> dict:
    env = android_environment()
    adb = str(env.get("adb") or "adb")
    devices = env.get("devices") if isinstance(env.get("devices"), list) else []
    online = [
        d for d in devices
        if isinstance(d, dict)
        and str(d.get("status") or "").lower() in {"device", "online"}
        and str(d.get("device_id") or "").startswith("emulator-")
    ]
    if not online:
        evidence = {
            "gate_d_complete": False,
            "drill": "android_emulator_smoke",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "devices_online": 0,
            "reason": "No online emulator — start AVD before Gate D Android smoke can advance",
            "matrix_rows": [],
        }
    else:
        device = online[0]
        serial = str(device.get("device_id"))
        api_level = int(_adb_shell(adb, serial, "getprop", "ro.build.version.sdk") or "0")
        model = _adb_shell(adb, serial, "getprop", "ro.product.model")
        smoke = _adb_shell(adb, serial, "echo", "qpilot-android-smoke")
        rows = [
            {
                "surface": "android",
                "device_id": serial,
                "form": "emulator",
                "api_level": api_level,
                "outcome": "passed" if "qpilot-android-smoke" in smoke else "failed",
                "source": "android_emulator_smoke",
                "model": model,
            }
        ]
        scored = evaluate_matrix(rows)
        evidence = {
            "gate_d_complete": False,
            "drill": "android_emulator_smoke",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": bool(rows) and rows[0]["outcome"] == "passed" and api_level >= 24,
            "adb": adb,
            "device_id": serial,
            "api_level": api_level,
            "model": model,
            "smoke_output": smoke[:80],
            "devices_online": len(online),
            "matrix_rows": rows,
            "android_profiles_verified": [
                p for p in (scored.get("verified") or []) if p.startswith("android.")
            ],
            "reason": (
                f"Live emulator {serial} API {api_level} smoke passed; "
                "full Appium product matrix / web+android Gate D completeness still open"
            ),
        }

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "android_emulator_smoke_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "android_emulator_smoke_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        # Persist matrix rows for the combined device matrix drill to pick up.
        rows_path = ROOT / "docs" / "ops-evidence" / "android_live_matrix_rows.json"
        rows_path.write_text(
            json.dumps(evidence.get("matrix_rows") or [], indent=2),
            encoding="utf-8",
        )
    return evidence
