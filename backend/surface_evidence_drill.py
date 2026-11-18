"""Gate A: capture surface_coverage evidence from the owned AdminPortal fixture.

Walks key pages with Playwright, builds a mini app_map, and writes
``docs/ops-evidence/admin_portal_surface_coverage.json``. Never marks Gate A complete.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "admin_portal_surface_coverage.json"
PATHS = ("/", "/users", "/users/new", "/widgets", "/reports", "/help", "/help/guide")


def run_admin_portal_surface_drill(*, ops_dir: Path | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    from tests.admin_portal import AdminPortal

    from .surface_coverage import summarize_surfaces

    portal = AdminPortal(0, bugs=False).start()
    pages: list[dict] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1366, "height": 900})
            for path in PATHS:
                page.goto(portal.url.rstrip("/") + path, wait_until="domcontentloaded")
                page.wait_for_timeout(200)
                snap = page.evaluate(
                    """() => {
                      const iframes = [...document.querySelectorAll('iframe')].map(el => ({
                        name: el.getAttribute('name') || el.getAttribute('title') || '',
                        src: el.getAttribute('src') || '',
                      }));
                      let shadowRoots = 0;
                      const walk = (root) => {
                        root.querySelectorAll('*').forEach(el => {
                          if (el.shadowRoot) { shadowRoots += 1; walk(el.shadowRoot); }
                        });
                      };
                      walk(document);
                      const forms = [...document.querySelectorAll('form, dialog, [role=dialog], .modal')].map(el => ({
                        selector: el.id ? ('#' + el.id) : el.tagName.toLowerCase(),
                        kind: el.matches('dialog, [role=dialog], .modal') ? 'dialog' : 'form',
                      }));
                      const buttons = [...document.querySelectorAll('button,[role=button]')].map(el => ({
                        text: (el.innerText || '').trim().slice(0, 40),
                        kind: /modal|dialog|prompt|alert/i.test(el.id + el.className + (el.innerText||''))
                          ? 'modal' : 'button',
                      }));
                      const links = [...document.querySelectorAll('a')].map(a => ({
                        href: a.getAttribute('href') || '',
                        download: a.hasAttribute('download'),
                      }));
                      return {
                        title: document.title || '',
                        iframes,
                        frames: iframes.map(f => ({status: 'testable', name: f.name || f.src})),
                        shadowRoots,
                        forms,
                        buttons,
                        links,
                        lazy: document.querySelector('[loading=lazy], .skeleton, [data-lazy]')
                          ? {hint: true} : null,
                        locale: {language: document.documentElement.lang || navigator.language || ''},
                      };
                    }"""
                )
                pages.append({
                    "url": portal.url.rstrip("/") + path,
                    "slug": path.strip("/") or "home",
                    "title": snap.get("title") or path,
                    "iframes": snap.get("iframes") or [],
                    "frames": snap.get("frames") or [],
                    "shadowRoots": snap.get("shadowRoots") or 0,
                    "forms": snap.get("forms") or [],
                    "buttons": snap.get("buttons") or [],
                    "links": snap.get("links") or [],
                    "lazy": snap.get("lazy"),
                    "locale": snap.get("locale") or {},
                    "mobile_checked": False,
                })
            # Phone viewport pass on home
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(portal.url, wait_until="domcontentloaded")
            if pages:
                pages[0]["mobile_checked"] = True
                pages[0]["viewport"] = "mobile"
            browser.close()
    finally:
        try:
            portal.stop()
        except Exception:
            pass

    surfaces = summarize_surfaces(pages, {"mobile_check": True, "found_by": {}})
    evidence = {
        "gate_a_surfaces_complete": False,
        "drill": "admin_portal_surface_coverage",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixture": "AdminPortal",
        "pages_walked": [p["slug"] for p in pages],
        "surfaces": surfaces,
        "reason": (
            "AdminPortal surface inventory captured (iframe/shadow/dialog/download when present); "
            "full Gate A live matrix still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "admin_portal_surface_coverage.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "admin_portal_surface_coverage.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
