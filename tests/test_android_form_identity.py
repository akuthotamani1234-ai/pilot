"""Form screens must remain distinct under a shared native scroll-view shell."""
import time
from types import SimpleNamespace
from xml.sax.saxutils import quoteattr

from backend.android import extract_screen
from backend.android_app import AppSession
from backend.android_design import normalize_screens
from backend.android_interact import EMPTY_PASSWORD, fill, find_form, generated_secrets
from backend.android_runtime import same_screen, screen_key
from backend.qa_contracts import Flow

PACKAGE = "com.example.formfixture"


def screen(kind="products", filled=False, matching_fields=False):
    def node(cls, *, text="", resource="", hint="", password=False, clickable=False, children=""):
        attrs = {"class": cls, "package": PACKAGE, "text": text, "resource-id": resource,
                 "hint": hint, "password": str(password).lower(), "clickable": str(clickable).lower(),
                 "enabled": "true", "displayed": "true", "bounds": "[0,0][400,700]",
                 "scrollable": str(cls.endswith("ScrollView")).lower()}
        return "<node " + " ".join(k + "=" + quoteattr(v) for k, v in attrs.items()) + ">" + children + "</node>"

    body = node("android.widget.TextView", text="Products" if kind == "products" else "Welcome")
    fields = ["Username", "Password"] if kind == "login" or matching_fields else ["Username", "Email", "Password", "Confirm Password"]
    if kind != "products":
        for label in fields:
            body += node("android.widget.EditText", resource=PACKAGE + ":id/" + label.replace(" ", "").lower(),
                         hint=label, password="Password" in label, text="private-test-value" if filled else "")
        body += node("android.widget.Button", text="Log in" if kind == "login" else "Sign up",
                     resource=PACKAGE + ":id/submit", clickable=True)
    xml = "<hierarchy>" + node("android.widget.ScrollView", resource=PACKAGE + ":id/shared_scroll", children=body) + "</hierarchy>"
    return normalize_screens([extract_screen(xml, PACKAGE, "emulator-5554", ".MainActivity")])[0]


def test_login_is_distinct_from_products_with_the_same_scroller():
    products, login = screen(), screen("login")
    assert find_form(login)["kind"] == "login"
    assert not same_screen(login, products)
    assert screen_key(login) != screen_key(products)


def test_signup_and_login_are_distinct_under_the_same_heading():
    login, signup = screen("login"), screen("signup")
    assert find_form(signup)["kind"] == "signup"
    assert not same_screen(login, signup)
    assert screen_key(login) != screen_key(signup)


def test_signup_with_the_same_fields_uses_its_observed_submit_label():
    login, signup = screen("login"), screen("signup", matching_fields=True)
    assert not same_screen(login, signup)
    assert screen_key(login) != screen_key(signup)


def test_typing_does_not_change_form_identity_or_expose_values():
    empty, filled = screen("login"), screen("login", filled=True)
    assert same_screen(empty, filled)
    assert screen_key(empty) == screen_key(filled)
    assert "private-test-value" not in str(filled["identity"])


def test_menu_reached_login_is_queued_for_form_validation(monkeypatch):
    products, login = screen(), screen("login")
    device = SimpleNamespace(config={"app_mode": "installed"}, screens=[products], driver=None,
                             stop_path=SimpleNamespace(exists=lambda: False), deadline=time.monotonic() + 60, max_tries=30)
    session = AppSession(device)
    monkeypatch.setattr(session, "keep", lambda *args, **kwargs: True)
    submit = find_form(login)["submit"]
    opened = session.opened("Open Login", "menu", products, [], products, login, submit, role="menu")
    assert find_form(opened)["kind"] == "login"
    planned = next(session.feature_items())
    assert planned["area"] == "form"
    assert planned["args"][1]["kind"] == "login"


def test_clearing_a_password_uses_a_private_reference():
    password = find_form(screen("login"))["password"]
    step = fill(password, "")
    assert step["secret_ref"] == EMPTY_PASSWORD and "value" not in step
    assert generated_secrets()[EMPTY_PASSWORD] == ""
    flow = Flow.model_validate({"id": "empty_login", "title": "Empty password validation", "approved": True,
                                "steps": [step, {"action": "assert_visible", "locator": password["locators"][0]}]},
                               context={"test_mode": True})
    assert flow.steps[0].sensitive


def test_signup_emits_empty_and_invalid_email_checks_before_registration(monkeypatch):
    signup = screen("signup")
    device = SimpleNamespace(config={"app_mode": "installed"}, screens=[signup], driver=None,
                             stop_path=SimpleNamespace(exists=lambda: False), deadline=time.monotonic() + 60, max_tries=30)
    session = AppSession(device)
    flows, positive = [], []
    monkeypatch.setattr(session, "observe_after", lambda *args, **kwargs: (signup, signup))
    monkeypatch.setattr(session, "_messages", lambda *args: (
        [{"action": "assert_visible", "locator": {"strategy": "resource_id", "value": PACKAGE + ":id/error"}}],
        [{"kind": "message", "after": "Required field validation", "element": {"text": "Required field validation"}}]))
    monkeypatch.setattr(session, "keep", lambda flow, *args, **kwargs: flows.append(flow) or True)
    monkeypatch.setattr(session, "_positive_form_check", lambda *args: positive.append(len(flows)))
    session.form_checks(signup, find_form(signup))
    assert len(flows) == 2 and all(flow is not None for flow in flows)
    assert positive == [2]
    assert len([step for step in flows[0]["steps"] if step["action"] == "fill"]) == 4
    assert any(step.get("secret_ref") == EMPTY_PASSWORD for step in flows[0]["steps"])
    assert any(step.get("value") == "qa.tester" for step in flows[1]["steps"])
