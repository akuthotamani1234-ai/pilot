"""Iframes and shadow DOM (Step 3), on the local AdminPortal:
  * an input in an OPEN shadow root and a checkbox in a NESTED shadow root are found (with their shadow path),
    and a CLOSED shadow root is listed as unsupported - never guessed;
  * an iframe and the iframe nested in it are walked: their button and checkbox are found with a frame path and an
    address a test can use (the frame chain), and no same-site frame says "not tested yet";
  * the iframe's 'Load totals' button is learned and tested end to end - it passes on the clean portal and fails
    with the planted bug (B6: the button does nothing)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.config import settings
from tests.admin_portal import AdminPortal

pytestmark = pytest.mark.slow  # (runs the whole tester: quick checks leave it out with -m "not slow")
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def portal():
    p = AdminPortal().start()
    yield p
    p.stop()


def _discover(url, tmp_path, monkeypatch):
    from backend.agents.discovery import discovery_agent
    monkeypatch.setattr(settings, "crawl_scope", "page")
    return discovery_agent({"url": url, "run_dir": str(tmp_path), "site_key": "portal", "log": []})["app_map"][0]


def test_open_and_nested_shadow_roots_are_read_and_a_closed_one_is_reported(portal, tmp_path, monkeypatch):
    page = _discover(portal.url + "/widgets", tmp_path, monkeypatch)
    by_id = {i.get("id"): i for i in page["inputs"]}
    assert by_id["nickname"]["shadow_path"] == ["user-card#profile-card"]
    assert by_id["newsletter"]["shadow_path"] == ["user-card#profile-card", "pref-toggle"]
    assert by_id["newsletter"]["label"] == "Newsletter"
    assert [u["tag"] for u in page["unsupported"]] == ["secret-widget"]
    assert "closed shadow root" in page["unsupported"][0]["reason"]
    # the newsletter checkbox is learned like any other control (it changes the text next to it)
    learned = {b["control"]: b for b in page.get("behaviour", [])}
    assert learned["Newsletter"]["effect"] in ("text", "value"), learned.get("Newsletter")


def test_nested_iframes_are_walked_and_their_controls_get_a_frame_address(portal, tmp_path, monkeypatch):
    from backend.agents.discovery import ENTER
    page = _discover(portal.url + "/reports", tmp_path, monkeypatch)
    frames = page["frames"]
    assert [(f["name"], f["status"], len(f["path"])) for f in frames] == [
        ("Totals", "testable", 1), ("Archive options", "testable", 2)]
    load = next(b for b in page["buttons"] if b.get("text") == "Load totals")
    assert load["frame_path"] == ['iframe[id="totals-frame"]'] and ENTER in load["selector"]
    box = next(i for i in page["inputs"] if i.get("id") == "include-archived")
    assert box["frame_path"] == ['iframe[id="totals-frame"]', 'iframe[name="archive"]']
    assert box["selector"].count("internal:control=enter-frame") == 2
    # what the frame's button did was seen (the frame's text changed)
    learned = {b["control"]: b for b in page.get("behaviour", [])}
    assert any("Total sales: 4560" in a for a in learned["Load totals"]["added"]), learned["Load totals"]
    # the coverage list: no same-site frame is "not tested yet"
    from backend.agents.test_design import coverage
    items = coverage(page, "")["items"]
    frames_listed = [x for x in items if x["kind"] == "embedded frame (iframe)"]
    assert frames_listed and all(x["status"] == "tested" for x in frames_listed)


def _run(portal, tmp_path, path):
    env = os.environ.copy()
    env.update({"LLM_PROVIDER": "none", "HEADLESS": "true", "SLOW_MO_MS": "0", "TEST_WORKERS": "2",
                "RUNS_DIR": str(tmp_path / "runs"), "BASELINE_DIR": str(tmp_path / "baseline"),
                "WORKSPACE_DIR": str(tmp_path / "ws"), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    r = subprocess.run([sys.executable, "main.py", portal.url + path, "--no-open", "--scope", "page"], check=False, cwd=ROOT,
                       env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1200)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    run = sorted((tmp_path / "runs").iterdir())[-1]
    return json.loads((run / "results.json").read_text(encoding="utf-8")), run


@pytest.mark.parametrize("bugs", [False, True])
def test_the_iframe_button_is_tested_and_its_bug_is_caught(tmp_path, bugs):
    portal = AdminPortal(bugs=bugs).start()
    try:
        results, run = _run(portal, tmp_path, "/reports")
    finally:
        portal.stop()
    cases = json.loads((run / "test_cases.json").read_text(encoding="utf-8"))
    load = [c for c in cases if "Load totals" in c["title"]]
    assert load, [c["title"] for c in cases]
    status = {c["execution_status"] for c in load}
    if bugs:  # B6: the button does nothing -> its test fails (on the clean portal the same test passed)
        assert "Failed" in status, status
    else:
        assert status == {"Passed"}, [(c["title"], c["execution_status"], c.get("actual_result")) for c in load]
    archived = [c for c in cases if "Include archived" in c["title"]]
    assert archived and all(c["execution_status"] in ("Passed", "Failed") for c in archived)
