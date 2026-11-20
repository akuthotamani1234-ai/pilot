"""Paginated row-select learned cases prefer search over brittle Next/Prev openers."""
import pytest
from playwright.sync_api import sync_playwright

from backend.agents.test_design import learned_cases
from backend.navigation import open_path


@pytest.fixture()
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        pg = context.new_page()
        yield pg
        context.close()
        browser.close()


def _users_page():
    return {
        "slug": "users",
        "url": "http://fixture.test/users",
        "title": "Users",
        "page_type": "content",
        "inputs": [
            {"selector": "#user-search", "type": "search", "name": "Search users", "label": "Search users"},
            {"selector": 'input[aria-label="Select Tomas Smith"]', "type": "checkbox",
             "name": "Select Tomas Smith", "revealed_by": "#next"},
        ],
        "buttons": [
            {"selector": "#next", "text": "Next"},
            {"selector": "#prev", "text": "Previous"},
        ],
        "behaviour": [
            {
                "selector": 'input[aria-label="Select Tomas Smith"]',
                "control": "Select Tomas Smith",
                "action": "tick",
                "effect": "value",
                "revealed_by": "#next",
                "revealed_by_name": "Next",
                "risk": "safe",
                "tone": "ok",
            }
        ],
    }


def test_learned_row_select_uses_search_instead_of_next():
    cases = learned_cases([_users_page()])
    assert cases, "expected a learned case for Select Tomas Smith"
    spec = cases[0]["spec"]
    assert spec["openers"] == [{
        "selector": "#user-search",
        "action": "fill",
        "value": "Tomas Smith",
        "name": "Search users",
    }]
    assert "Search for 'Tomas Smith'" in cases[0]["steps"]
    assert not any("Next" in s for s in cases[0]["steps"])


def test_learned_row_select_uses_search_instead_of_page_size():
    page = _users_page()
    page["inputs"][1]["revealed_by"] = "#page-size"
    page["behaviour"][0]["revealed_by"] = "#page-size"
    page["inputs"].append({
        "selector": "#page-size", "type": "select-one", "name": "Rows per page", "label": "Rows per page",
        "options": [{"value": "25", "text": "25"}],
    })
    cases = learned_cases([page])
    assert cases[0]["spec"]["openers"][0]["selector"] == "#user-search"
    assert cases[0]["spec"]["openers"][0]["value"] == "Tomas Smith"


def test_learned_row_select_skipped_without_search_when_pagerish():
    page = _users_page()
    page["inputs"] = [i for i in page["inputs"] if i["selector"] != "#user-search"]
    assert learned_cases([page]) == []


def test_open_path_fill_reveals_target(page):
    page.set_content(
        """
        <input id="user-search" type="search">
        <div id="rows"></div>
        <script>
          const rows = document.getElementById('rows');
          const draw = (term) => {
            rows.innerHTML = '';
            if ((term || '').toLowerCase().includes('tomas')) {
              const cb = document.createElement('input');
              cb.type = 'checkbox';
              cb.setAttribute('aria-label', 'Select Tomas Smith');
              rows.appendChild(cb);
            }
          };
          document.getElementById('user-search').oninput = e => draw(e.target.value);
        </script>
        """
    )
    target = 'input[aria-label="Select Tomas Smith"]'
    assert page.locator(target).count() == 0
    open_path(
        page,
        [{"selector": "#user-search", "action": "fill", "value": "Tomas Smith", "name": "Search users"}],
        target,
    )
    assert page.locator(target).count() == 1
