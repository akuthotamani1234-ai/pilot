"""Gate A surface coverage summary from a finished app_map.

Counts iframe/frame inventory, open shadow roots, closed/unsupported hosts,
API/openapi seed hints, lazy-loaded content, locale/metadata signals,
desktop/mobile viewport presence, dialogs/modals, and download links.
Missing surfaces stay unknown — never a pass.
"""
from __future__ import annotations


def summarize_surfaces(app_map: list[dict] | None = None, crawl: dict | None = None) -> dict:
    pages = app_map or []
    crawl = crawl or {}
    frames = {"testable": 0, "external": 0, "unreachable": 0, "pages_with_frames": 0, "listed_iframes": 0}
    shadow = {"open_roots_seen": 0, "pages_with_shadow": 0, "closed_unsupported": 0}
    lazy = {"pages_with_lazy": 0, "items_seen": 0}
    metadata = {"pages_with_locale": 0, "pages_with_skeleton": 0, "title_or_meta": 0}
    viewports = {"desktop_or_default": 0, "mobile_checked": 0}
    dialogs = {"pages_with_dialogs": 0, "form_dialogs": 0, "modal_buttons": 0}
    downloads = {"pages_with_downloads": 0, "links": 0}
    rich = {"canvas": 0, "file_upload": 0, "web_component": 0, "pages_with_rich": 0}
    for page in pages:
        page_frames = page.get("frames") if isinstance(page.get("frames"), list) else []
        listed = page.get("iframes") if isinstance(page.get("iframes"), list) else []
        if page_frames or listed:
            frames["pages_with_frames"] += 1
        frames["listed_iframes"] += len(listed)
        for fr in page_frames:
            status = str((fr or {}).get("status") or "").lower()
            if status == "testable":
                frames["testable"] += 1
            elif status == "external":
                frames["external"] += 1
            else:
                frames["unreachable"] += 1
        roots = page.get("shadowRoots")
        try:
            n_roots = int(roots or 0)
        except (TypeError, ValueError):
            n_roots = 0
        if n_roots > 0:
            shadow["pages_with_shadow"] += 1
            shadow["open_roots_seen"] += n_roots
        for item in page.get("unsupported") or []:
            reason = str((item or {}).get("reason") or item or "").lower()
            if "shadow" in reason or "closed" in reason:
                shadow["closed_unsupported"] += 1

        lazy_payload = page.get("lazy")
        if isinstance(lazy_payload, dict) and lazy_payload:
            lazy["pages_with_lazy"] += 1
            lazy["items_seen"] += sum(
                len(v) if isinstance(v, list) else (1 if v else 0) for v in lazy_payload.values()
            )
        elif lazy_payload:
            lazy["pages_with_lazy"] += 1
            lazy["items_seen"] += 1

        locale = page.get("locale") if isinstance(page.get("locale"), dict) else {}
        if locale:
            metadata["pages_with_locale"] += 1
        if page.get("skeleton"):
            metadata["pages_with_skeleton"] += 1
        if page.get("title") or page.get("meta") or page.get("description"):
            metadata["title_or_meta"] += 1

        viewports["desktop_or_default"] += 1
        if page.get("mobile") or page.get("mobile_checked") or page.get("viewport") == "mobile":
            viewports["mobile_checked"] += 1

        page_dialogs = 0
        for form in page.get("forms") or []:
            sel = str((form or {}).get("selector") or "")
            kind = str((form or {}).get("kind") or (form or {}).get("type") or "").lower()
            if "dialog" in sel or "modal" in sel or kind in {"dialog", "modal"}:
                dialogs["form_dialogs"] += 1
                page_dialogs += 1
        for btn in page.get("buttons") or []:
            kind = str((btn or {}).get("kind") or (btn or {}).get("opens") or "").lower()
            role = str((btn or {}).get("role") or "").lower()
            if kind in {"modal", "dialog"} or role == "dialog":
                dialogs["modal_buttons"] += 1
                page_dialogs += 1
        if page_dialogs:
            dialogs["pages_with_dialogs"] += 1

        page_downloads = 0
        for link in page.get("links") or []:
            if (link or {}).get("download"):
                downloads["links"] += 1
                page_downloads += 1
        if page_downloads:
            downloads["pages_with_downloads"] += 1

        page_rich = 0
        components = []
        inv = page.get("component_inventory") if isinstance(page.get("component_inventory"), dict) else {}
        if isinstance(inv.get("components"), list):
            components.extend(inv["components"])
        if isinstance(page.get("components"), list):
            components.extend(page["components"])
        for row in components:
            kind = str((row or {}).get("kind") or "").lower()
            if kind == "canvas":
                rich["canvas"] += 1
                page_rich += 1
            elif kind in {"file_upload", "file"}:
                rich["file_upload"] += 1
                page_rich += 1
            elif kind in {"web_component", "custom_element"}:
                rich["web_component"] += 1
                page_rich += 1
        for field in page.get("inputs") or []:
            ftype = str((field or {}).get("type") or (field or {}).get("kind") or "").lower()
            if ftype in {"file", "file_upload"}:
                rich["file_upload"] += 1
                page_rich += 1
        if page_rich:
            rich["pages_with_rich"] += 1

    # Crawl-level mobile flag when pages did not store per-page mobile rows.
    if crawl.get("mobile_check") and viewports["mobile_checked"] == 0 and pages:
        viewports["mobile_checked"] = len(pages)

    found_by = crawl.get("found_by") if isinstance(crawl.get("found_by"), dict) else {}
    api = {
        "network_seeded": sum(1 for how in found_by.values() if how == "network"),
        "openapi_or_scrape": sum(1 for how in found_by.values() if how in {"scrape", "openapi", "sitemap"}),
        "blocked_requests": len(crawl.get("blocked_requests") or []),
    }
    evidence = {
        "pages": len(pages),
        "frames": frames,
        "shadow": shadow,
        "api": api,
        "lazy": lazy,
        "metadata": metadata,
        "viewports": viewports,
        "dialogs": dialogs,
        "downloads": downloads,
        "rich_controls": rich,
    }
    unknown = []
    if not pages:
        unknown.append("no pages inventoried")
    if frames["pages_with_frames"] == 0 and frames["listed_iframes"] == 0:
        unknown.append("iframe inventory empty on this run")
    if shadow["open_roots_seen"] == 0 and shadow["closed_unsupported"] == 0:
        unknown.append("shadow DOM signals empty on this run")
    if api["network_seeded"] == 0 and api["openapi_or_scrape"] == 0:
        unknown.append("no API/network/openapi seeds recorded")
    if lazy["pages_with_lazy"] == 0:
        unknown.append("no lazy-loaded content signals recorded")
    if metadata["pages_with_locale"] == 0 and metadata["title_or_meta"] == 0:
        unknown.append("no locale/title metadata signals recorded")
    if viewports["mobile_checked"] == 0:
        unknown.append("no mobile viewport check recorded")
    if dialogs["pages_with_dialogs"] == 0:
        unknown.append("no dialog/modal surfaces recorded")
    if downloads["links"] == 0:
        unknown.append("no download links recorded")
    if rich["canvas"] == 0 and rich["file_upload"] == 0 and rich["web_component"] == 0:
        unknown.append("no canvas/file-upload/web-component controls recorded")
    return {
        "gate_a_surfaces_complete": False,
        "pages": len(pages),
        "frames": frames,
        "shadow": shadow,
        "dialogs": dialogs,
        "downloads": downloads,
        "lazy": lazy,
        "metadata": metadata,
        "viewports": viewports,
        "api": api,
        "rich_controls": rich,
        "unknown": unknown,
        "evidence": evidence,
        "note": (
            "Surface counts are run-local. Empty does not prove the site lacks "
            "iframes/shadow/API/lazy/metadata/dialogs/downloads/rich controls."
        ),
    }
