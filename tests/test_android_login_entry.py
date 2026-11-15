"""Login/register entry screens from good.mp4 must not end functional exploration."""

import json
from types import SimpleNamespace

import pytest

from backend.android import extract_screen
from backend.android_app import AppSession
from backend.android_design import normalize_screens
from backend.android_interact import find_form
from backend.android_reporting import report


def entry_screen(primary="LOGIN", footer="New user? Register Now", footer_class="TextView"):
    xml = f'''<hierarchy><node class="android.widget.LinearLayout" bounds="[0,0][1080,2000]">
      <node class="android.widget.EditText" resource-id="email" hint="Email" bounds="[100,100][900,200]"/>
      <node class="android.widget.EditText" resource-id="password" hint="Password" password="true"
            bounds="[100,250][900,350]"/>
      <node class="android.widget.Button" resource-id="primary" text="{primary}" clickable="true"
            bounds="[100,500][900,600]"/>
      <node class="android.widget.{footer_class}" resource-id="footer" text="{footer}" clickable="true"
            bounds="[100,650][900,750]"/>
    </node></hierarchy>'''
    return normalize_screens([extract_screen(xml, "com.example.entry", "emulator-5554", ".Login")])[0]


@pytest.mark.parametrize("primary,footer,kind", [
    ("LOGIN", "New user? Register Now", "login"),
    ("REGISTER", "Already have an account? Log in", "signup"),
])
def test_form_submit_is_the_native_button_beside_an_account_navigation_link(primary, footer, kind):
    form = find_form(entry_screen(primary, footer))
    assert form["kind"] == kind
    assert form["submit"]["resource_id"] == "primary"
    assert len(form["inputs"]) == 2


@pytest.mark.parametrize("missing", [False, True])
def test_native_planner_records_an_ambiguous_or_missing_submit_without_crashing(tmp_path, missing):
    screen = entry_screen(footer_class="Button")
    if missing:
        screen["elements"] = [e for e in screen["elements"] if e.get("resource_id") not in {"primary", "footer"}]
    device = SimpleNamespace(screens=[screen], config={"app_mode": "installed"}, stop_path=tmp_path / "STOP")
    session = AppSession(device, environment={})
    item = next(session.feature_items())
    assert item["area"] == "form"
    item["run"](*item["args"])
    assert session.coverage[-1]["status"] == "not tested"
    assert session.tried[-1]["outcome"] == ("incomplete" if missing else "inconclusive")
    assert not session.flows


def test_report_headline_includes_the_functional_exploration_crash(tmp_path):
    stopped = "Stopped by an error: 'NoneType' object is not subscriptable"
    report({"run_dir": str(tmp_path), "run_id": "interrupted-entry", "config": {},
            "screens": [entry_screen()], "test_cases": [], "results": [],
            "interaction": {"enabled": True, "stopped": stopped, "tries_used": 0}})
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["incomplete"]
    assert stopped in " ".join(summary["reasons"])
    assert summary["verdict"] == "Insufficient Evidence"
