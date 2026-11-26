"""A one-time code (OTP) a person types for an Android run: asked once, used once, never kept."""
import json
import threading
import time

import pytest

from backend import android_code


def box(**k):
    return {"input_capable": True, "visible": True, "locators": [{"strategy": "resource_id", "value": "otp"}], **k}


def test_a_code_screen_is_recognised_and_a_login_screen_is_not():
    otp = {"screen_name": "Verify", "elements": [{"text": "Enter the 6-digit code sent to +91 98…", "visible": True},
                                                 box(hint="Code")]}
    assert android_code.code_field(otp)["hint"] == "Code"
    login = {"screen_name": "Login", "elements": [box(hint="Email"), box(hint="Password", password=True)]}
    assert android_code.code_field(login) is None
    named = {"screen_name": "Login", "elements": [box(hint="Mobile number"), box(hint="OTP")]}
    assert android_code.code_field(named)["hint"] == "OTP"


def test_the_person_types_the_code_once_and_it_is_not_kept(tmp_path):
    got = {}

    def run():
        got["code"] = android_code.ask_person(tmp_path, "Verify", "Code", wait_s=10, sleep=lambda s: time.sleep(0.05))
    t = threading.Thread(target=run)
    t.start()
    for _ in range(100):
        if android_code.waiting(tmp_path):
            break
        time.sleep(0.02)
    assert android_code.waiting(tmp_path)["screen"] == "Verify"
    with pytest.raises(ValueError):
        android_code.give_code(tmp_path, "12 34")  # (not a code)
    android_code.give_code(tmp_path, "482913")
    t.join(5)
    assert got["code"] == "482913"
    assert not (tmp_path / android_code.ANSWER).exists() and not (tmp_path / android_code.REQUEST).exists()
    assert android_code.waiting(tmp_path) is None
    with pytest.raises(ValueError, match="not waiting"):
        android_code.give_code(tmp_path, "111111")  # (nobody is asking any more)


def test_nothing_waits_without_time_for_a_person_or_after_stop(tmp_path):
    assert android_code.ask_person(tmp_path, "Verify", "Code", wait_s=0) == ""
    stop = tmp_path / "STOP"
    stop.write_text("x")
    assert android_code.ask_person(tmp_path, "Verify", "Code", wait_s=30, stop_path=stop) == ""
    assert android_code.waiting(tmp_path) is None


def test_the_studio_endpoints_ask_and_answer(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import server
    run = tmp_path / "android_20261123_000000_abcdef"
    run.mkdir()
    monkeypatch.setattr(server, "_run_dir", lambda name: run)
    client = TestClient(server.app, base_url="http://127.0.0.1")
    assert client.get(f"/api/runs/{run.name}/code").json() == {"waiting": None}
    (run / android_code.REQUEST).write_text(json.dumps({"screen": "Verify", "field": "Code", "asked_at": time.time(),
                                                        "wait_s": 60}))
    assert client.get(f"/api/runs/{run.name}/code").json()["waiting"]["screen"] == "Verify"
    assert client.post(f"/api/runs/{run.name}/code", json={"code": "482913"}).status_code == 403  # (UI header)
    ok = client.post(f"/api/runs/{run.name}/code", json={"code": "482913"}, headers={"X-Agentic-QA": "1"})
    assert ok.status_code == 200 and (run / android_code.ANSWER).read_text() == "482913"


def test_the_run_types_your_code_into_the_app_and_masks_it(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from backend import android_interact as ai
    otp = {"screen_name": "Verify OTP", "elements": [
        {"text": "Enter the code sent to your phone", "visible": True},
        box(hint="Code", id="otp", class_name="android.widget.EditText"),
        {"id": "verify", "text": "Verify", "clickable": True, "visible": True, "enabled": True,
         "class_name": "android.widget.Button", "locators": [{"strategy": "text", "value": "Verify"}]}]}
    session = ai.Session.__new__(ai.Session)
    session.tried, session.secrets = [], {}
    session.device = SimpleNamespace(stop_path=tmp_path / "STOP", config={"human_wait_s": 60},
                                     observe=lambda: {"screen_name": "Products", "elements": []})
    performed, masked = [], []
    monkeypatch.setattr(android_code, "ask_person", lambda *a, **k: "482913")
    monkeypatch.setattr(ai, "usable", lambda e: True)
    monkeypatch.setattr(ai, "reach", lambda e: [])

    def perform(steps):
        performed.extend(steps)
        masked.append("482913" in session.secrets.values())
    session.perform = perform
    after = session.person_code(otp)
    assert after["screen_name"] == "Products"
    assert performed[0] == {"action": "fill", "locator": {"strategy": "resource_id", "value": "otp"}, "value": "482913"}
    assert performed[-1]["action"] == "tap" and masked == [True]  # (masked while typed)
    assert "482913" not in session.secrets.values()  # (and forgotten after)
    assert session.tried[-1]["outcome"] == "typed by you" and "482913" not in str(session.tried)


def test_network_steps_are_valid_only_as_off_or_on():
    from backend.qa_contracts import Step
    assert Step(action="network", value="off").value == "off"
    with pytest.raises(ValueError):
        Step(action="network", value="slow")


def _adapter(current):
    from backend.qa_runtime import AndroidContractAdapter
    adapter = AndroidContractAdapter.__new__(AndroidContractAdapter)
    calls = []
    state = {"pkg": current}

    class Driver:
        current_package = property(lambda self: state["pkg"])
        current_context = "NATIVE_APP"
        contexts = ["NATIVE_APP"]

        def switch_to_context(self, name):
            pass

        def execute_script(self, name, args):
            calls.append((name, args))

        def background_app(self, seconds):
            calls.append(("background", seconds))

        def activate_app(self, package):
            calls.append(("activate", package))
            state["pkg"] = package
    driver = Driver()
    adapter.driver, adapter.config, adapter.stop_path, adapter.active = driver, {"package_name": "com.shop"}, None, "native"
    return adapter, calls


def test_the_network_is_switched_off_and_on_for_the_app(monkeypatch):
    import backend.qa_runtime as rt
    monkeypatch.setattr(rt.time, "sleep", lambda s: None)
    adapter, calls = _adapter("com.shop")
    adapter.device_action("network", "off")
    assert calls[-1] == ("mobile: setConnectivity", {"wifi": False, "data": False}) and adapter.offline
    adapter.device_action("network", "on")
    assert calls[-1] == ("mobile: setConnectivity", {"wifi": True, "data": True}) and not adapter.offline


def test_after_leaving_the_app_the_tester_taps_it_again(monkeypatch):
    """2026-11-23: 'comes back after leaving the app' failed because the phone stayed on its home screen."""
    import backend.qa_runtime as rt
    monkeypatch.setattr(rt.time, "sleep", lambda s: None)
    clock = iter(range(0, 1000))
    monkeypatch.setattr(rt.time, "monotonic", lambda: next(clock))
    adapter, calls = _adapter("com.google.android.apps.nexuslauncher")
    adapter.device_action("background", "3")
    assert ("activate", "com.shop") in calls


# ---- CartNShop run android_20261123_075125_a149f8

def test_a_field_wrapper_is_not_offered_to_the_ai():
    from backend.android_interact import wraps_input
    box = {"input_capable": True, "bounds": "[60,500][1020,640]"}
    til = {"class_name": "com.google.android.material.textfield.TextInputLayout", "resource_id": "x:id/til_email",
           "bounds": "[40,480][1040,660]", "clickable": True}
    frame = {"class_name": "android.widget.FrameLayout", "bounds": "[40,480][1040,660]", "text": ""}
    button = {"class_name": "android.widget.Button", "text": "LOGIN", "bounds": "[60,700][1020,800]"}
    screen = {"elements": [til, frame, box, button]}
    assert wraps_input(screen, til) and wraps_input(screen, frame)
    assert not wraps_input(screen, box) and not wraps_input(screen, button)


def test_a_sign_up_error_keeps_its_text_masked_and_a_screenshot(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import backend.android as android
    from backend import android_interact as ai
    monkeypatch.setattr(android, "capture_screenshot", lambda driver, run_dir, name, pkg=None: f"screenshots/{name}.png")
    import backend.android_accounts as acc
    monkeypatch.setattr(acc, "persist", lambda s: None)
    session = ai.Session.__new__(ai.Session)
    session.screens = [{"package_name": "com.mycompany.cartnshop"}]
    session.device = SimpleNamespace(stop_path=tmp_path / "STOP", driver=object())
    session.account_setup = {"status": "attempted"}
    said = session.keep_error({"screen_name": "CREATE AN ACCOUNT"}, "Sign-up",
                              "The email qa.x@example.com is badly formatted", ["qa.x@example.com"])
    assert "qa.x@example.com" not in said and "badly formatted" in said
    assert session.account_setup["status"] == "failed" and session.account_setup["screenshot"].endswith("sign-up_error.png")
    assert "badly formatted" in session.account_setup["detail"]


def test_an_evidence_screenshot_is_also_the_live_device_frame(tmp_path):
    from backend.android import capture_screenshot

    class D:
        current_context, current_package, page_source = "NATIVE_APP", "com.example.app", "<hierarchy/>"

        def save_screenshot(self, p):
            open(p, "wb").write(b"\x89PNG\r\n\x1a\nscreen")
            return True
    assert capture_screenshot(D(), tmp_path, "step_1", "com.example.app") == "screenshots/step_1.png"
    assert (tmp_path / "live" / "device.jpg").read_bytes() == b"\x89PNG\r\n\x1a\nscreen"
