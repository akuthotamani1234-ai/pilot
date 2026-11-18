"""Gate A: DemoStore /lab exposes iframe + open shadow for surface inventory."""
import http.client
from urllib.parse import urlparse

from tests.demo_store import DemoStore


def test_demo_store_lab_page_embeds_iframe_and_open_shadow():
    store = DemoStore().start()
    try:
        parsed = urlparse(store.url)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        conn.request("GET", "/lab")
        response = conn.getresponse()
        html = response.read().decode("utf-8")
        conn.close()
    finally:
        store.stop()
    assert response.status == 200
    assert "<iframe" in html
    assert "attachShadow({mode: 'open'})" in html or 'attachShadow({mode: "open"})' in html
    assert "open-box" in html
