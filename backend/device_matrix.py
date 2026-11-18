"""Gate D device matrix. Declares required web and Android surfaces.

A profile is verified only when evidence names that profile and records an
executed outcome. Missing or planned-only rows stay unverified — never a pass.
"""
from __future__ import annotations

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
