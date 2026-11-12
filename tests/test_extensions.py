"""Step 11 + steps 14-19 (the extensions):
  11 the human review asks about an expected result that was only observed, waits for the answer, applies it and
     remembers it for the next run;
  14 pages found by the sitemap, by the page's own network requests and by a single-page app's history API - each
     page says how it was found;
  15 several user roles: a lower role is refused an admin page, the higher one may open it; the role tests are made;
  16 phone width: a control only a phone shows (a hamburger) is found, a page that scrolls sideways is a finding;
  18 the JavaScript coverage: V8's nested block ranges -> the covered stretches;
  19 the frontier explores new kinds of pages first, polite speed, --section, merging reports."""
import http.server
import json
import threading
from urllib.parse import urlparse

import pytest

from backend.config import settings


def _serve(routes: dict):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0].rstrip("/") or "/"
            code, ctype, body = routes.get(path, (404, "text/html", "<p>missing</p>"))
            if callable(body):
                body = body(self)
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            form = dict(x.split("=", 1) for x in self.rfile.read(length).decode().split("&") if "=" in x)
            user = {"admin%40x.test": "admin", "viewer%40x.test": "viewer"}.get(form.get("email"))
            ok = user and form.get("password") == "Pass%23123"
            self.send_response(303)
            self.send_header("Location", "/dashboard" if ok else "/login")
            if ok:
                self.send_header("Set-Cookie", f"who={user}; Path=/")
            self.end_headers()

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _page(title, body, extra=""):
    return f"<!doctype html><html><head><title>{title}</title>{extra}</head><body><main>{body}</main></body></html>"


def test_the_review_asks_waits_and_remembers(tmp_path, monkeypatch):
    from backend import review
    monkeypatch.setattr(settings, "baseline_dir", tmp_path / "baseline")
    monkeypatch.setattr(settings, "review", "on")
    monkeypatch.setattr(settings, "review_timeout_s", 30)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cases = [{"tc_id": "TC-1", "kind": "learned", "oracle": "observed", "title": "Load totals",
              "spec": {"name": "Load totals", "action": "click", "added": ["Total sales: 4560"]}},
             {"tc_id": "TC-2", "kind": "learned", "oracle": "observed", "title": "Help",
              "spec": {"name": "Help", "action": "click", "added": ["Help text"]}}]

    def answer():  # (what the web UI does: the whole file at once)
        tmp = run_dir / "answers.tmp"
        tmp.write_text(json.dumps({"answers": {"TC-1": {"answer": "should be", "text": "Total sales: 4,560"},
                                               "TC-2": {"answer": "skip"}}}), encoding="utf-8")
        tmp.replace(run_dir / "review_answers.json")
    threading.Timer(1.5, answer).start()
    out = review.review_gate_agent({"site_key": "s", "run_dir": str(run_dir), "test_cases": cases, "log": []})
    asked = json.loads((run_dir / "review_request.json").read_text(encoding="utf-8"))["questions"]
    assert asked[0]["question"] == "Clicking 'Load totals' showed 'Total sales: 4560'. Is that correct?"
    assert [c["tc_id"] for c in out["test_cases"]] == ["TC-1"]
    assert out["test_cases"][0]["spec"]["added"] == ["Total sales: 4,560"]
    monkeypatch.setattr(settings, "review", "off")  # the next run: the answers apply without asking
    again = review.review_gate_agent({"site_key": "s", "run_dir": str(tmp_path), "test_cases": cases, "log": []})
    assert [c["tc_id"] for c in again["test_cases"]] == ["TC-1"] and again["test_cases"][0]["oracle"] == "requirement"


def test_more_ways_to_find_pages(tmp_path, monkeypatch):
    from backend.agents.discovery import discovery_agent
    srv, url = _serve({
        # (a single-page app moves to a route without a link, then back - the start page stays the start page)
        "/": (200, "text/html", _page("Home", '<a href="/a">A</a><script>history.pushState({}, "", "/spa-route");'
                                               'history.replaceState({}, "", "/");</script>')),
        "/a": (200, "text/html", _page("A", "<p>a</p>")),
        "/spa-route": (200, "text/html", _page("Route", "<p>route</p>")),
        "/only-in-sitemap": (200, "text/html", _page("Hidden", "<p>hidden</p>")),
        "/sitemap.xml": (200, "application/xml", lambda h: '<urlset><url><loc>http://' + h.headers["Host"]
                                                           + '/only-in-sitemap</loc></url></urlset>')})
    try:
        monkeypatch.setattr(settings, "max_interactions_per_page", 0)
        monkeypatch.setattr(settings, "mobile_check", False)
        out = discovery_agent({"url": url + "/", "run_dir": str(tmp_path), "site_key": "s", "log": []})
    finally:
        srv.shutdown()
    by = {urlparse(p["url"]).path or "/": p.get("found_by") for p in out["app_map"]}
    assert by.get("/a") == "link" and by.get("/only-in-sitemap") == "sitemap", by
    assert by.get("/spa-route") in ("history", "network"), by
    assert out["crawl"]["found_by"]["sitemap"] == 1


def test_sitemap_decodes_xml_escaped_query_parameters(tmp_path, monkeypatch):
    from backend.agents.discovery import discovery_agent
    def sitemap(h):
        return ('<urlset><url><loc>http://' + h.headers["Host"]
                + '/filtered?category=fruit&amp;sort=price</loc></url></urlset>')
    srv, url = _serve({"/": (200, "text/html", _page("Home", "<p>Home</p>")),
                       "/filtered": (200, "text/html", _page("Filtered", "<p>Fruit sorted by price</p>")),
                       "/sitemap.xml": (200, "application/xml", sitemap)})
    try:
        monkeypatch.setattr(settings, "max_interactions_per_page", 0)
        monkeypatch.setattr(settings, "mobile_check", False)
        out = discovery_agent({"url": url + "/", "run_dir": str(tmp_path), "site_key": "s", "log": []})
    finally:
        srv.shutdown()
    page = next(p for p in out["app_map"] if urlparse(p["url"]).path == "/filtered")
    assert page.get("found_by") == "sitemap"
    assert urlparse(page["url"]).query == "category=fruit&sort=price"


def test_phone_width_finds_phone_only_controls_and_layout_problems(tmp_path, monkeypatch):
    from backend.agents.discovery import discovery_agent
    css = ("<style>#burger{display:none} @media (max-width:600px){#burger{display:block}}"
           " .wide{width:900px;height:20px;background:#ccc}</style>")
    srv, url = _serve({"/": (200, "text/html", _page("Home", '<button id="burger" onclick="document.getElementById(\'m\')'
                                                              '.hidden=false">Menu</button><nav id="m" hidden><a href="/x">X'
                                                              '</a></nav><div class="wide"></div>', css))})
    try:
        monkeypatch.setattr(settings, "max_interactions_per_page", 0)
        monkeypatch.setattr(settings, "crawl_scope", "page")
        out = discovery_agent({"url": url + "/", "run_dir": str(tmp_path), "site_key": "s", "log": []})
    finally:
        srv.shutdown()
    page = out["app_map"][0]
    assert [b["selector"] for b in page.get("mobile_only", [])] == ["#burger"], page.get("mobile_only")
    assert any(i["type"] == "layout" and "horizontal scroll" in i["detail"] for i in out["crawl_issues"])


def test_a_lower_role_is_refused_the_admin_page(tmp_path, monkeypatch):
    from backend.agents.discovery import discovery_agent
    from backend.roles import role_cases
    login = _page("Log in", '<form method="post" action="/login"><input type="email" name="email" id="email">'
                             '<input type="password" name="password" id="password"><button>Log in</button></form>')

    def who(h):
        return next((c.split("=")[1] for c in (h.headers.get("Cookie") or "").split("; ") if c.startswith("who=")), "")
    srv, url = _serve({
        "/": (200, "text/html", _page("Home", '<a href="/login">Log in</a>')),
        "/login": (200, "text/html", login),
        "/dashboard": (200, "text/html", lambda h: _page("Dashboard", '<a href="/admin">Admin</a> <a href="/logout">Log out'
                                                                        '</a>') if who(h) else login),
        "/admin": (200, "text/html", lambda h: _page("Admin", "<p>Admin area</p><a href='/logout'>Log out</a>")
                   if who(h) == "admin" else _page("Forbidden", "<p>Access denied</p>"))})
    try:
        monkeypatch.setattr(settings, "max_interactions_per_page", 0)
        monkeypatch.setattr(settings, "mobile_check", False)
        monkeypatch.setattr(settings, "test_accounts", [{"role": "admin", "username": "admin@x.test", "password": "Pass#123"},
                                                        {"role": "viewer", "username": "viewer@x.test", "password": "Pass#123"}])
        monkeypatch.setattr(settings, "test_username", "admin@x.test")
        monkeypatch.setattr(settings, "test_password", "Pass#123")
        out = discovery_agent({"url": url + "/", "run_dir": str(tmp_path), "site_key": "s", "log": []})
    finally:
        srv.shutdown()
    roles = out["roles"]
    assert roles["main"] == "admin"
    viewer = roles["roles"]["viewer"]
    assert viewer["login"] == "success"
    admin_page = next(v for u, v in viewer["pages"].items() if u.endswith("/admin"))
    assert admin_page["access"] == "denied", viewer["pages"]
    titles = [c["title"] for c in role_cases(out)]
    assert "Role 'viewer' can not open /admin" in titles, titles
    assert "Pass#123" not in (tmp_path / "roles.json").read_text(encoding="utf-8")


def test_javascript_coverage_ranges():
    from backend.jscov import covered_ranges
    # the whole script ran once, an inner block (10-20) never ran, a function inside it (12-15) did
    funcs = [{"ranges": [{"startOffset": 0, "endOffset": 40, "count": 1}, {"startOffset": 10, "endOffset": 20, "count": 0}]},
             {"ranges": [{"startOffset": 12, "endOffset": 15, "count": 2}]}]
    assert covered_ranges(funcs) == (40, [[0, 10], [12, 15], [20, 40]])


def test_new_kinds_of_pages_first_and_polite_speed(monkeypatch):
    from backend.agents.discovery import _Frontier, _mode, _Pace, _parent_path
    q = _Frontier(("a", 0, True, False))
    q.append_later(("product-2", 1, True, False))
    q.append(("contact", 1, True, False))
    q.append(("app", 1, True, True))
    assert [q.popleft()[0] for _ in range(4)] == ["app", "a", "contact", "product-2"]  # (logged in, new, known)
    assert _parent_path("https://s.test/products/red-oak-lamp") == "/products" and _parent_path("https://s.test/a") == ""
    p = _Pace(10, active=True)
    assert p.gap == pytest.approx(0.1) and _Pace(10, active=False).gap == 0
    monkeypatch.setattr(settings, "section_path", "/electronics")
    assert _mode("https://shop.test/") == ("section", "/electronics")


def test_reports_of_several_runs_are_merged(tmp_path):
    from backend.merge import merge_runs
    for name, verdict, pages in (("run_a", "Ready", 10), ("run_b", "Not Ready", 7)):
        d = tmp_path / name
        d.mkdir()
        (d / "summary.json").write_text(json.dumps({"verdict": verdict, "pages": pages, "reasons": ["x"],
                                                    "coverage_card": {"pages": {"found": pages, "verified": 2},
                                                                      "features": {"found": 5}, "items": [],
                                                                      "limits_hit": []}}), encoding="utf-8")
    out = merge_runs([tmp_path / "run_a", tmp_path / "run_b"], tmp_path)
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["verdict"] == "Not Ready" and s["coverage_card"]["pages"] == {"found": 17, "verified": 4}
    assert (out / "report.html").exists()
