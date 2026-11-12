"""The report's numbers come from ONE canonical calculation (backend/metrics.py) and are checked against each other:
link checks never inflate the functional pass rate, a blocked test case is not 'executed', every percentage says
its denominator, and a total that does not add up is reported as a failed consistency check."""
from backend import metrics


def _r(file, test, outcome, checks=1, **kw):
    return dict({"nodeid": f"{file}::{test}", "file": file, "test": test, "outcome": outcome, "checks": checks}, **kw)


def _c(cid, files, tests, status, **kw):
    return dict({"id": cid, "tc_id": f"TC-{abs(hash(cid)) % 10 ** 8:08X}", "title": cid, "files": files,
                 "tests": tests, "execution_status": status}, **kw)


def _run():
    """Like the AutomationTestStore report: many link checks pass, the functional tests mostly fail."""
    results = [_r("test_all_links.py", f"test_link[int_{n}]", "passed") for n in range(40)]
    results += [_r("test_all_links.py", "test_link[ext_1]", "skipped", checks=0)]
    results += [_r("test_site.py", f"test_page_loads[p{n}]", "passed") for n in range(5)]
    results += [_r("test_home_data.py", "test_data_email_no_at", "inconclusive", checks=0,
                   error="Inconclusive: the box itself does not check e-mail addresses")]
    results += [_r("test_checks.py", "test_check_1", "failed", error="AssertionError: search"),
                _r("test_checks.py", "test_check_2", "passed"), _r("test_checks.py", "test_check_3", "passed"),
                _r("test_journeys.py", "test_journey_1", "failed", error="AssertionError: cart total")]
    cases = [_c("site_links", ["test_all_links.py"], ["test_link", "test_section_link"], "Passed", size="small"),
             _c("site_pages_open", ["test_site.py"], ["test_page_loads"], "Passed", size="small"),
             _c("site_input_values", ["test_home_data.py"], ["test_data_*"], "Inconclusive", size="small"),
             _c("check_1", ["test_checks.py"], ["test_check_1"], "Failed", kind="check"),
             _c("check_2", ["test_checks.py"], ["test_check_2"], "Passed", kind="check"),
             _c("check_3", ["test_checks.py"], ["test_check_3"], "Passed", kind="check"),
             _c("journey_1", ["test_journeys.py"], ["test_journey_1"], "Failed", kind="journey"),
             _c("blocked_1", [], [], "Blocked", kind="blocked", blocked=True)]
    failures = [{"source": "test", "nodeid": r["nodeid"], "category": c} for r, c in
                [(results[-4], "product_defect"), (results[-1], "product_defect"), (results[-5], "inconclusive")]]
    return results, cases, failures


def test_link_checks_never_inflate_the_functional_pass_rate():
    results, cases, failures = _run()
    m = metrics.build(results, cases, None, failures)
    h = m["headline"]
    assert h["name"] == "Functional test cases passed"
    assert (h["passed"], h["of"], h["percent"]) == (2, 4, 50)  # check_2 + check_3 of 4 functional cases with a verdict
    assert "link, page and input checks are not in it" in h["denominator"]
    links = next(r for r in m["rates"] if r["name"].startswith("URL and link"))
    assert (links["passed"], links["of"]) == (40, 40) and "1 skipped" in links["denominator"]
    g = m["single_tests"]["groups"]
    assert (g["links"]["total"], g["page_checks"]["total"], g["input_checks"]["total"], g["functional"]["total"]) == \
        (41, 5, 1, 4)
    # every percentage says what it is a share of
    assert all(r["denominator"] for r in m["rates"])


def test_a_blocked_case_is_planned_but_not_executed():
    results, cases, failures = _run()
    tc = metrics.build(results, cases, None, failures)["test_cases"]
    assert tc["planned"] == 8 and tc["blocked"] == 1
    assert tc["executed"] == 7 and tc["not_executed"] == 1  # (the old report counted 53 executed with 1 blocked)


def test_workflows_and_findings_are_counted_separately():
    results, cases, failures = _run()
    m = metrics.build(results, cases, None, failures)
    assert m["workflows"]["failed"] == 1 and len(m["workflows"]["list"]) == 1
    f = m["findings"]
    assert f["application_defects"] == 2 and f["inconclusive"] == 1 and f["test_problems"] == 0


def test_the_totals_add_up_and_a_mismatch_is_reported():
    results, cases, failures = _run()
    m = metrics.build(results, cases, None, failures)
    assert m["consistent"], [c for c in m["consistency"] if not c["ok"]]
    # a test case whose stored status does not follow from its own tests (e.g. a stale status after a re-run)
    cases[4]["execution_status"] = "Failed"
    bad = {c["check"] for c in metrics.build(results, cases, None, failures)["consistency"] if not c["ok"]}
    assert "Each test case's status is the result of its own single tests" in bad
    # a single test that no test case owns, and a failed test without its finding
    cases[4]["execution_status"] = "Passed"
    results.append(_r("test_extra.py", "test_orphan", "failed"))
    bad = {c["check"] for c in metrics.build(results, cases, None, failures)["consistency"] if not c["ok"]}
    assert {"Every single test belongs to a test case", "Every failed or inconclusive single test has its finding"} <= bad


def test_a_verified_feature_needs_a_passed_test_that_ran_assertions():
    results, cases, failures = _run()
    reg = {"pages": {"P-1": {"pattern": "/", "state": "verified"}},
           "features": {"F-1": {"id": "F-1", "name": "sort", "level": "feature", "status": "verified",
                                "tests": [{"tc_id": cases[4]["tc_id"], "how": "verifies"}]},
                        "F-2": {"id": "F-2", "name": "search", "level": "feature", "status": "failed",
                                "tests": [{"tc_id": cases[3]["tc_id"], "how": "verifies"}]}},
           "counts": {"pages": {"discovered": 1, "inspected": 1, "tested": 1, "verified": 1},
                      "features": {"discovered": 2, "verified": 1, "failed": 1}}}
    m = metrics.build(results, cases, reg, failures)
    assert m["consistent"], [c for c in m["consistency"] if not c["ok"]]
    results[-3]["checks"] = 0  # the 'passed' test of the verified feature checked nothing
    bad = {c["check"] for c in metrics.build(results, cases, reg, failures)["consistency"] if not c["ok"]}
    assert "Every verified feature has a passed test case that checked its result" in bad
    reg["features"]["F-2"]["tests"] = [{"tc_id": cases[4]["tc_id"], "how": "verifies"}]  # failed by a passing test?
    bad = {c["check"] for c in metrics.build(results, cases, reg, failures)["consistency"] if not c["ok"]}
    assert "Every failed feature has a failed test case that checks it" in bad
    lines = metrics.summary_lines(metrics.build(results, cases, reg, failures))
    assert any("consistency check(s) FAILED" in line for line in lines)
