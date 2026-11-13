"""P3–P5 OrangeHRM web QA hardening (reusable, offline fixtures).

P3: field-aware values + custom-control fallback recording (force/DOM never proves user actionability).
P4: unsubmitted Save/input checks are interaction/smoke — no business-verified credit.
P5: AI proposals with absent records/selectors are unsupported/exploratory, not product defects.
"""
from backend.ai_grounding import grounding_problem, invented_record_problem, unsupported_reason
from backend.assert_strength import counts_as_business_proof, verification_credit
from backend.forms import record_control_fallback, set_choice
from backend.qa_contracts import business_outcome_requires_oracle, write_authorization_gap
from backend.registry import record_outcomes
from backend.testdata import field_kind, valid_value, values


def test_field_kind_infers_email_phone_numeric_date_from_labels_and_constraints():
    assert field_kind({"type": "text", "label": "Work Email"}) == "email"
    assert field_kind({"type": "text", "label": "Mobile", "inputmode": "tel"}) == "phone"
    assert field_kind({"type": "number", "label": "Age", "min": "18", "max": "65"}) == "age"
    assert field_kind({"type": "date", "label": "Date of Birth"}) == "date"
    phone = valid_value({"type": "tel", "label": "Phone"}, tag="qa-run-9")
    assert phone.startswith("+") or phone.isdigit() or " " in phone
    mail = valid_value({"type": "email", "label": "E-mail"}, tag="qa-run-9")
    assert mail.endswith("@example.com") and "qa" in mail
    birth = valid_value({"type": "date", "label": "Date of Birth"})
    assert birth < "2005-01-01"
    future = valid_value({"type": "date", "label": "Start Date"})
    assert future >= "2020-01-01"
    patterned = values({"type": "text", "label": "Code", "pattern": r"\d{5}"})
    assert any(v["expect"] == "accept" and v["value"].isdigit() for v in patterned)


def test_custom_control_fallback_is_recorded_and_does_not_prove_actionability():
    rec = record_control_fallback("force check on styled control", how="force")
    assert rec["fallback"] is True
    assert rec["proves_user_actionability"] is False
    assert rec["how"] == "force"

    class FakeEl:
        def __init__(self):
            self._checked = False
            self.calls = []

        def check(self, timeout=3000, force=False):
            self.calls.append(("check", force))
            if not force:
                raise RuntimeError("not actionable")
            self._checked = True

        def uncheck(self, timeout=3000, force=False):
            self.calls.append(("uncheck", force))
            self._checked = False

        def is_checked(self):
            return self._checked

        def evaluate(self, *_a, **_k):
            self.calls.append(("evaluate",))
            self._checked = True

    log = []
    el = FakeEl()
    out = set_choice(el, checked=True, log=log)
    assert out["fallback"] is True
    assert out["proves_user_actionability"] is False
    assert log and log[0]["fallback"] is True
    assert ("check", True) in el.calls  # force path used after normal check failed


def test_unsubmitted_save_form_case_is_interaction_not_business_verified():
    case = {
        "id": "journey_1",
        "journey": "form",
        "title": "Fill the whole 'Save' form like a user (4 boxes) - not sent",
        "type": "end-to-end",
        "verification": "interaction",
        "steps": ["Open page", "Type values", "Do NOT send the form"],
        "expected": "Every box accepts a normal value",
    }
    assert verification_credit(case) == "interaction"
    assert not counts_as_business_proof(case, "strong")
    assert "Unsubmitted" in business_outcome_requires_oracle(case) or "input-only" in business_outcome_requires_oracle(case)

    reg = {"pages": {}, "features": {
        "F-form": {"id": "F-form", "level": "feature", "kind": "form", "name": "Save", "page": "P-1",
                   "pages": ["home"], "status": "inspected", "why": "",
                   "tests": [{"tc_id": "TC-form", "how": "uses"}], "outcomes": {}}}}
    cases = [{"tc_id": "TC-form", "title": case["title"], "execution_status": "Passed",
              "verification": "interaction", "journey": "form",
              "files": ["test_journeys.py"], "tests": ["test_journey_1"]}]
    results = [{"nodeid": "test_journeys.py::test_journey_1", "file": "test_journeys.py",
                "test": "test_journey_1", "outcome": "passed", "checks": 4}]
    # Strong retained-value asserts still do not grant business-verified credit.
    record_outcomes(reg, cases, {}, results, {"test_journeys.py::test_journey_1": "strong"})
    assert reg["features"]["F-form"]["status"] == "smoke"
    assert "interaction" in (reg["features"]["F-form"].get("why") or "").lower() or \
        "input" in (reg["features"]["F-form"].get("why") or "").lower()


def test_writes_never_auto_enabled_from_environment_test_alone():
    gap = write_authorization_gap(environment="test", writes_ok=False, action_class="write")
    assert gap and "staging" in gap.lower()
    assert "never enables writes" in gap.lower() or "missing" in gap.lower()
    assert write_authorization_gap(environment="staging", writes_ok=True, action_class="write") == ""
    assert "delete" in write_authorization_gap(environment="staging", writes_ok=True,
                                               allow_actions=[], action_class="delete").lower()


def test_search_filter_sort_cases_keep_business_credit_when_outcomes_defined():
    search = {"id": "search_finds_item", "kind": "feature", "feature_kind": "search",
              "verification": "business", "type": "positive"}
    sort = {"id": "sort_name", "kind": "sort", "verification": "business"}
    assert verification_credit(search) == "business"
    assert verification_credit(sort) == "business"
    assert counts_as_business_proof(search, "strong")
    assert business_outcome_requires_oracle(search) == ""


def test_unknown_case_defaults_to_interaction_not_business():
    assert verification_credit(None) == "interaction"
    assert verification_credit({"id": "mystery", "title": "Something vague"}) == "interaction"
    assert verification_credit({"id": "site_input_values", "title": "Input boxes"}) == "business"


def test_ai_proposal_with_absent_record_or_selector_is_unsupported_not_product_defect():
    pages = [{"title": "Users", "headings": [{"text": "System Users"}], "buttons": [
                {"selector": "button[type=submit]", "text": "Search"}],
              "inputs": [{"selector": "#username", "label": "Username"}],
              "forms": [], "links": [], "behaviour": [], "itemNames": ["Alice Admin"]}]
    people = invented_record_problem("Open the record for John Doe and click Edit", pages)
    assert people and "John Doe" in people and "not a product defect" in people.lower()

    bad = (
        'from playwright.sync_api import expect\n'
        'def test_ai_flow_1(page):\n'
        '    page.goto("https://fixture.test")\n'
        '    page.get_by_text("John Doe", exact=True).click()\n'
        '    expect(page.get_by_role("heading", name="Missing Heading")).to_be_visible()\n'
    )
    problem = grounding_problem(bad, pages)
    assert problem
    reason = unsupported_reason(problem)
    assert "Unsupported" in reason or "unsupported" in reason.lower()

    invented_css = (
        'def test_ai_flow_2(page):\n'
        '    page.locator("#never-observed-widget-xyz").click()\n'
    )
    css_problem = grounding_problem(invented_css, pages)
    assert css_problem and "not observed" in css_problem.lower()
    assert "product defect" in reason.lower()

    # Observed person is allowed; role-based table without native <table> is fine.
    ok_pages = [{"title": "Users", "headings": [{"text": "System Users"}],
                 "itemNames": ["John Doe"], "tables": [{"selector": "[role=table]", "native": False}],
                 "buttons": [], "inputs": [], "forms": [], "links": [], "behaviour": []}]
    assert invented_record_problem("Open John Doe", ok_pages) is None
    assert grounding_problem(
        'page.get_by_role("row", name="John Doe", exact=True).click()', ok_pages
    ) is None
    toast = grounding_problem('page.locator(".oxd-toast").click()', pages)
    assert toast and "severity" in toast.lower()


def test_grounding_still_rejects_ambiguous_product_text_and_heading_assertions():
    """Existing ai grounding regressions from test_ai_grounding.py stay true here too."""
    assert grounding_problem('page.locator("text=Phone").click()', [])
    assert grounding_problem('page.get_by_text("Phone").click()', [])
    assert grounding_problem('expect(page.locator("h2")).to_have_text("CART")', [])
    pages = [{"title": "STORE", "headings": [{"text": "Products"}]}]
    assert grounding_problem('expect(page.get_by_role("heading", name="CART")).to_be_visible()', pages)
    assert (
        grounding_problem('expect(page.get_by_role("heading", name="Products", exact=True)).to_be_visible()', pages)
        is None
    )
