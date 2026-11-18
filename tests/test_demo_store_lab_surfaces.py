"""Gate A: DemoStore /lab exposes iframe + open shadow for surface inventory."""
from urllib.request import urlopen

from tests.demo_store import DemoStore


def test_demo_store_lab_page_embeds_iframe_and_open_shadow():
    store = DemoStore().start()
    try:
        html = urlopen(store.url + "/lab", timeout=5).read().decode("utf-8")
    finally:
        store.stop()
    assert 'iframe title="About frame"' in html or "iframe title='About frame'" in html or "<iframe" in html
    assert "attachShadow({mode: 'open'})" in html or 'attachShadow({mode: "open"})' in html
    assert "open-box" in html
