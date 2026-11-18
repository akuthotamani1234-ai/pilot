"""Gate A: capture surface_coverage evidence from owned local fixtures.

Walks key pages with Playwright, builds a mini app_map, and writes evidence under
``docs/ops-evidence/``. Never marks Gate A complete.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADMIN_EVIDENCE = ROOT / "docs" / "ops-evidence" / "admin_portal_surface_coverage.json"
DEMO_EVIDENCE = ROOT / "docs" / "ops-evidence" / "demo_store_surface_coverage.json"
CLASSIC_EVIDENCE = ROOT / "docs" / "ops-evidence" / "classic_shop_surface_coverage.json"
TRAVEL_EVIDENCE = ROOT / "docs" / "ops-evidence" / "travel_site_surface_coverage.json"
ADMIN_PATHS = ("/", "/users", "/users/new", "/widgets", "/reports", "/help", "/help/guide")
DEMO_PATHS = ("/", "/about", "/lab", "/deals", "/signin")
CLASSIC_PATHS = (
    "/",
    "/?rt=product/category&path=10",
    "/?rt=product/search&keyword=lip",
    "/?rt=checkout/cart",
    "/?rt=account/login",
    "/?rt=content/contact",
)
TRAVEL_PATHS = ("/", "/signup", "/search?from=LHR&to=JFK&trip=oneway&depart=2099-01-15&passengers=1")

_SNAP_JS = """() => {
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
  const components = [];
  document.querySelectorAll('canvas').forEach(el => {
    components.push({kind: 'canvas', selector: el.id ? ('#' + el.id) : 'canvas'});
  });
  document.querySelectorAll('input[type=file]').forEach(el => {
    components.push({kind: 'file_upload', selector: el.id ? ('#' + el.id) : 'input[type=file]'});
  });
  document.querySelectorAll('*').forEach(el => {
    if (el.tagName && el.tagName.includes('-')) {
      components.push({kind: 'web_component', selector: el.tagName.toLowerCase()});
    }
  });
  return {
    title: document.title || '',
    iframes,
    frames: iframes.map(f => ({status: 'testable', name: f.name || f.src})),
    shadowRoots,
    forms,
    buttons,
    links,
    components,
    lazy: document.querySelector('[loading=lazy], .skeleton, [data-lazy]') ? {hint: true} : null,
    locale: {language: document.documentElement.lang || navigator.language || ''},
  };
}"""


def _walk_fixture(base_url: str, paths: tuple[str, ...]) -> list[dict]:
    from playwright.sync_api import sync_playwright

    pages: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1366, "height": 900})
        for path in paths:
            page.goto(base_url.rstrip("/") + path, wait_until="domcontentloaded")
            page.wait_for_timeout(200)
            snap = page.evaluate(_SNAP_JS)
            pages.append({
                "url": base_url.rstrip("/") + path,
                "slug": path.strip("/") or "home",
                "title": snap.get("title") or path,
                "iframes": snap.get("iframes") or [],
                "frames": snap.get("frames") or [],
                "shadowRoots": snap.get("shadowRoots") or 0,
                "forms": snap.get("forms") or [],
                "buttons": snap.get("buttons") or [],
                "links": snap.get("links") or [],
                "components": snap.get("components") or [],
                "lazy": snap.get("lazy"),
                "locale": snap.get("locale") or {},
                "mobile_checked": False,
            })
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(base_url, wait_until="domcontentloaded")
        if pages:
            pages[0]["mobile_checked"] = True
            pages[0]["viewport"] = "mobile"
        browser.close()
    return pages


def _write_evidence(evidence: dict, *, evidence_path: Path, ops_dir: Path | None) -> dict:
    dest = Path(ops_dir) if ops_dir else evidence_path.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / evidence_path.name) if ops_dir else evidence_path
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / evidence_path.name
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence


def run_admin_portal_surface_drill(*, ops_dir: Path | None = None) -> dict:
    from tests.admin_portal import AdminPortal

    from .surface_coverage import summarize_surfaces

    portal = AdminPortal(0, bugs=False).start()
    try:
        pages = _walk_fixture(portal.url, ADMIN_PATHS)
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
            "AdminPortal surface inventory captured (iframe/shadow/dialog/download/rich when present); "
            "full Gate A live matrix still open"
        ),
    }
    return _write_evidence(evidence, evidence_path=ADMIN_EVIDENCE, ops_dir=ops_dir)


def _fixture_surface_drill(*, fixture: str, start, paths: tuple[str, ...], evidence_path: Path,
                           crawl_extra: dict | None = None, ops_dir: Path | None = None,
                           reason: str = "") -> dict:
    from .surface_coverage import summarize_surfaces

    site = start()
    try:
        pages = _walk_fixture(site.url, paths)
        crawl = {"mobile_check": True, "found_by": {}}
        if crawl_extra:
            crawl.update(crawl_extra)
        # Prefer scrape seed for first non-home path when callers want API/openapi signal.
        if pages and not crawl.get("found_by"):
            crawl["found_by"] = {pages[min(1, len(pages) - 1)]["url"]: "scrape"}
        surfaces = summarize_surfaces(pages, crawl)
    finally:
        try:
            site.stop()
        except Exception:
            pass
    evidence = {
        "gate_a_surfaces_complete": False,
        "drill": evidence_path.stem,
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixture": fixture,
        "pages_walked": [p["slug"] for p in pages],
        "surfaces": surfaces,
        "reason": reason or (
            f"{fixture} surface inventory captured; full Gate A live matrix still open"
        ),
    }
    return _write_evidence(evidence, evidence_path=evidence_path, ops_dir=ops_dir)


def run_demo_store_surface_drill(*, ops_dir: Path | None = None) -> dict:
    """Walk DemoStore public pages incl. /lab (iframe + shadow) for Gate A evidence."""
    from tests.demo_store import DemoStore

    store = DemoStore().start()
    try:
        pages = _walk_fixture(store.url, DEMO_PATHS)
        lab = store.url.rstrip("/") + "/lab"
    finally:
        try:
            store.stop()
        except Exception:
            pass
    from .surface_coverage import summarize_surfaces
    surfaces = summarize_surfaces(pages, {"mobile_check": True, "found_by": {lab: "scrape"}})
    evidence = {
        "gate_a_surfaces_complete": False,
        "drill": "demo_store_surface_coverage",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixture": "DemoStore",
        "pages_walked": [p["slug"] for p in pages],
        "surfaces": surfaces,
        "reason": (
            "DemoStore public surface inventory captured (incl. /lab iframe+shadow when present); "
            "full Gate A live matrix still open"
        ),
    }
    return _write_evidence(evidence, evidence_path=DEMO_EVIDENCE, ops_dir=ops_dir)


def run_classic_shop_surface_drill(*, ops_dir: Path | None = None) -> dict:
    from tests.classic_shop import ClassicShop
    return _fixture_surface_drill(
        fixture="ClassicShop",
        start=lambda: ClassicShop().start(),
        paths=CLASSIC_PATHS,
        evidence_path=CLASSIC_EVIDENCE,
        ops_dir=ops_dir,
        reason=(
            "ClassicShop route-template surface inventory captured; "
            "full Gate A live matrix still open"
        ),
    )


def run_travel_site_surface_drill(*, ops_dir: Path | None = None) -> dict:
    from tests.travel_site import TravelSite
    return _fixture_surface_drill(
        fixture="TravelSite",
        start=lambda: TravelSite().start(),
        paths=TRAVEL_PATHS,
        evidence_path=TRAVEL_EVIDENCE,
        ops_dir=ops_dir,
        reason=(
            "TravelSite search/signup surface inventory captured; "
            "full Gate A live matrix still open"
        ),
    )
