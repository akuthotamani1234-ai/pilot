"""The two parts of the TestOptim capability list that were missing (Nov 2, 2026):
  7  visual regression - the look of every page compared with its APPROVED look: missing / moved / overlapping elements
     and the changed share of the picture, a person approves a new look, nothing is accepted silently;
  8  integrations - Slack and Jira get only APPLICATION DEFECTS (never a test-script problem), the same problem is never
     sent twice, the token never lands in a file; a deploy script starts a run with the webhook token.
Every server here runs on this PC (no internet, no real Slack / Jira)."""
import base64
import hashlib
import hmac
import http.server
import json
import threading
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from backend.config import settings


def _serve(handler):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


# ------------------------------------------------------------------ 7. visual regression

def test_the_layout_comparison_names_what_changed():
    from backend.visual import compare_layout
    old = {"size": [1366, 1000], "overlaps": [],
           "boxes": [{"k": "h1:Welcome", "b": [100, 50, 400, 40]}, {"k": "button:Buy", "b": [100, 120, 80, 30]},
                     {"k": "a:Home", "b": [10, 10, 50, 20]}, {"k": "h2:Products", "b": [100, 300, 300, 30]},
                     {"k": "a:Product #", "b": [100, 350, 200, 20]}, {"k": "a:Product # #2", "b": [100, 380, 200, 20]},
                     {"k": "img:logo.png", "b": [900, 10, 100, 40]}]}
    new = {"size": [1366, 1400], "overlaps": ["button:Buy | a:Help"],
           "boxes": [{"k": "button:Buy", "b": [100, 120, 80, 30]}, {"k": "a:Home", "b": [10, 10, 50, 20]},
                     {"k": "h2:Products", "b": [100, 700, 300, 30]}, {"k": "a:Product #", "b": [100, 750, 200, 20]},
                     {"k": "a:Product # #2", "b": [100, 780, 200, 20]}, {"k": "img:logo.png", "b": [900, 10, 300, 40]},
                     {"k": "a:Help", "b": [110, 125, 60, 20]}]}
    found = {c["kind"]: [] for c in compare_layout(old, new, 12)}
    for c in compare_layout(old, new, 12):
        found[c["kind"]].append(c["detail"])
    assert found["missing"] == ["1 element(s) of the approved page are gone: h1 'Welcome'"]
    # the 3 elements below the new content moved TOGETHER: one change, not three
    assert "from h2 'Products' on, 3 elements moved together (+0 px across, +400 px down)" in found["moved"]
    assert "img 'logo.png': size 100x40 -> 300x40 px" in found["moved"]
    assert len(found["moved"]) == 2, found["moved"]
    assert found["overlap"] == ["1 new overlap(s): button 'Buy' covers a 'Help'"]
    assert found["height"] == ["the page is +400 px longer (1000 -> 1400 px)"]
    assert compare_layout(old, old, 12) == []  # the same look: nothing


V1 = """<!doctype html><html><head><title>Shop</title></head><body style="margin:0;font:16px sans-serif">
<header style="height:60px;background:#246"><a href="/" style="color:#fff">Home</a></header>
<h1>Welcome to the shop</h1><p>Prices from 10 to 99</p>
<div class="carousel"><h2>Slide {slide}</h2></div>
<h2>Products</h2><a href="/p/1">Blue Top</a> <a href="/p/2">Red Shirt</a>
<button>Add to cart</button></body></html>"""
# the redesign: the welcome heading is gone, a banner pushes everything down, the button now covers a link
V2 = """<!doctype html><html><head><title>Shop</title></head><body style="margin:0;font:16px sans-serif">
<header style="height:60px;background:#246"><a href="/" style="color:#fff">Home</a></header>
<div style="height:300px;background:#fc0">Big sale</div><p>Prices from 10 to 99</p>
<div class="carousel"><h2>Slide {slide}</h2></div>
<h2>Products</h2><a href="/p/1">Blue Top</a> <a href="/p/2">Red Shirt</a>
<button style="position:relative;left:-160px">Add to cart</button></body></html>"""


def _crawl_and_check(tmp_path, monkeypatch, name, html):
    from backend.agents.discovery import discovery_agent
    from backend.visual import keep_new_looks, visual_check_agent
    calls = {"n": 0}

    class Site(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            calls["n"] += 1
            body = html.replace("{slide}", str(calls["n"])) if self.path.split("?")[0] == "/" else ""
            data = body.encode()
            self.send_response(200 if body else 404)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    srv, url = _serve(Site)
    run_dir = tmp_path / name
    run_dir.mkdir()
    (run_dir / "run_args.json").write_text(json.dumps({"site_key": "shop"}), encoding="utf-8")
    try:
        out = discovery_agent({"url": url + "/", "run_dir": str(run_dir), "site_key": "shop", "log": []})
    finally:
        srv.shutdown()
    state = {"app_map": out["app_map"], "run_dir": str(run_dir), "site_key": "shop", "run_id": name, "log": []}
    before = (settings.baseline_dir / "shop" / "visual" / "index.json")
    before = before.read_text(encoding="utf-8") if before.exists() else None
    visual_check_agent(state)
    after = settings.baseline_dir / "shop" / "visual" / "index.json"
    assert (after.read_text(encoding="utf-8") if after.exists() else None) == before  # the check only reads
    keep_new_looks(run_dir, "shop")  # (the run finished: save_baseline)
    return run_dir, json.loads((run_dir / "visual.json").read_text(encoding="utf-8"))


def test_the_look_is_compared_with_the_approved_look_and_a_person_approves_a_new_one(tmp_path, monkeypatch):
    from backend.visual import approve, load_index
    monkeypatch.setattr(settings, "baseline_dir", tmp_path / "baseline")
    monkeypatch.setattr(settings, "crawl_scope", "page")
    monkeypatch.setattr(settings, "max_interactions_per_page", 0)
    monkeypatch.setattr(settings, "visual_check", True)
    _, first = _crawl_and_check(tmp_path, monkeypatch, "run1", V1)
    assert first["first_run"] and first["counts"]["new"] == 1  # the first look is the approved look
    page = load_index("shop")["pages"]["/"]
    assert set(page["widths"]) == {"desktop", "phone"}
    assert not any("Slide" in b["k"] for b in page["widths"]["desktop"]["boxes"])  # (a carousel changes by itself)

    _, same = _crawl_and_check(tmp_path, monkeypatch, "run2", V1)  # (only the carousel's slide changed)
    assert same["counts"] == {"same": 1, "changed": 0, "new": 0, "approved": 0, "compared": 1}, same["pages"]

    run3, changed = _crawl_and_check(tmp_path, monkeypatch, "run3", V2)
    assert changed["counts"]["changed"] == 1
    desk = changed["pages"][0]["widths"]["desktop"]
    kinds = {c["kind"] for c in desk["changes"]}
    assert {"missing", "moved", "overlap", "picture"} <= kinds, desk["changes"]
    assert any("h1 'Welcome to the shop'" in c["detail"] for c in desk["changes"] if c["kind"] == "missing")
    assert (run3 / desk["diff_shot"]).stat().st_size > 0 and (run3 / desk["approved_shot"]).exists()
    assert "phone" in changed["pages"][0]["widths"]
    # nothing is accepted silently: the approved look is still the old one
    assert load_index("shop")["pages"]["/"]["run_id"] == "run1"

    assert approve(run3) == 1
    assert load_index("shop")["pages"]["/"]["run_id"] == "run3"
    _, after = _crawl_and_check(tmp_path, monkeypatch, "run4", V2)
    assert after["counts"]["same"] == 1 and after["counts"]["changed"] == 0, after["pages"]


def test_the_report_and_its_limits_show_the_visual_check(tmp_path):
    from backend.agents.reporter import limits_hit, visual_html
    vis = {"first_run": False, "left_out": 4, "counts": {"same": 1, "changed": 1, "new": 0, "compared": 2},
           "pages": [{"url": "https://shop.test/", "key": "/", "title": "Shop", "status": "changed", "widths": {
               "desktop": {"changes": [{"kind": "missing", "detail": "1 element(s) of the approved page are gone: h1 'X'"}],
                           "percent": 7.5, "shot": "screenshots/01_home.png", "approved_shot": "visual/home_desktop_approved.png",
                           "diff_shot": "visual/home_desktop_diff.png"}}}]}
    (tmp_path / "visual.json").write_text(json.dumps(vis), encoding="utf-8")
    html = visual_html(vis)
    assert "h1 &#x27;X&#x27;" in html and "visual/home_desktop_diff.png" in html and "7.5% of the picture" in html
    assert "visual_limit" in [x["id"] for x in limits_hit({}, tmp_path)]


# ------------------------------------------------------------------ 8. Slack + Jira

class _Fake(http.server.BaseHTTPRequestHandler):
    got: list = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.got.append({"path": self.path, "headers": dict(self.headers), "body": body})
        answer = {"key": f"QA-{len(self.got)}"} if self.path == "/rest/api/2/issue" else {}
        data = json.dumps(answer).encode()
        self.send_response(201 if self.path == "/rest/api/2/issue" else 200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


FAILURES = [
    {"id": 0, "source": "test", "category": "product_defect", "category_name": "Application defect", "severity": "high",
     "confidence": "high", "test": "test_cart_total", "tc_id": "TC-7", "page_url": "https://shop.test/cart",
     "explanation": "The total ignores the quantity.", "error": "AssertionError: total 10 != 30",
     "screenshot": "failure_screenshots/cart.png", "evidence": ["failure_screenshots/cart.png"],
     "next_action": "Fix the website.", "bug": {"title": "Cart total ignores the quantity", "feature": "Cart",
                                                "steps": ["Open /cart", "Set quantity 3"], "expected": "Total 30",
                                                "actual": "Total 10"}},
    {"id": 1, "source": "test", "category": "test_defect", "severity": "high", "confidence": "high",
     "test": "test_broken_locator", "page_url": "https://shop.test/x", "error": "locator not found"},
    {"id": 2, "source": "crawler", "category": "product_defect", "severity": "medium", "confidence": "low",
     "test": "console_error", "page_url": "https://shop.test/y", "error": "JS error"},
]


def test_slack_and_jira_get_only_application_defects_once(tmp_path, monkeypatch):
    from backend.integrations import integrations_agent
    _Fake.got = []
    srv, url = _serve(_Fake)
    monkeypatch.setattr(settings, "baseline_dir", tmp_path / "baseline")
    monkeypatch.setattr(settings, "slack_webhook_url", url + "/slack")
    for k, v in {"jira_url": url, "jira_email": "qa@shop.test", "jira_api_token": "jira-secret-token",
                 "jira_project": "QA"}.items():
        monkeypatch.setattr(settings, k, v)
    run_dir = tmp_path / "run"
    (run_dir / "failure_screenshots").mkdir(parents=True)
    (run_dir / "failure_screenshots" / "cart.png").write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="))
    state = {"url": "https://shop.test/", "run_dir": str(run_dir), "run_id": "run1", "site_key": "shop",
             "verdict": "Not Ready", "failures": FAILURES, "log": []}
    try:
        out = integrations_agent(state)
        again = integrations_agent(dict(state, run_id="run2"))  # the next run finds the same problem
    finally:
        srv.shutdown()
    slack = [g for g in _Fake.got if g["path"] == "/slack"]
    issues = [g for g in _Fake.got if g["path"] == "/rest/api/2/issue"]
    files = [g for g in _Fake.got if g["path"].endswith("/attachments")]
    assert len(slack) == 2  # (a message per run - Slack is a notice, Jira the record)
    text = json.loads(slack[0]["body"])["text"]
    assert "Cart total ignores the quantity" in text and "test_broken_locator" not in text and "Not Ready" in text
    assert len(issues) == 1, [json.loads(i["body"]) for i in issues]  # the 2nd run: already reported, not again
    fields = json.loads(issues[0]["body"])["fields"]
    assert fields["project"] == {"key": "QA"} and fields["summary"] == "[high] Cart total ignores the quantity"
    for part in ("*Steps to reproduce:*\n# Open /cart\n# Set quantity 3", "*Expected:* Total 30", "TC-7",
                 "*Severity:* high", "*Next action:* Fix the website."):
        assert part in fields["description"], part
    assert issues[0]["headers"]["Authorization"].startswith("Basic ")
    assert len(files) == 1 and files[0]["headers"]["X-Atlassian-Token"] == "no-check" and b"cart.png" in files[0]["body"]
    assert out["log"][-1] == "Jira: 1 issue(s) created" and again["log"][-1] == "Jira: 0 issue(s) created, 1 already reported"
    saved = (run_dir / "integrations.json").read_text(encoding="utf-8") + json.dumps(out["log"])
    assert "jira-secret-token" not in saved and "/slack" not in saved


def test_nothing_is_sent_without_settings_or_significant_defects(tmp_path, monkeypatch):
    from backend.integrations import integrations_agent, send_slack
    monkeypatch.setattr(settings, "slack_webhook_url", "")
    monkeypatch.setattr(settings, "jira_url", "")
    assert integrations_agent({"run_dir": str(tmp_path), "failures": FAILURES, "log": ["x"]}) == {"log": ["x"]}
    assert not (tmp_path / "integrations.json").exists()
    monkeypatch.setattr(settings, "slack_webhook_url", "http://hooks.example/abc")  # (not https: refused)
    low = [dict(FAILURES[0], severity="medium")]
    assert send_slack({"run_dir": str(tmp_path), "verdict": "Ready with Risks"}, low)["sent"] is False
    assert "https" in send_slack({"run_dir": str(tmp_path), "verdict": "Not Ready"}, FAILURES)["why"]


# ------------------------------------------------------------------ 8. the webhook

@pytest.fixture
def hook(monkeypatch):
    from backend import server
    started = []
    monkeypatch.setattr(server, "start_run", lambda req: started.append(req) or {"id": len(started)})
    monkeypatch.setattr(settings, "webhook_token", "hook-token-123")
    monkeypatch.setattr(settings, "webhook_test_url", "")
    return TestClient(server.app, base_url="http://127.0.0.1:8000"), started


def test_a_deploy_script_starts_a_run_with_the_webhook_token(hook, monkeypatch):
    client, started = hook
    assert client.post("/api/hooks/run", json={"url": "https://shop.test"}).status_code == 401  # no token
    assert client.post("/api/hooks/run", json={"url": "https://shop.test"},
                       headers={"X-QA-Token": "wrong"}).status_code == 401
    r = client.post("/api/hooks/run", json={"url": "https://shop.test"}, headers={"X-QA-Token": "hook-token-123"})
    assert r.status_code == 200 and r.json()["started"] and started[-1].source == "https://shop.test"
    assert started[-1].authorized
    assert client.post("/api/hooks/run", json={}, headers={"X-QA-Token": "hook-token-123"}).status_code == 400
    # GitHub: a signed 'deployment_status' event tests the deployed address - only a successful deployment
    for state, runs in (("failure", 1), ("success", 2)):
        body = json.dumps({"deployment_status": {"state": state, "environment_url": "https://preview.shop.test"}}).encode()
        sig = "sha256=" + hmac.new(b"hook-token-123", body, hashlib.sha256).hexdigest()
        r = client.post("/api/hooks/run", content=body, headers={"X-GitHub-Event": "deployment_status",
                                                                 "X-Hub-Signature-256": sig})
        assert r.status_code == 200 and len(started) == runs, r.json()
    assert started[-1].source == "https://preview.shop.test"
    assert urlparse(started[-1].source).hostname == "preview.shop.test"
    # other changes still need the UI's own header
    assert client.post("/api/runs", json={"source": "https://shop.test"}).status_code == 403
    monkeypatch.setattr(settings, "webhook_token", "")
    assert client.post("/api/hooks/run", json={"url": "https://shop.test"},
                       headers={"X-QA-Token": "hook-token-123"}).status_code == 404  # off without a token
