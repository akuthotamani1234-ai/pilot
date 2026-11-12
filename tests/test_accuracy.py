"""ACCURACY, measured end to end: the whole agent (main.py) against DemoStore - whose pages, features and planted bugs
are known (tests/demo_store_truth.json) - first clean, then with its 6 planted bugs. Proves that the agent finds
what is really there (also what only scrolling or an action reveals), checks results instead of clicks, catches
real bugs without false alarms, blocks protected actions and reports honest numbers. Takes ~15 minutes:

    .venv\\Scripts\\python.exe -m pytest tests/test_accuracy.py -q

ACCURACY_OUT=<file.json> also writes the measured numbers there (the same as tests/accuracy_benchmark.py --out).
"""
import json
import os
from pathlib import Path

import pytest

from tests.accuracy_benchmark import benchmark

pytestmark = pytest.mark.slow  # (runs the whole tester: quick checks leave it out with -m "not slow")


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    m = benchmark(tmp_path_factory.mktemp("accuracy"))
    if os.environ.get("ACCURACY_OUT"):
        Path(os.environ["ACCURACY_OUT"]).write_text(json.dumps(m, indent=2), encoding="utf-8")
    return m


def _rows(m):
    return {r["id"]: r for r in m["truth"]["features"]["rows"]}


def test_every_known_page_is_found_including_the_ones_only_an_action_or_scrolling_reveals(measured):
    for name in ("clean", "buggy"):
        pages = measured[name]["truth"]["pages"]
        assert not pages["missing"], (name, pages["missing"])
        assert pages["inaccessible_classified"] == {"/admin": True}  # 403 = needs permission, not a broken page


def test_clean_website_every_feature_gets_the_right_outcome_and_nothing_fails(measured):
    t = measured["clean"]["truth"]
    rows = _rows(measured["clean"])
    wrong = {k: (r["statuses"], r["detected"]) for k, r in rows.items() if not r["correct"]}
    assert t["features"]["detected"] >= 23, wrong
    assert t["features"]["correct"] >= 22, wrong
    assert not t["false_alarms"], t["false_alarms"]  # a working website: no test fails
    assert rows["deals.favourites_visitor"]["correct"]  # a visitor asked to sign in: "needs a test account", not passed
    assert rows["product.buy_now"]["correct"] and rows["checkout.place_order"]["correct"]  # blocked, never clicked


def test_planted_bugs_are_caught_without_false_passes_or_false_alarms(measured):
    b = measured["buggy"]["truth"]["bugs"]
    assert b["caught"] == sorted(json.loads(open("tests/demo_store_truth.json", encoding="utf-8").read())["bugs"]), b
    assert not b["false_pass"] and not b["not_tested"]
    assert not measured["buggy"]["truth"]["false_alarms"], measured["buggy"]["truth"]["false_alarms"]


def test_protected_actions_are_never_performed(measured):
    for name in ("clean", "buggy"):
        assert measured[name]["truth"]["never_requested_but_done"] == []


def test_the_reported_numbers_match_the_registry_and_the_results(measured):
    from pathlib import Path

    from backend import registry
    run = Path(measured["clean"]["run_dir"])
    reg = registry.load(run)
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    counts = summary["coverage"]["registry"]
    assert counts == registry.counts(reg, json.loads((run / "crawl.json").read_text(encoding="utf-8")))
    f = counts["features"]
    assert f["discovered"] == len(reg["features"])
    assert f["verified"] == sum(1 for x in reg["features"].values() if x["status"] == "verified")
    assert f["verified"] <= f["tested"] <= f["discovered"]
    assert all(x["why"] for x in reg["features"].values() if x["status"] in ("unresolved", "clicked_only"))
    cases = json.loads((run / "test_cases.json").read_text(encoding="utf-8"))
    linked = {t["tc_id"] for x in reg["features"].values() for t in x["tests"]}
    assert linked <= {c["tc_id"] for c in cases}  # every link points to a real test case
    a = json.loads((run / "crawl.json").read_text(encoding="utf-8"))["actions"]
    assert a["attempted"] >= 10 and "limit_per_page" in a  # what exploring tried, and its limit, are disclosed
