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


def _linked_smoke() -> dict:
    return {
        "gate_d_complete": False,
        "ok": False,
        "drill": "android_emulator_smoke",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_android_emulator_smoke_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    if ops_dir is not None and folder_is_linked(Path(ops_dir)):
        return _linked_smoke()

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

    text = json.dumps(evidence, indent=2)
    name = "android_emulator_smoke_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_smoke()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_smoke()
    # Keep a dedicated API24 smoke artifact so later API30 refreshes do not erase it.
    if evidence.get("ok") and int(evidence.get("api_level") or 0) == 24:
        api24 = {
            **evidence,
            "drill": "android_emulator_smoke_api24",
            "note": "Dedicated API24 smoke; preserved across higher-API refreshes",
        }
        api24_name = "android_emulator_smoke_api24_drill.json"
        if not folder_is_linked(dest / api24_name):
            write_text_unless_linked(dest, api24_name, json.dumps(api24, indent=2))
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
        # Merge into live matrix rows so API24 evidence survives API30 refreshes.
        rows_name = "android_live_matrix_rows.json"
        rows_dir = ROOT / "docs" / "ops-evidence"
        rows_path = rows_dir / rows_name
        if not folder_is_linked(rows_path) and not folder_is_linked(rows_dir):
            existing: list = []
            if rows_path.is_file():
                try:
                    loaded = json.loads(rows_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, list):
                        existing = [r for r in loaded if isinstance(r, dict)]
                except (OSError, ValueError):
                    existing = []
            fresh = [
                r for r in (evidence.get("matrix_rows") or [])
                if isinstance(r, dict)
            ]
            merged: list[dict] = []
            seen: set[tuple] = set()
            for row in existing + fresh:
                key = (
                    str(row.get("source") or ""),
                    str(row.get("device_id") or ""),
                    str(row.get("api_level") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append(row)
            rows_dir.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(rows_dir, rows_name, json.dumps(merged, indent=2))
    return evidence
