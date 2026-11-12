"""What the run on zero.webappsecurity.com (runs/zero.webappsecurity.com_20261101_233258) got wrong: this computer's
security software (Bitdefender Endpoint Security Tools) blocked the plain-http demo bank in the middle of the tests
("Malicious attack attempt (PrivacyThreat.PasswordStealer.HTTP)") - from then on every test saw its block page. The
report said 126 failures (missing boxes, 'HTTP 403' as a refused login) instead of "blocked by your security software:
these results prove nothing"."""

BITDEFENDER = ("E   AssertionError: the input box should be visible\nE   Error: element(s) not found\n"
               "E     - waiting for locator(\"#name\").first\nE   Aria snapshot:\nE   - table:\nE     - rowgroup:\n"
               "E       - 'row \"This page has been blocked Bitdefender Endpoint Security Tools has blocked access to "
               "this webpage in accordance with your organization's security and compliance policies. Detecting module: "
               "Network Attack Defense Reason: Malicious attack attempt (PrivacyThreat.PasswordStealer.HTTP)\"':")


def _r(test, error, file="test_feedback_html_data.py"):
    return {"nodeid": f"{file}::{test}", "file": file, "test": test, "outcome": "failed", "error": error,
            "error_type": "AssertionError"}


def test_a_security_software_block_page_is_no_website_bug():
    from backend.agents.failure_analysis import BLOCKED_WHY, classify
    cat, why, _ = classify(_r("test_data_name_valid", BITDEFENDER))
    assert (cat, why) == ("infrastructure", BLOCKED_WHY)  # (was: locator - 'the input box should be visible')


def test_once_blocked_an_http_403_is_the_block_page_too(tmp_path):
    from backend.agents.failure_analysis import BLOCKED_ACTION, failure_analysis_agent
    forbidden = "E   AssertionError: http://zero.test/search.html?searchTerm=a returned HTTP 403"
    results = [_r("test_data_name_valid", BITDEFENDER), _r("test_page_loads[search]", forbidden, "test_site.py")]
    out = failure_analysis_agent({"url": "http://zero.test/", "results": results, "test_cases": [], "run_dir": str(tmp_path)})
    tests = [f for f in out["failures"] if f["source"] == "test"]
    assert [f["category"] for f in tests] == ["infrastructure", "infrastructure"], tests
    assert all(f["next_action"] == BLOCKED_ACTION and "bug" not in f for f in tests)
    # without a block page in the run, an HTTP 403 stays what it was: the login / permission was refused
    out = failure_analysis_agent({"url": "http://zero.test/", "results": [results[1]], "test_cases": [],
                                  "run_dir": str(tmp_path)})
    assert [f["category"] for f in out["failures"] if f["source"] == "test"] == ["auth_problem"]
