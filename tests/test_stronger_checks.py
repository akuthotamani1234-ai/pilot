"""Step 6 - stronger checks:
  * a sorted column is IN ORDER (numbers as numbers, dates as dates, text without case) and a 2nd click reverses it;
  * how strong each test's proof is (strong / weak / none), read from the code; a feature whose passed tests only
    checked "no errors" is "smoke", never verified;
  * on AdminPortal: the Score column sorted as text (B1) and a case-sensitive table search (B2) are caught, the
    rows-per-page choice is checked, and the clean portal passes the same tests."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.admin_portal import AdminPortal

pytestmark = pytest.mark.slow  # (runs the whole tester: quick checks leave it out with -m "not slow")
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def helpers():
    from backend.agents.script_generator import TABLE_HELPERS
    ns = {"re": re}
    exec(TABLE_HELPERS, ns)  # (the helpers the generated steps modules get)
    return ns


def test_a_column_is_in_order_by_its_kind_of_value(helpers):
    order = helpers["_order"]
    assert order(["3", "23", "100"]) == "ascending"
    assert order(["100", "23", "3"]) == "descending"
    assert order(["100", "11", "23", "3"]) is None            # sorted as text: not in order as numbers (B1)
    assert order(["$5.00", "$12.50", "$100"]) == "ascending"
    assert order(["2024-01-31", "2024-02-01", "2025-01-01"]) == "ascending"
    assert order(["31/01/2024", "01/02/2024"]) == "ascending"  # d/m/Y
    assert order(["asha", "Ben", "chen"]) == "ascending"        # without case
    assert order(["Ben", "asha"]) == "descending"


def test_how_strong_each_test_is(tmp_path):
    from backend.assert_strength import analyse
    (tmp_path / "steps_home.py").write_text(
        "def step_sort(page):\n    assert _order([1]) == 'ascending', 'x'\n"
        "def step_click(page, console_errors):\n    new_errors = console_errors[0:]\n    assert not new_errors\n",
        encoding="utf-8")
    (tmp_path / "test_checks.py").write_text(
        "import steps_home\n"
        "def test_check_1(page):\n    steps_home.step_sort(page)\n"
        "def test_check_2(page, console_errors):\n    steps_home.step_click(page, console_errors)\n"
        "def test_check_3(page):\n    expect(page.locator('#x')).to_have_value('1')\n"
        "def test_check_4(page):\n    page.goto('x')\n", encoding="utf-8")
    s = analyse(tmp_path)
    assert s == {"test_checks.py::test_check_1": "strong", "test_checks.py::test_check_2": "weak",
                 "test_checks.py::test_check_3": "strong", "test_checks.py::test_check_4": "none"}


def test_a_feature_verified_only_by_a_smoke_test_is_not_verified():
    from backend.registry import record_outcomes
    reg = {"pages": {}, "features": {
        "F-1": {"id": "F-1", "level": "control", "kind": "button", "name": "Save", "page": "P-1", "pages": ["home"],
                "status": "inspected", "why": "", "tests": [{"tc_id": "TC-1", "how": "verifies"}], "outcomes": {}}}}
    cases = [{"tc_id": "TC-1", "title": "Every button can be clicked", "execution_status": "Passed",
              "files": ["test_checks.py"], "tests": ["test_check_2"]}]
    results = [{"nodeid": "test_checks.py::test_check_2", "file": "test_checks.py", "test": "test_check_2",
                "outcome": "passed", "checks": 1}]
    record_outcomes(reg, cases, {}, results, {"test_checks.py::test_check_2": "weak"})
    assert reg["features"]["F-1"]["status"] == "smoke"
    record_outcomes(reg, cases, {}, results, {"test_checks.py::test_check_2": "strong"})
    assert reg["features"]["F-1"]["status"] == "verified"


def _run(portal, tmp_path, path):
    env = os.environ.copy()
    env.update({"LLM_PROVIDER": "none", "HEADLESS": "true", "SLOW_MO_MS": "0", "TEST_WORKERS": "2",
                "RUNS_DIR": str(tmp_path / "runs"), "BASELINE_DIR": str(tmp_path / "baseline"),
                "WORKSPACE_DIR": str(tmp_path / "ws"), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                "PATTERN_SAMPLES": "1"})
    r = subprocess.run([sys.executable, "main.py", portal.url + path, "--no-open", "--scope", "page"], check=False, cwd=ROOT,
                       env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1500)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    run = sorted((tmp_path / "runs").iterdir())[-1]
    return json.loads((run / "test_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("bugs", [False, True])
def test_the_users_table_is_checked_like_a_tester(tmp_path, bugs):
    portal = AdminPortal(bugs=bugs).start()
    try:
        cases = _run(portal, tmp_path, "/users")
    finally:
        portal.stop()
    by = lambda words: [c for c in cases if all(w in c["title"] for w in words)]  # noqa: E731
    score = by(["'Score' column sorts"])
    search = by(["Searching the table"])
    size = by(["Rows per page"])
    name = by(["'Name' column sorts"])
    assert score and search and size and name, [c["title"] for c in cases]
    assert size[0]["execution_status"] == "Passed" and name[0]["execution_status"] == "Passed"
    if bugs:
        assert score[0]["execution_status"] == "Failed"    # B1: sorted as text
        assert search[0]["execution_status"] == "Failed"   # B2: case-sensitive
        assert "upper / lower case" in (search[0].get("actual_result") or "")
    else:
        assert score[0]["execution_status"] == "Passed", score[0].get("actual_result")
        assert search[0]["execution_status"] == "Passed", search[0].get("actual_result")


@pytest.mark.parametrize("bugs", [False, True])
def test_the_widgets_are_checked_by_what_they_did(tmp_path, bugs):
    portal = AdminPortal(bugs=bugs).start()
    try:
        cases = _run(portal, tmp_path, "/widgets")
    finally:
        portal.stop()
    by = lambda words: [c for c in cases if all(w in c["title"] for w in words)]  # noqa: E731
    alert, modal, download = by(["'Show alert'"]), by(["'Open settings'", "popup"]), by(["downloads its file"])
    assert alert and modal and download, [c["title"] for c in cases]
    assert alert[0]["execution_status"] == "Passed" and download[0]["execution_status"] == "Passed"
    assert modal[0]["execution_status"] == ("Failed" if bugs else "Passed")  # B4: the modal can't be closed
