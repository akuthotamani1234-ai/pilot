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
