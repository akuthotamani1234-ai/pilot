"""Focused setup and rendered-page regressions: no external websites or model calls."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend.page_status import RENDER_EVIDENCE_JS, exploration_status, page_testable, rendered_application


def test_rendered_ui_preserves_http_failure():
    page={"status":404,"title":"Catalog"}
    evidence={"application_mount":True,"visible_controls":8,"text_length":200,"error_document":False}
    assert rendered_application(page,evidence)
    page["rendered_application"]=True
    assert page_testable(page) and page["status"]==404

@pytest.mark.parametrize("status",[401,403,405,429,500,503])
def test_real_failures_are_not_overridden(status):
    page={"status":status,"title":"Catalog","rendered_application":True}
    assert not rendered_application(page,{"application_mount":True,"visible_controls":20,"text_length":1000})
    assert not page_testable(page)

def test_error_document_is_not_a_working_application():
    assert not rendered_application({"status":404,"title":"404 Not Found"},
        {"application_mount":True,"visible_controls":8,"text_length":200,"error_document":True})
    assert not page_testable({"status":404})

def test_partial_and_exhausted_frontiers_are_distinct():
    assert exploration_status({"visited":7})["status"]=="routes_processed"
    assert "not proof" in exploration_status({})["limitation"]
    for crawl in [{"not_visited_count":2},{"time_limit_reached":True},{"skipped":[{"reason":"max depth reached"}]}]:
        assert exploration_status(crawl)["status"]=="partial"

CARD_HTML="""<!doctype html><title>Public catalog</title><div id="root"><h1>Products</h1>
<select aria-label="Sort products"><option value="az">Name A to Z</option><option value="lohi">Price low to high</option></select>
<div class="catalog-grid">"""+ "".join(
f"""<article class="catalog-card"><img alt="Product {i}" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20'%3E%3C/svg%3E">
<a href="#" role="button" onclick="event.preventDefault();location.href='/item/{i}'"><span class="item-name">Product {i}</span></a>
<span class="price">&#36;{i}.00</span><button>Add to cart</button></article>""" for i in range(1,4)
)+"</div><p>A complete product catalog with client-side controls, names, prices and product navigation.</p></div><script>window.catalogReady=true;</script>"

def test_client_cards_are_read_without_inventing_destinations():
    from playwright.sync_api import sync_playwright

    from backend.agents.discovery import EXTRACT_JS, ITEMS_JS
    from backend.features import page_type
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page()
        page.set_content(CARD_HTML)
        data=page.evaluate(EXTRACT_JS)
        assert data["itemLinks"]["count"]==3
        assert data["itemLinks"]["links"]==[]
        assert data["itemLinks"]["client_navigation"]
        assert page_type(dict(data,url="https://example.test/catalog",auth=True))=="listing"
        items=page.evaluate(ITEMS_JS,{"mark":True})
        assert items["names"]==["Product 1","Product 2","Product 3"]
        assert page.locator("[data-qa-item]").count()==3
        assert rendered_application({"status":404,"title":"Public catalog"},page.evaluate(RENDER_EVIDENCE_JS))
        browser.close()

def test_crawl_keeps_rendered_404_and_reports_real_404(tmp_path,monkeypatch):
    from backend.agents.discovery import discovery_agent
    from backend.config import settings
    class Site(BaseHTTPRequestHandler):
        def do_GET(self):
            pages={"/":(200,'<title>Home</title><h1>Home</h1><a href="/catalog">Catalog</a><a href="/missing">Missing</a>'),
                   "/catalog":(404,CARD_HTML),"/missing":(404,"<title>404 Not Found</title><h1>Page not found</h1>")}
            code,html=pages.get(self.path.split("?")[0],(404,"<h1>Not found</h1>"))
            body=html.encode()
            self.send_response(code)
            self.send_header("Content-Type","text/html")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self,*args):
            pass
    site=ThreadingHTTPServer(("127.0.0.1",0),Site)
    threading.Thread(target=site.serve_forever,daemon=True).start()
    for name,value in {"max_pages":0,"max_depth":0,"crawl_scope":"site","max_interactions_per_page":0,
        "mobile_check":False,"visual_check":False,"llm_provider":"none","auto_register":False,
        "login_enabled":False,"max_requests_per_sec":0}.items():
        monkeypatch.setattr(settings,name,value)
    try:
        out=discovery_agent({"url":f"http://127.0.0.1:{site.server_address[1]}","run_dir":str(tmp_path),"site_key":"rendered","log":[]})
    finally:
        site.shutdown()
        site.server_close()
    catalog=next(p for p in out["app_map"] if p["url"].endswith("/catalog"))
    assert catalog["status"]==404 and page_testable(catalog)
    assert catalog["page_type"]=="listing"
    assert not any(i["type"]=="page_failed" and i["url"].endswith("/catalog") for i in out["crawl_issues"])
    assert any(i["type"]=="http_status" and i["url"].endswith("/catalog") for i in out["crawl_issues"])
    assert any(i["type"]=="page_failed" and i["url"].endswith("/missing") for i in out["crawl_issues"])
    # This fixture disables interactions, so reachable UI states remain unexamined.
    assert out["crawl"]["exploration"]["status"] == "partial"
    assert out["crawl"]["exploration"]["actions_limited"]
    assert not out["crawl"]["exploration"]["within_selected_scope"]

def test_account_modes_are_checked_before_network():
    from fastapi.testclient import TestClient

    from backend import server
    with TestClient(server.app,base_url="http://127.0.0.1") as client:
        for extra,expected in [({"auth_mode":"existing"},"Existing account"),
                               ({"auth_mode":"signup","allow_signup":False},"permission")]:
            response=client.post("/api/runs",headers={"X-Agentic-QA":"1"},
                json={"source":"https://example.test","authorized":True,"llm_provider":"none",**extra})
            assert response.status_code==400 and expected in response.json()["detail"]

def test_homepage_and_assets_cannot_stay_on_a_stale_ui():
    from fastapi.testclient import TestClient

    from backend import server
    with TestClient(server.app,base_url="http://127.0.0.1") as client:
        response=client.get("/")
        assert "no-store" in response.headers["cache-control"]
        for name in ("chat.js","workflow.js","chat.css","studio.css"):
            assert "/static/"+name+"?v=" in response.text

def test_empty_aria_cart_is_a_control_and_count_changes_are_not_new_controls():
    import time

    from playwright.sync_api import sync_playwright

    from backend.agents.discovery import EXTRACT_JS
    from backend.observe import Explorer
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page()
        page.set_content('<a id="cart" role="button" aria-label="Cart, empty" style="display:block;width:30px;height:30px"></a><button id="add">Add to cart</button><a name="top"></a>')
        entry=page.evaluate(EXTRACT_JS)
        assert any(b["selector"]=="#cart" and b["accname"]=="Cart, empty" for b in entry["buttons"])
        page.locator("#cart").evaluate("e=>e.setAttribute('aria-label','Cart, 1 items')")
        explorer=Explorer(EXTRACT_JS,lambda *a:None,time.time()+10)
        assert not any(x["selector"]=="#cart" for x in explorer._revealed(page,entry,{"selector":"#add","name":"Add to cart"}))
        browser.close()

def test_visible_target_does_not_replay_an_obsolete_opener():
    import time

    from playwright.sync_api import sync_playwright

    from backend.agents.discovery import EXTRACT_JS
    from backend.observe import Explorer
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page()
        page.route("http://example.test/**",lambda route:route.fulfill(content_type="text/html",body=
            '<button id="target" onclick="document.getElementById(\'result\').textContent=\'Opened\'">Open details</button><p id="result">Closed</p>'))
        page.goto("http://example.test/")
        entry=page.evaluate(EXTRACT_JS)
        explorer=Explorer(EXTRACT_JS,lambda *a:None,time.time()+15)
        explorer._untouched=page.url
        result=explorer._try(page,page.url,entry,
            {"name":"Open details","selector":"#target","action":"click"},
            {"name":"Old opener","selector":"#no-longer-present","action":"click"},"safe")
        assert "error" not in result,result
        assert explorer._last_replay_count==0
        browser.close()
