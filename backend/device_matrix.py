"""Gate D device matrix. Declares required web and Android surfaces.

A profile is verified only when evidence names that profile and records an
executed outcome. Missing or planned-only rows stay unverified — never a pass.
"""
from __future__ import annotations

import json
from pathlib import Path

REQUIRED_PROFILES = (
    {"id": "web.desktop", "surface": "web", "viewport": "1366x900", "required": True},
    {"id": "web.phone", "surface": "web", "viewport": "390x844", "required": True},
    {"id": "android.emulator", "surface": "android", "form": "emulator", "required": True},
    {"id": "android.api24+", "surface": "android", "api_min": 24, "required": True},
)

_DONE = frozenset({"passed", "failed", "blocked", "error"})


def default_matrix() -> list[dict]:
    """Copy of the required Gate D profiles."""
    return [dict(row) for row in REQUIRED_PROFILES]


def _match(profile: dict, evidence: dict) -> bool:
    if evidence.get("profile_id") == profile["id"]:
        return True
    surface = (evidence.get("surface") or "").strip().lower()
    if surface != profile["surface"]:
        return False
    if profile["surface"] == "web":
        return (evidence.get("viewport") or "") == profile.get("viewport")
    if profile.get("form") == "emulator":
        device = str(evidence.get("device_id") or "")
        return device.startswith("emulator-") or evidence.get("form") == "emulator"
    api_min = profile.get("api_min")
    if api_min is not None:
        try:
            return int(evidence.get("api_level") or evidence.get("android_version") or 0) >= int(api_min)
        except (TypeError, ValueError):
            return False
    return False


def android_evidence_from_run(run_dir: str | Path | None = None, *, config: dict | None = None,
                              results: list[dict] | None = None) -> list[dict]:
    """Emit Android matrix rows only when this run recorded a real device/config.

    Never invents emulator evidence for web-only runs. ``outcome`` comes from
    executed results when present; otherwise the environment probe alone is not
    enough to verify a profile.
    """
    cfg = dict(config or {})
    env = {}
    if run_dir:
        path = Path(run_dir) / "android_environment.json"
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    env = loaded
            except (OSError, ValueError):
                env = {}
        if not cfg:
            for name in ("android_config.json", ".private/android_config.json"):
                cfg_path = Path(run_dir) / name
                if cfg_path.is_file():
                    try:
                        loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
                        if isinstance(loaded, dict):
                            cfg = loaded
                            break
                    except (OSError, ValueError):
                        continue
    device_id = str(cfg.get("device_id") or cfg.get("udid") or "").strip()
    if not device_id and isinstance(env.get("devices"), list):
        # Prefer an emulator that was online during the probe.
        for device in env["devices"]:
            if not isinstance(device, dict):
                continue
            did = str(device.get("device_id") or "")
            if did.startswith("emulator-") and str(device.get("status") or "") == "device":
                device_id = did
                break
    if not device_id:
        return []
    api_level = cfg.get("api_level") or cfg.get("android_version") or cfg.get("platform_version")
    if api_level in (None, "") and isinstance(env.get("devices"), list):
        for device in env["devices"]:
            if isinstance(device, dict) and str(device.get("device_id") or "") == device_id:
                api_level = device.get("api_level") or device.get("android_version")
                break
    outcomes = []
    for row in results or []:
        status = str(row.get("status") or row.get("execution_status") or row.get("outcome") or "").lower()
        if status in {"passed", "pass"}:
            outcomes.append("passed")
        elif status in {"failed", "fail", "error"}:
            outcomes.append("failed")
        elif status in {"blocked", "skipped", "inconclusive"}:
            outcomes.append("blocked")
    if not outcomes:
        # Environment/config present but nothing executed — leave unverified.
        return []
    outcome = outcomes[0]
    form = "emulator" if device_id.startswith("emulator-") or str(cfg.get("form") or "") == "emulator" else ""
    row = {
        "surface": "android",
        "device_id": device_id,
        "form": form,
        "api_level": api_level,
        "outcome": outcome,
        "source": "android_run",
    }
    return [row]


def viewport_evidence_from_app_map(app_map: list[dict] | None = None) -> list[dict]:
    """Evidence from discovery viewports already exercised (desktop + phone).

    Desktop (1366x900) is the crawl context. Phone (390x844) counts only when a
    page records ``mobile_only`` / phone layout / phone visual capture.
    """
    pages = app_map or []
    if not pages:
        return []
    ok_pages = [p for p in pages if not p.get("error") and (p.get("status") or 0) < 400]
    if not ok_pages:
        # Still opened something — treat as failed surface evidence, not missing.
        outcome = "failed"
        sample = pages
    else:
        outcome = "passed"
        sample = ok_pages
    evidence = [{
        "surface": "web",
        "viewport": "1366x900",
        "outcome": outcome,
        "source": "discovery",
        "pages": len(sample),
    }]
    phone_pages = [
        p for p in sample
        if "mobile_only" in p
        or p.get("layout") is not None
        or (isinstance(p.get("visual"), dict) and (p["visual"].get("phone") or p["visual"].get("phone_shot")))
    ]
    if phone_pages:
        evidence.append({
            "surface": "web",
            "viewport": "390x844",
            "outcome": outcome,
            "source": "discovery",
            "pages": len(phone_pages),
        })
    return evidence


def evaluate_matrix(evidence: list[dict] | None = None) -> dict:
    """Score required profiles against recorded run evidence.

    Evidence rows need ``outcome`` in {passed, failed, blocked, error} to count.
    """
    rows = evidence or []
    profiles = []
    for profile in default_matrix():
        hits = [e for e in rows if _match(profile, e) and (e.get("outcome") or "").lower() in _DONE]
        status = "verified" if hits else "unverified"
        profiles.append({
            **profile,
            "status": status,
            "evidence_count": len(hits),
            "outcomes": sorted({(e.get("outcome") or "").lower() for e in hits}),
        })
    required = [p for p in profiles if p.get("required")]
    verified = [p for p in required if p["status"] == "verified"]
    return {
        "complete": len(verified) == len(required) and bool(required),
        "verified": [p["id"] for p in verified],
        "unverified": [p["id"] for p in required if p["status"] != "verified"],
        "profiles": profiles,
        "live_emulator_required": any(p["id"] == "android.emulator" and p["status"] != "verified"
                                      for p in required),
    }
