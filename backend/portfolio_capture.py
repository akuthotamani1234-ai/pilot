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
        alts = page.get("imageAlts")
        if isinstance(alts, list) and alts:
            for img in alts:
                if not isinstance(img, dict):
                    continue
                alt = img.get("alt")
                if img.get("missing_alt_attr") and alt is None:
                    alt = ""
                images.append({"src": str(img.get("src") or ""), "alt": "" if alt is None else str(alt)})
        else:
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


def _compatibility(app_map: list[dict], crawl: dict | None = None) -> dict | None:
    """Build a desktop/mobile viewport matrix from app_map / crawl flags."""
    crawl = crawl or {}
    desktop = 0
    mobile = 0
    for page in app_map or []:
        desktop += 1
        if page.get("mobile") or page.get("mobile_checked") or page.get("viewport") == "mobile":
            mobile += 1
    if crawl.get("mobile_check") and mobile == 0 and desktop:
        mobile = desktop
    if desktop == 0 and mobile == 0 and not crawl.get("mobile_check"):
        return None
    matrix = {
        "desktop": desktop,
        "mobile": mobile,
        "desktop_or_default": desktop,
        "mobile_checked": mobile,
        "gate_f_complete": False,
    }
    browsers = crawl.get("browsers") if isinstance(crawl.get("browsers"), list) else None
    if browsers:
        matrix["browsers"] = browsers
    return matrix


def capture_portfolios(run_dir: str | Path, app_map: list[dict], *, source_url: str = "",
                       crawl: dict | None = None) -> dict:
    """Write portfolio evidence files and return paths/payloads."""
    path = Path(run_dir)
    from .finalization import folder_is_linked
    if folder_is_linked(path):
        return {"a11y_page": {}, "performance": None, "security_headers": None, "compatibility": None}
    path.mkdir(parents=True, exist_ok=True)
    from .finalization import write_text_unless_linked
    a11y = _a11y_page(app_map)
    perf = _performance(app_map)
    security = _security(app_map, source_url)
    compat = _compatibility(app_map, crawl)
    write_text_unless_linked(path, "a11y_page.json", json.dumps(a11y, indent=2))
    out = {"a11y_page": a11y, "performance": perf, "security_headers": security,
           "compatibility": compat}
    if perf is not None:
        write_text_unless_linked(path, "performance.json", json.dumps(perf, indent=2))
    if security is not None:
        write_text_unless_linked(path, "security_headers.json", json.dumps(security, indent=2))
    if compat is not None:
        write_text_unless_linked(path, "compatibility.json", json.dumps(compat, indent=2))
    return out


def source_is_https(url: str) -> bool | None:
    scheme = urlparse(url or "").scheme.lower()
    if scheme == "https":
        return True
    if scheme == "http":
        return False
    return None
