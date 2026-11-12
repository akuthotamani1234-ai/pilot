"""Steps 17 + 19 - a LARGE website (BigStore: 2,000 products) is tested by page TYPE, within its budget:
  * product addresses WITHOUT a number (/products/red-oak-lamp): the product pages are ONE page type by their design;
    "3 fully tested / 10 smoke-checked / 2,000 found" is reported (the sitemap lists them all);
  * the run finishes inside RUN_TIME_LIMIT_MIN (it is not incomplete) and visits far fewer pages than exist;
  * its 3 planted bugs (a search hit without the word, an unsorted price sort, a cart total that ignores the quantity)
    are caught.
Several minutes:  python -m pytest tests/test_big_store.py -q"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.accuracy import measure
from tests.big_store import EMAIL, PASSWORD, BigStore

pytestmark = pytest.mark.slow  # (runs the whole tester: quick checks leave it out with -m "not slow")
ROOT = Path(__file__).resolve().parent.parent
TRUTH = json.loads((ROOT / "tests" / "truth" / "big_store.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    work = tmp_path_factory.mktemp("big")
    store = BigStore(bugs=True, slugs=True).start()
    env = os.environ.copy()
    env.update({"LLM_PROVIDER": "none", "HEADLESS": "true", "SLOW_MO_MS": "0", "TEST_WORKERS": "3",
                "RUNS_DIR": str(work / "runs"), "BASELINE_DIR": str(work / "baseline"), "WORKSPACE_DIR": str(work / "ws"),
                "TEST_USERNAME": EMAIL, "TEST_PASSWORD": PASSWORD, "AUTO_REGISTER": "false", "RUN_TIME_LIMIT_MIN": "60",
                "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "MAX_INTERACTIONS_PER_PAGE": "8",
                "PATTERN_SAMPLES": "3"})
    try:
        r = subprocess.run([sys.executable, "main.py", store.url, "--no-open", "--max-pages", "0"], check=False, cwd=ROOT, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=4200)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
        d = sorted((work / "runs").iterdir())[-1]
        return d, measure(d, TRUTH, True, list(store.visited))
    finally:
        store.stop()


def test_the_product_pages_are_one_page_type(run):
    d, _ = run
    s = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    kinds = {k["kind"]: k for k in s["coverage_card"]["items"]}
    want = TRUTH["page_type"]
    assert want["kind"] in kinds, list(kinds)
    k = kinds[want["kind"]]
    assert (k["fully_tested"], k["smoke"], k["found"]) == (want["fully_tested"], want["smoke"], want["found"]), k


def test_the_run_stays_within_its_budget(run):
    d, m = run
    s = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    assert not s["incomplete"], s["reasons"][:1]
    assert m["pages"]["discovered"] < 120  # (2,000 product pages exist: a sample of each kind is visited)


def test_the_planted_bugs_are_caught(run):
    _, m = run
    assert len(m["truth"]["bugs"]["caught"]) == 3, m["truth"]["bugs"]
    assert m["truth"]["never_requested_but_done"] == []
