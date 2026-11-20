"""Standalone open-shadow text boxes get textbox control cases (AdminPortal Nickname)."""
from backend.agents.script_generator import CONTROL_TESTS, _textbox_test
from backend.agents.test_design import control_cases


def test_shadow_nickname_gets_textbox_case():
    page = {
        "url": "http://127.0.0.1/widgets",
        "title": "Widgets",
        "slug": "widgets",
        "auth": True,
        "buttons": [],
        "links": [],
        "forms": [],
        "inputs": [{
            "id": "nickname",
            "label": "Nickname",
            "type": "text",
            "tag": "input",
            "selector": "#nickname",
            "shadow_path": ["user-card#profile-card"],
            "disabled": False,
            "data_first": True,
        }],
    }
    cases = control_cases(page)
    textbox = [c for c in cases if c.get("kind") == "textbox"]
    assert textbox, cases
    assert any("Nickname" in (c.get("title") or "") for c in textbox)
    assert "textbox" in CONTROL_TESTS
    lines = "\n".join(_textbox_test("textbox_nickname", textbox[0]["title"], textbox[0]))
    assert "QA Shadow" in lines
    assert "#nickname" in lines
