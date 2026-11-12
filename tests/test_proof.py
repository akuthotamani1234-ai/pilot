"""Step 13 - the proof, on the two practice sites whose truth is known (tests/truth/*.json). The whole agent (main.py),
no AI, measured by backend/accuracy.py:

  AdminPortal (staging: forms sent, delete allowed)   feature recall >= 95 %; both frames found and tested;
                                                      first run on the buggy portal >= 6 / 7 bugs (B6 may be suspect);
                                                      regression (the clean run's tests on the buggy portal) 7 / 7;
                                                      0 false alarms on the clean portal; nothing tagged left behind
  TravelSite (default environment: nothing sent)      first run >= 5 / 6 bugs (T1-T3, T6 as rule violations);
                                                      0 false alarms on the clean site
These runs take a while (several minutes each):  python -m pytest tests/test_proof.py -q
"""
import json

import pytest

from tests.accuracy_benchmark import benchmark

pytestmark = pytest.mark.slow  # (runs the whole tester: quick checks leave it out with -m "not slow")


@pytest.fixture(scope="module")
def admin(tmp_path_factory):
    return benchmark(tmp_path_factory.mktemp("admin"), site="admin", mode="both")


@pytest.fixture(scope="module")
def travel(tmp_path_factory):
    return benchmark(tmp_path_factory.mktemp("travel"), site="travel", mode="first")


def _show(m):
    return json.dumps({k: m["truth"].get(k) for k in ("bugs", "false_alarms", "questions", "frames")}, indent=1)[:3000]


def test_adminportal_recall_and_frames(admin):
    t = admin["clean"]["truth"]
    f = t["features"]
    assert f["detected"] / f["known"] >= 0.95, [r["id"] for r in f["rows"] if not r["detected"]]
    assert t["frames"]["found"] == 2 and t["frames"]["tested"] == 2, t["frames"]
    assert t["false_alarms"] == [], t["false_alarms"]


def test_adminportal_bugs_first_run_and_regression(admin):
    first, reg = admin["buggy"]["truth"]["bugs"], admin["regression"]["truth"]["bugs"]
    assert len(first["caught"]) >= 6, _show(admin["buggy"])
    assert len(reg["caught"]) == 7, _show(admin["regression"])


def test_adminportal_leaves_no_test_data(admin):
    for name in ("clean", "buggy"):
        s = json.loads((__import__("pathlib").Path(admin[name]["run_dir"]) / "summary.json").read_text(encoding="utf-8"))
        assert s["data_created"]["left"] == 0, (name, s["data_created"])


def test_travelsite_rules_and_items(travel):
    bugs = travel["buggy"]["truth"]["bugs"]
    assert len(bugs["caught"]) >= 5, _show(travel["buggy"])
    assert {"T1", "T2", "T3", "T6"} <= set(bugs["caught"]), bugs
    assert travel["clean"]["truth"]["false_alarms"] == [], travel["clean"]["truth"]["false_alarms"]
    assert travel["clean"]["truth"]["questions"] == [], travel["clean"]["truth"]["questions"]
    assert travel["buggy"]["truth"]["never_requested_but_done"] == []  # (nothing was sent: POST /signup never)
