"""Prepared component-inventory and nested-navigation checks; execution is deferred."""

import time

from playwright.sync_api import sync_playwright

from backend.agents.discovery import EXTRACT_JS
from backend.observe import Explorer
from backend.page_inventory import DOM_COMPONENTS_JS, merge_snapshots, save_inventory
from tests.qa_contract_fixture import ContractFixture


def test_dom_inventory_identifies_hidden_components_and_omits_input_contents():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content("""<nav aria-label="Dashboard"><button id="menu" aria-controls="submenu" aria-expanded="false">Menu</button>
        <div id="submenu" role="menu" hidden><a role="menuitem" href="/reports">Reports</a></div></nav>
        <label for="password">Password</label><input id="password" type="password" value="never-copy-this">
        <select id="filter"><option>All</option><option>Active</option></select>
        <table id="grid"><tr><th>Name</th></tr><tr><td>Example</td></tr></table>
        <script>const host=document.body.appendChild(document.createElement('qa-widget'));host.attachShadow({mode:'open'}).innerHTML='<button id="inside">Inner control</button>';</script>""")
        data = page.evaluate(DOM_COMPONENTS_JS)
        rows = {row["selector"]: row for row in data["components"]}
        assert rows["#password"]["kind"] == "password_input"
        assert rows["#submenu"]["visible"] is False
        assert rows["#filter"]["options"] == ["All", "Active"]
        assert rows["#grid"]["column_names"] == ["Name"]
        assert any(row["name"] == "Inner control" and row["shadow"] for row in rows.values())
        assert "never-copy-this" not in str(data)
        browser.close()


def test_component_states_preserve_hidden_visible_and_dropdown_history(tmp_path):
    entry = {"url": "https://example.test", "slug": "home"}
    merge_snapshots(entry, [{"components": [{"selector": "#menu", "kind": "dropdown", "name": "Menu", "visible": False, "options": ["A"]}]}])
    merge_snapshots(entry, [{"components": [{"selector": "#menu", "kind": "dropdown", "name": "Menu", "visible": True, "options": ["A", "B"]}]}], revealed_by="#open")
    row = entry["component_inventory"]["components"][0]
    assert row["seen_visible"] is True and row["discovery_status"] == "observed"
    assert row["observed_options"] == ["A", "B"]
    assert row["revealed_by"] == ["#open"]
    assert len(entry["component_inventory"]["states"]) == 2
    result = save_inventory(tmp_path, [entry])
    assert result["pages"][0]["components"][0]["test_status"] == "not_tested"
    assert (tmp_path / "components.html").is_file()


def test_a_page_inventory_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = b"tenant-b-only-inventory"
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_bytes(secret)
    (other / "components.json").write_bytes(secret)
    (other / "components.html").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    page = {"url": "https://shop.test", "title": "Shop", "slug": "shop", "component_inventory": {
        "components": [{"selector": "#buy", "kind": "button", "name": "Buy", "discovery_status": "observed"}],
    }}
    result = save_inventory(linked / "run", [page])
    assert result["total_components"] == 1
    assert (other / "keep.txt").read_bytes() == secret
    assert (other / "components.json").read_bytes() == secret
    assert (other / "components.html").read_bytes() == secret
    assert not (other / "run").exists()

    real = tmp_path / "real"
    real.mkdir()
    saved = save_inventory(real, [page])
    assert saved["total_components"] == 1
    text = (real / "components.json").read_text(encoding="utf-8")
    assert "#buy" in text and secret.decode() not in text
    assert secret.decode() not in (real / "components.html").read_text(encoding="utf-8")
    assert (other / "keep.txt").read_bytes() == secret


def test_nested_opener_replay_reaches_the_grandchild_control(tmp_path):
    with ContractFixture(tmp_path / "fixture.sqlite") as fixture, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(fixture.url)
        page.set_content("""<button id="root" onclick="document.getElementById('child').hidden=false">Resources</button>
        <button id="child" hidden onclick="document.getElementById('leaf').hidden=false">More resources</button>
        <button id="leaf" hidden onclick="document.getElementById('status').textContent='Leaf reached'">Open details</button>
        <p id="status" role="status">Ready</p>""")
        entry = page.evaluate(EXTRACT_JS)
        entry.update(url=page.url)
        explorer = Explorer(EXTRACT_JS, lambda *_args: None, time.time() + 30)
        explorer._untouched = page.url
        root = {"selector": "#root", "name": "Resources", "text": "Resources", "action": "click", "kind": "button", "revealed_by": None}
        child = {"selector": "#child", "name": "More resources", "text": "More resources", "action": "click", "kind": "button", "revealed_by": "#root"}
        leaf = {"selector": "#leaf", "name": "Open details", "text": "Open details", "action": "click", "kind": "button", "revealed_by": "#child"}
        explorer.decided[("__opener__", "#root")] = root
        result = explorer._try(page, page.url, entry, leaf, child, "safe")
        assert not result.get("error") and not result.get("blocked"), result
        assert page.locator("#status").inner_text() == "Leaf reached"
        assert explorer._last_replay_count == 2
        browser.close()
