"""iOS autonomous / hybrid / requirement-based on one stateful fake XCUITest app (tests/ios_fake_app.py): discovery
(screens, transitions, the WebView inspected in its own context and back), nothing risky tapped, scenarios from what
discovery saw, AI scenarios validated against real controls, Jira cases planned over every screen, real execution of
each step against the app's state - so a real defect fails, a correct app passes. No Mac here: live iOS is BLOCKED."""
import json

from backend import ios
from backend.requirements_api import run_ios
from tests.ios_fake_app import FakeIosApp


def _discover(tmp_path, **kw):
    app = FakeIosApp(**kw)
    return app, ios.explore(app, tmp_path, "com.example.shop", settle_s=0)


def test_discovery_finds_every_safe_screen_inspects_the_webview_and_never_taps_risky_controls(tmp_path):
    app, model = _discover(tmp_path)
    ids = {sc["id"]: sc for sc in model["screens"]}
    assert len(ids) == 3  # home, shop, help
    help_ = next(sc for sc in ids.values() if sc["webview"])
    assert help_["webview"]["inspectable"] and help_["webview"]["ids"] == ["faq", "shipping"]
    assert help_["path"] == [{"by": "accessibility_id", "target": "helpButton"}]
    assert "deleteAccount" not in app.taps and any(s["control"] == "deleteAccount" for s in model["skipped"])
    assert [c["to"] for c in model["context_switches"]][:2] == ["WEBVIEW_77.1", "NATIVE_APP"]
    assert (tmp_path / "ios_screens.json").is_file() and (tmp_path / "screens" / "S1.png").is_file()
    assert (tmp_path / "live" / "device.jpg").read_bytes().startswith(b"\x89PNG")  # (the Live Execution frame)


def test_autonomous_scenarios_really_run_and_a_real_defect_fails(tmp_path):
    for bug in (False, True):
        app, model = _discover(tmp_path / str(bug), bug=bug)
        cases = ios.autonomous_cases(model)
        titles = " | ".join(c.title for c in cases)
        assert "opens" in titles and "web content" in titles
        add_case = ios.IosCase(case="IOS-X", title="adding a product sets the badge to 1", from_launch=True, steps=[
            ios.IosStep(action="tap", target="shopButton"), ios.IosStep(action="tap", target="addToCart"),
            ios.IosStep(action="assert_text", target="cartBadge", value="1")])
        runner = ios.IosRun(app, tmp_path / str(bug), "com.example.shop")
        recs = [runner.run_case(c) for c in cases + [add_case]]
        assert all(r["execution_status"] == "Passed" for r in recs[:-1]), recs
        assert recs[-1]["execution_status"] == ("Failed" if bug else "Passed")  # (the app's defect, not hidden)
        web = next(r for r, c in zip(recs, cases) if "web content" in c.title)
        assert any(s["to"].startswith("WEBVIEW") for s in runner.context_switches)
        assert runner.context_switches[-1]["to"] == "NATIVE_APP" and web["check_count"] == 2


def test_a_webview_that_cannot_be_inspected_is_said_exactly_never_passed(tmp_path):
    app, model = _discover(tmp_path, inspectable=False)
    case = next(c for c in ios.autonomous_cases(model) if "web content" in c.title)
    rec = ios.IosRun(app, tmp_path, "com.example.shop").run_case(case)
    assert rec["execution_status"] == "Not run" and "isInspectable" in rec["skip_reason"]


def test_ai_scenarios_only_over_real_controls_and_never_risky(tmp_path):
    app, model = _discover(tmp_path)

    def ask(prompt, shape, **kw):
        assert "helpButton" in prompt and "#faq" in prompt or "faq" in prompt
        return [ios.IosCase(case="x", title="FAQ shown", steps=[ios.IosStep(action="tap", target="helpButton"),
                                                               ios.IosStep(action="assert_visible", by="css",
                                                                           target="#faq")]),
                ios.IosCase(case="y", title="invented", steps=[ios.IosStep(action="tap", target="wishlist"),
                                                              ios.IosStep(action="assert_visible", target="x")]),
                ios.IosCase(case="z", title="risky", steps=[ios.IosStep(action="tap", target="deleteAccount"),
                                                           ios.IosStep(action="assert_visible", target="gone")])]
    got = {c.title: c for c in ios.ai_scenarios(model, ask=ask)}
    assert got["FAQ shown"].steps and got["FAQ shown"].from_launch
    assert "does not show" in got["invented"].not_possible and "changes data" in got["risky"].not_possible


def _ask_for_jira(prompt, shape, **kw):  # (the AI plans the Jira case over the discovered screens)
    assert "reach_by_tapping_from_launch" in prompt
    return [ios.IosCase(case="TC-QPL-4-1", steps=[ios.IosStep(action="tap", target="shopButton"),
                                                  ios.IosStep(action="tap", target="addToCart"),
                                                  ios.IosStep(action="assert_text", target="cartBadge", value="1")])]


TESTS = [{"tc": "TC-QPL-4-1", "title": "Adding a product puts it in the cart", "text": "Add a product; badge is 1"}]


def test_three_strategies_on_ios(tmp_path):
    lines = []
    req = run_ios(FakeIosApp(), tmp_path / "r", "com.example.shop", TESTS, "requirements", lines.append,
                  ask=_ask_for_jira, settle_s=0)
    assert [r.get("requirement_test") for r in req] == ["TC-QPL-4-1"] and req[0]["execution_status"] == "Passed"

    def no_ai(*a, **k):
        from backend.llm import LLMError
        raise LLMError("no AI")
    auto = run_ios(FakeIosApp(), tmp_path / "a", "com.example.shop", [], "autonomous", lines.append, ask=no_ai,
                   settle_s=0)
    assert auto and all(r["origin"] == "autonomous" and "requirement_test" not in r for r in auto)
    assert all(r["execution_status"] == "Passed" for r in auto)

    def both(prompt, shape, **kw):
        return _ask_for_jira(prompt, shape) if "TEST CASES" in prompt else no_ai()
    hyb = run_ios(FakeIosApp(bug=True), tmp_path / "h", "com.example.shop", TESTS, "hybrid", lines.append, ask=both,
                  settle_s=0)
    jira = [r for r in hyb if r.get("requirement_test")]
    assert jira[0]["execution_status"] == "Failed"  # (the defect is reported on the Jira case)
    assert len(hyb) > 1 and any(r.get("origin") == "autonomous" for r in hyb)
    assert json.loads((tmp_path / "h" / "ios_contexts.json").read_text())
    assert any("discovery: 3 screen(s)" in ln for ln in lines)
