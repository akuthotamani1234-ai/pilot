"""AI output must use observed selectors, messages and approved account scope."""

from backend.ai_grounding import account_permission_reason, grounding_problem


def test_rejects_ambiguous_product_text_and_heading_assertions():
    assert grounding_problem('page.locator("text=Phone").click()', [])
    assert grounding_problem('page.get_by_text("Phone").click()', [])
    assert grounding_problem('expect(page.locator("h2")).to_have_text("CART")', [])
    assert grounding_problem('page.get_by_role("link",name="Phone",exact=True).click()', []) is None
    assert grounding_problem('expect(page.locator("h2")).to_have_count(2)', []) is None


def test_message_assertions_require_observation_or_an_owner_requirement():
    code = 'assert any("incorrect" in m for m in _said(page))'
    pages = [{"behaviour": [{"message": "User does not exist"}]}]
    assert grounding_problem(code, pages)
    assert grounding_problem(code, pages, "The wrong-password message must contain incorrect") is None
    assert grounding_problem('assert any("does not exist" in m for m in _said(page))', pages) is None


def test_named_headings_must_exist_in_observed_dom():
    pages = [{"title": "STORE", "headings": [{"text": "Products"}]}]
    assert grounding_problem('expect(page.get_by_role("heading",name="CART")).to_be_visible()', pages)
    assert grounding_problem('expect(page.get_by_role("heading",name="STORE")).to_be_visible()', pages)
    assert (
        grounding_problem('expect(page.get_by_role("heading",name="Products",exact=True)).to_be_visible()', pages)
        is None
    )


def test_account_mutations_and_positive_login_need_approved_scope():
    signup = {"title": "Register a new account", "steps": ["Submit the signup form"], "expected": "Account created"}
    assert account_permission_reason(signup, allow_signup=False, has_account=False)
    assert account_permission_reason(signup, allow_signup=True, has_account=False) == ""
    login = {"title": "Log in", "expected": "The user is logged in successfully"}
    assert account_permission_reason(login, allow_signup=False, has_account=False)
    assert account_permission_reason(login, allow_signup=False, has_account=True) == ""
    assert (
        account_permission_reason(
            {"title": "Login with wrong password is rejected"}, allow_signup=False, has_account=False
        )
        == ""
    )


def test_ai_code_gets_one_grounded_repair_attempt(monkeypatch):
    from backend.agents import script_generator as gen

    calls = []
    bad = 'from playwright.sync_api import expect\n\ndef test_ai_flow_1(page):\n    page.goto("https://fixture.test")\n    expect(page.locator("h1")).to_have_text("STORE")\n'
    good = 'from playwright.sync_api import expect\n\ndef test_ai_flow_1(page):\n    page.goto("https://fixture.test")\n    expect(page).to_have_title("STORE")\n'

    def ask(prompt, **kwargs):
        calls.append(prompt)
        return bad if len(calls) == 1 else good

    monkeypatch.setattr(gen, "ask_llm", ask)
    page = {
        "slug": "home",
        "url": "https://fixture.test",
        "title": "STORE",
        "buttons": [],
        "inputs": [],
        "forms": [],
        "links": [],
        "headings": [],
    }
    flow = {
        "id": "ai_flow_1",
        "title": "Check the tab title",
        "guest": True,
        "pages": ["home"],
        "test_data": "",
        "steps": ["Open the page"],
        "expected": "The document title is STORE",
    }
    code = gen._llm_flows([flow], {"home": page})
    assert "to_have_title" in code
    assert len(calls) == 2 and "OBSERVED PAGES" in calls[1]
