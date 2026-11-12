"""Stay on the page / section that was given (discovery): a link like site.com/xpath-practice-page/ is ONE section.
Every page of a website shares its header menu and its name in the title, so "the same app" can't be told from them:
the crawl follows the folder, plus what the CONTENT of a page in the folder links to (one step out) - never the
site-wide menu. Only the entire website (site mode) or a login / sign-up link opens the whole app."""
import http.server
import threading
from urllib.parse import urlparse

import pytest

from backend.agents.discovery import MENU_OUTSIDE, _leaves_section, _mode, _normalize
from backend.config import settings


def test_the_practice_page_link_is_its_own_section(monkeypatch):
    assert _mode(_normalize("https://selectorshub.com/xpath-practice-page/")) == ("section", "/xpath-practice-page")
    monkeypatch.setattr(settings, "crawl_scope", "page")  # --scope / CRAWL_SCOPE wins
    assert _mode(_normalize("https://selectorshub.com/xpath-practice-page/")) == ("page", "/xpath-practice-page")
    monkeypatch.setattr(settings, "crawl_scope", "site")
    assert _mode(_normalize("https://selectorshub.com/xpath-practice-page/")) == ("site", "")


def test_the_header_menu_never_takes_the_crawl_out_of_the_section():
    sec = "/xpath-practice-page"
    # the same blog link: in the header menu -> not followed; in the page's own content -> followed (one step out)
    assert _leaves_section("https://s.test/blog", sec, False, True, chrome=True) == MENU_OUTSIDE
    assert _leaves_section("https://s.test/blog", sec, False, True, chrome=False) == ""
    # a page one step out does not lead further out
    assert "one step out" in _leaves_section("https://s.test/deeper", sec, False, False, chrome=False)
    # pages under the folder: always, also from the menu
    assert _leaves_section("https://s.test/xpath-practice-page/part-2", sec, False, True, chrome=True) == ""
    # the entire website / a login link: everything of the app
    assert _leaves_section("https://s.test/blog", sec, True, True, chrome=True) == ""


PAGES = {  # path -> (content links, sidebar links); every page has the same header + footer and the same site name
    "/practice": (["/practice/forms", "/iframe-demo"], ["/popular"]),
    "/practice/forms": (["/practice/tables"], []),
    "/practice/tables": ([], []),
    "/iframe-demo": (["/deep-demo"], []),
}
MENU = ["/", "/blog", "/courses", "/practice/", "/about"]
OTHER = ["/", "/blog", "/courses", "/about", "/contact", "/popular", "/deep-demo"]


class _Site(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"  # (/practice/ and /practice are the same page)
        if path not in PAGES and path not in OTHER:
            self.send_error(404)
            return
        content, side = PAGES.get(path, (["/"], []))
        a = lambda hrefs: "".join(f'<a href="{h}">{h.strip("/") or "home"}</a> ' for h in hrefs)  # noqa: E731
        # the practice page also has a DEMO login form among its other practice boxes (like selectorshub's): it is
        # no door to "the whole app" - the run stays in the section
        demo = ('<form><input type="email" name="email"><input type="password" name="pass"><button>Login</button>'
                '</form>' + "".join(f'<input name="practice{n}" placeholder="Box {n}">' for n in range(5))
                if path == "/practice" else "")
        body = (f'<header><nav class="main-menu">{a(MENU)}</nav></header>'
                f'<main><h1>{path}</h1><p>Practice content.</p>{a(content)}{demo}</main>'
                f'<aside class="sidebar">{a(side)}</aside><footer>{a(["/contact"])}</footer>')
        html = f"<!doctype html><html><head><title>{path} - PracticeHub</title></head><body>{body}</body></html>"
        data = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def _paths(app_map):
    return {urlparse(p["url"]).path.strip("/") for p in app_map}


@pytest.fixture
def site():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_a_section_run_visits_its_pages_and_what_their_content_links_to(site, tmp_path, monkeypatch):
    from backend.agents.discovery import discovery_agent
    monkeypatch.setattr(settings, "max_interactions_per_page", 0)  # (only the pages matter here)
    out = discovery_agent({"url": site + "/practice/", "run_dir": str(tmp_path), "site_key": "hub", "log": []})
    visited = _paths(out["app_map"])
    assert visited == {"practice", "practice/forms", "practice/tables", "iframe-demo"}, visited
    why = {urlparse(s["url"]).path.strip("/"): s["reason"] for s in out["crawl"]["skipped"]}
    for menu_page in ("blog", "courses", "about", "contact", "popular"):  # header, footer and sidebar links
        assert why[menu_page] == MENU_OUTSIDE, (menu_page, why.get(menu_page))
    assert "one step out" in why["deep-demo"]
    assert out["crawl"]["mode"] == "section"
    assert out["login"]["found"] and not out["login"]["required"]  # a demo login form, not the app's door


def test_a_login_page_is_the_door_but_a_page_with_a_demo_login_is_not():
    from backend.agents.discovery import _login_page
    box = lambda t="text": {"type": t}  # noqa: E731
    login = {"inputs": [box("email"), box("password"), box("checkbox")]}
    practice = {"inputs": [box("email"), box("password")] + [box() for _ in range(36)]}
    assert _login_page(login, "https://s.test/portal", start_auth=False)          # only the login form
    assert _login_page(practice, "https://s.test/login", start_auth=False)        # a login address
    assert _login_page(dict(practice, final_url="https://s.test/auth/login"), "https://s.test/app", False)  # redirected
    assert not _login_page(practice, "https://s.test/xpath-practice-page", start_auth=False)


def test_scope_site_still_crawls_the_whole_website(site, tmp_path, monkeypatch):
    from backend.agents.discovery import discovery_agent
    monkeypatch.setattr(settings, "max_interactions_per_page", 0)
    monkeypatch.setattr(settings, "crawl_scope", "site")
    out = discovery_agent({"url": site + "/practice/", "run_dir": str(tmp_path), "site_key": "hub", "log": []})
    visited = _paths(out["app_map"])
    assert {"blog", "courses", "about", "contact", "popular", "deep-demo", "iframe-demo"} <= visited, visited
