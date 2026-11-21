"""Discovery records the website's own API calls (method, path pattern, status), never their contents."""
import http.server
import json
import threading

from backend.api_inventory import ApiInventory, path_pattern
from backend.config import settings


class _Req:
    def __init__(self, kind, method="GET"):
        self.resource_type, self.method = kind, method


class _Resp:
    def __init__(self, url, status=200, kind="xhr", method="GET", ctype="application/json"):
        self.url, self.status, self.request, self.headers = url, status, _Req(kind, method), {"content-type": ctype}


def test_ids_become_patterns_and_only_metadata_is_kept():
    assert path_pattern("/api/v2/pim/employees/7") == "/api/v2/pim/employees/{id}"
    assert path_pattern("/api/u/3f2b1c9e-1d2a-4c3b-9e8f-0a1b2c3d4e5f/x") == "/api/u/{id}/x"
    inv = ApiInventory({"shop.test"})
    inv.observe(_Resp("https://shop.test/api/items/1?token=SECRET123&page=2"), "https://shop.test/list")
    inv.observe(_Resp("https://shop.test/api/items/2?page=3", status=404), "https://shop.test/list")
    inv.observe(_Resp("https://shop.test/api/items", method="POST"), "https://shop.test/new")
    inv.observe(_Resp("https://shop.test/app.js", kind="script"))  # not an API call
    inv.observe(_Resp("https://tracker.example/collect"))          # another host
    summary = inv.summary()
    assert summary["endpoints"] == 2 and summary["calls"] == 3 and summary["with_errors"] == 1
    get = next(r for r in summary["endpoints_list"] if r["method"] == "GET")
    assert get["path"] == "/api/items/{id}" and get["query_keys"] == ["page", "token"]
    assert get["statuses"] == {"200": 1, "404": 1} and get["pages"] == ["/list"]
    assert "SECRET123" not in json.dumps(summary)


def test_discovery_writes_the_api_inventory(tmp_path, monkeypatch):
    from backend.agents import discovery
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "max_pages", 2)
    page = ("<title>Items</title><h1>Items</h1><ul id=l></ul><script>"
            "fetch('/api/items/42?session=abc123secret').then(r=>r.json()).then(d=>{"
            "document.getElementById('l').innerHTML='<li>'+d.name+'</li>'})</script>")

    class Site(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/items/"):
                data, ctype = b'{"name":"Blue Top"}', "application/json"
            else:
                data, ctype = page.encode(), "text/html"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    try:
        discovery.discovery_agent({"url": url, "run_dir": str(tmp_path), "site_key": "t", "log": []})
    finally:
        srv.shutdown()
    inv = json.loads((tmp_path / "api_inventory.json").read_text(encoding="utf-8"))
    paths = {r["path"]: r for r in inv["endpoints_list"]}
    assert "/api/items/{id}" in paths, inv
    assert paths["/api/items/{id}"]["query_keys"] == ["session"]
    assert "abc123secret" not in (tmp_path / "api_inventory.json").read_text(encoding="utf-8")
