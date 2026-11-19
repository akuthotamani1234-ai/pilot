"""Gate F visual evidence when a full pixel diff has not run yet.

Uses discovery screenshots already on disk. First-run pages are marked ``new``
(not changed). Never invents a pass from missing files.
"""
from __future__ import annotations

import json
from pathlib import Path


def capture_visual(run_dir: str | Path, app_map: list[dict] | None = None) -> dict:
    """Write or reuse visual.json. Existing pixel reports are left untouched."""
    path = Path(run_dir)
    existing = path / "visual.json"
    if path.is_symlink() or existing.is_symlink():
        return {
            "first_run": False, "pages": [], "changed": [], "same": [],
            "source": "discovery_screenshots", "note": "the visual report is a link",
        }
    if existing.is_file():
        try:
            payload = json.loads(existing.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload:
                return payload
        except (OSError, ValueError):
            pass
    from .agents.change_detection import relative_path_is_linked
    pages = []
    for page in app_map or []:
        shot = page.get("screenshot") or ""
        if not shot:
            continue
        rel = Path(str(shot))
        shot_path = path / rel
        if relative_path_is_linked(path, rel) or not shot_path.is_file():
            continue
        pages.append({
            "key": page.get("slug") or page.get("url") or shot,
            "url": page.get("url") or "",
            "status": "new",
            "screenshot": shot,
        })
    report = {
        "first_run": True,
        "pages": pages,
        "changed": [],
        "same": [],
        "source": "discovery_screenshots",
        "note": "pixel diff not run; pages recorded as first-run evidence only",
    }
    from .finalization import write_text_unless_linked
    if not path.is_symlink():
        path.mkdir(parents=True, exist_ok=True)
        write_text_unless_linked(path, "visual.json", json.dumps(report, indent=2))
    return report
