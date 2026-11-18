"""Capture Gate F portfolio evidence from a finished discovery app_map.

Writes a11y_page.json, performance.json, and security_headers.json so portfolio
evaluators can run on observed data. Missing fields stay absent (unknown).
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from urllib.parse import urlparse


def _a11y_page(app_map: list[dict]) -> dict:
    images, inputs = [], []
    for page in app_map or []:
        for img in page.get("brokenImages") or []:
            images.append({"src": str(img), "alt": ""})
        # Buttons that wrap an image without an accessible name are treated as unlabeled imagery.
        for button in page.get("buttons") or []:
            if button.get("named") is False and button.get("selector"):
                images.append({"src": button.get("selector"), "alt": ""})
        for field in page.get("inputs") or []:
            inputs.append({
                "name": field.get("name") or field.get("id") or "",
                "label": field.get("label") or field.get("accname") or field.get("aria_label") or "",
                "selector": field.get("selector") or "",
            })
    return {"images": images[:100], "inputs": inputs[:200], "pages_sampled": len(app_map or [])}


def _performance(app_map: list[dict]) -> dict | None:
    times = []
    for page in app_map or []:
        try:
            ms = float(page.get("load_time_ms"))
        except (TypeError, ValueError):
            continue
        if ms >= 0:
            times.append(ms)
    if not times:
        return None
    return {
        "dom_content_loaded_ms": statistics.median(times),
        "load_ms": max(times),
        "largest_contentful_paint_ms": statistics.median(times),
        "samples": len(times),
    }


def _security(app_map: list[dict], source_url: str = "") -> dict | None:
    headers = {}
    https = None
    for page in app_map or []:
        raw = page.get("response_headers")
        if isinstance(raw, dict):
            for key, value in raw.items():
                headers.setdefault(str(key).lower(), value)
        url = page.get("final_url") or page.get("url") or ""
        if url.startswith("https://"):
            https = True if https is None else https
        elif url.startswith("http://") and https is None:
            https = False
    if https is None and source_url:
        https = source_url.startswith("https://")
    if not headers and https is None:
        return None
    return {"https": https, "headers": headers}


def capture_portfolios(run_dir: str | Path, app_map: list[dict], *, source_url: str = "") -> dict:
    """Write portfolio evidence files and return paths/payloads."""
    path = Path(run_dir)
    path.mkdir(parents=True, exist_ok=True)
    a11y = _a11y_page(app_map)
    perf = _performance(app_map)
    security = _security(app_map, source_url)
    (path / "a11y_page.json").write_text(json.dumps(a11y, indent=2), encoding="utf-8")
    out = {"a11y_page": a11y, "performance": perf, "security_headers": security}
    if perf is not None:
        (path / "performance.json").write_text(json.dumps(perf, indent=2), encoding="utf-8")
    if security is not None:
        (path / "security_headers.json").write_text(json.dumps(security, indent=2), encoding="utf-8")
    return out


def source_is_https(url: str) -> bool | None:
    scheme = urlparse(url or "").scheme.lower()
    if scheme == "https":
        return True
    if scheme == "http":
        return False
    return None
