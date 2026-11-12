"""Agent 5 — Failure Analysis Agent.

For every failed (or inconclusive) test and every problem the crawler saw, decide from the EVIDENCE what it is:
  product_defect   the WEBSITE probably has a bug                      (a check about the website failed)
  assertion_failure an exploratory expectation was not met: the control did not do what it did while exploring
                   (the website may have changed, or the behaviour depends on its state), or an AI-written
                   expectation that was never observed - review, not proven a bug
  locator          the test could not find or use the element          (not found, not unique, covered, not visible) -
                   not proof that the website is broken; self-healing tries to repair the script
  test_defect      the generated SCRIPT is wrong                       (coding error, sandbox)
  test_data        a test-data / precondition problem                  (no test account, unusable test value)
  auth_problem     login / permission problem                          (sent back to the login page, 401 / 403)
  infrastructure   network / environment problem                       (connection refused, DNS, browser crashed)
  timeout          too slow, or possibly flaky                         (time limit hit)
  flaky            failed first, passed on retry (the first failure is kept)
  inconclusive     not enough evidence either way                      (the test checked nothing, unknown errors)
  test_mistake     the AI LOOKED at the screen: the website did the right thing, the test expected something else
Every finding gets a confidence and its evidence (screenshot, trace, console errors, failed requests).
Every suspected website bug also gets a bug report: steps to reproduce, expected, actual, severity, next action.
The rules decide first. Then the AI's eyes (backend/vision.py: before / after pictures of the failed test) may
clear a failure as a test mistake, or - for a test that was not a check of the website - raise it to "suspect"
(a person confirms). It never makes a proven website bug on its own, and never judges what a picture can't show
(JavaScript errors, HTTP status codes). The AI's text explanation never changes the category.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from ..llm import LLMError, ask_llm, extract_json, llm_enabled, load_prompt
from ..state import QAState

SEVERITY = {"http_status": "medium", "page_failed": "critical", "product_defect": "high", "console_error": "medium",
            "failed_request": "medium", "broken_image": "low", "test_defect": "low", "test_data": "low",
            "auth_problem": "high", "flaky": "low", "timeout": "medium", "infrastructure": "medium",
            "inconclusive": "low", "assertion_failure": "low", "locator": "low",
            "third_party": "low", "suspect": "low", "rule_violation": "medium", "layout": "medium",
            "test_mistake": "low"}
CATEGORY_NAME = {"product_defect": "Application defect (potential website bug)",
                 "assertion_failure": "Test assertion failure (exploratory expectation not met)",
                 "locator": "Locator / interaction failure (not proof of a website bug)",
                 "test_defect": "Test-script defect (the generated code is wrong)",
                 "test_data": "Test data / precondition problem", "auth_problem": "Authentication / permission failure",
                 "infrastructure": "Infrastructure failure (network / environment)", "timeout": "Timeout or possibly flaky",
                 "flaky": "Flaky (passed on retry)", "inconclusive": "Inconclusive (not enough evidence)",
                 "third_party": "Third-party resource failed (another website's script, tracker or ad)",
                 "suspect": "Suspect - needs a person to look (it did nothing, while exploring and in its test)",
                 "rule_violation": "Rule violation? (a common convention between fields the site does not keep)",
                 "test_mistake": "Test mistake - checked on screen: the website did the right thing"}
NEXT_ACTION = {
    "product_defect": "Reproduce it by hand with the steps below; if it happens, fix the website.",
    "assertion_failure": "Compare the expected result with what the website does (screenshot; what exploring saw is in "
                         "registry.json): if the website changed on purpose or the expectation was a wrong guess, "
                         "nothing to fix (run with 'Fresh start'); if not, it is a regression to fix.",
    "test_defect": "The generated script is wrong, not the website: run again with 'Fresh start' or let self-healing "
                   "repair it.",
    "locator": "Look at the screenshot: is the element there (renamed, moved, hidden, covered by something)? If a person "
               "can use it, the test's address of it is wrong (self-healing tries a repair); if not, it is a website "
               "problem to fix.",
    "test_data": "Give a usable test account / test values, then run again.",
    "auth_problem": "Check the test account (password, role, expiry) and that it may open these pages.",
    "infrastructure": "Check the website is reachable from this PC, then run again.",
    "timeout": "Run again; if it keeps timing out, the page is too slow - check its loading time.",
    "flaky": "Look for slow-loading elements, animations or race conditions on this page.",
    "inconclusive": "Look at the screenshot / trace; add a clear expected result for this feature.",
    "third_party": "Nothing to fix on this website - unless the page needs that resource (then load it from your own "
                   "site, or handle its failure). Often a blocked tracker or ad.",
    "suspect": "Use the control by hand: if it should do something, it is a bug to fix; if it is decoration, nothing "
               "to do.",
    "rule_violation": "Answer the question in the review: if it is allowed, it is remembered and not asked again; if "
                      "not, it becomes a bug to fix.",
    "test_mistake": "Nothing to fix on the website. The AI looked at the screenshots (see 'Seen on screen'); if you "
                    "disagree, open the screenshot and check it yourself.",
}


# the page a test saw was not the website but a block page of THIS computer's / network's security software
# (antivirus, firewall, company proxy) - e.g. Bitdefender: "This page has been blocked ... Network Attack Defense"
BLOCK_PAGE = re.compile(r"(this|the) (web ?)?page has been blocked|has blocked access to this (web ?)?page|"
                        r"security and compliance polic|endpoint security|web page blocked|"
                        r"access to this (web ?)?(site|page) (has been|is) (blocked|denied) by|"
                        r"blocked by your (organi[sz]ation|administrator|network)|zscaler|forcepoint|fortiguard|websense",
                        re.I)
BLOCKED_WHY = ("This computer's or network's security software (antivirus, firewall, company proxy) blocked the website "
               "during the test: the test saw its block page, not the website. Not a website bug - and this result "
               "proves nothing either way.")
BLOCKED_ACTION = ("The security software decides this, not the website: ask your IT team to allow this website for "
                  "testing (or test from a computer where it is allowed), then run again. Never switch the protection "
                  "off yourself.")

# a demo website that rebuilds its data while it is tested: the tests open a current item instead of a gone one, and
# say so (templates/conftest.py: "[data changed] <address> no longer exists - ...")
DATA_CHANGED = re.compile(r"\[data changed\] (\S+) no longer exists")
GONE_WHY = ("The website rebuilt its data while it was tested (demo shops do this): this item no longer existed - the "
            "tests used a current item of the same kind instead. A gone item that answers 'not found' (and the page's "
            "error about it) is no website bug.")
GONE_ACTION = "Nothing to fix on the website; the tests already checked a current item of the same kind."

PY_ERROR = r"SyntaxError|NameError|ImportError|ModuleNotFoundError|AttributeError|TypeError|IndentationError"
MISSING = re.compile(r"element\(s\) not found|resolved to 0 elements")
LOCATOR = re.compile(r"""locator\((["'])(.+?)\1\)""")
WAITED_FOR = re.compile(r"""waiting for locator\((["'])(.+?)\1\)""")  # (Playwright's call log names the element)


def _control_gone(err: str) -> bool:
    """The element the script works with is not on the page (renamed, moved or removed) - the script must be
    repaired. Not an expected TEXT that did not appear (locator('text=...')): that is a check of the website."""
    m = (WAITED_FOR.search(err) or LOCATOR.search(err)) if MISSING.search(err) else None
    return bool(m) and not m.group(2).lstrip().startswith("text=")


def _tagged(err: str, tag: str) -> str | None:
    """What the test SAID after [rule] / [rule-confirmed]: the error line ('AssertionError: [rule] ...'), not the line
    of source code pytest prints above it ('raise AssertionError(f"[rule] {R['question']} ...")')."""
    said = re.findall(rf"(?:AssertionError: |^E\s+)\[{re.escape(tag)}\]\s*(.+?)$", err, re.M)
    hits = said or [h for h in re.findall(rf"\[{re.escape(tag)}\]\s*(.+?)$", err, re.M) if "{" not in h]
    return hits[-1].strip() if hits else None


# what the AI's eyes may change (result["vision"], backend/vision.py)
SEEN_CAN_CLEAR = {"product_defect", "assertion_failure", "locator", "timeout", "suspect", "inconclusive"}
SEEN_CAN_RAISE = {"assertion_failure", "locator", "timeout", "inconclusive"}


def classify(r: dict) -> tuple[str, str, str]:
    """(category, why, confidence) for one failed / inconclusive test result: the rules, then what the AI saw on the
    screen (if it looked)."""
    cat, why, conf = _rule_classify(r)
    v = r.get("vision") or {}
    seen = f" On screen: {v['seen']}" if v.get("seen") else ""
    if v.get("verdict") == "test_mistake" and cat in SEEN_CAN_CLEAR:
        return "test_mistake", f"The AI looked at the screenshots: {v.get('reason', '')}{seen}"[:600], "medium"
    if v.get("verdict") == "website_bug" and cat in SEEN_CAN_RAISE:
        return "suspect", (f"The AI looked at the screenshots and thinks the website is wrong: {v.get('reason', '')}"
                           f"{seen} A person should confirm it.")[:600], "medium"
    if v.get("verdict") == "website_bug" and cat == "product_defect":
        return cat, f"{why} The AI saw it on the screenshots too: {v.get('reason', '')}{seen}"[:600], "high"
    return cat, why, conf


def _rule_classify(r: dict) -> tuple[str, str, str]:
    """(category, why, confidence) for one failed / inconclusive test result - from the fixed rules only."""
    err, etype = (r.get("error") or ""), (r.get("error_type") or "")
    if r.get("contract_id"):
        if r.get("outcome") == "failed" and etype == "AssertionError":
            return "product_defect", "An explicit QA contract expectation failed: " + err[:300], "high"
        if r.get("outcome") == "error":
            return "infrastructure", "The approved QA contract could not execute: " + err[:300], "high"
    if r.get("outcome") == "inconclusive":  # (with the test's own reason when it gave one: "Inconclusive: ...")
        return "inconclusive", (err if err.startswith("Inconclusive:") else
                                "The test ran without failing, but it checked nothing - a pass would prove nothing."), "high"
    if r.get("flaky"):
        return "flaky", "Failed first, passed on retry - timing or an unstable element.", "medium"
    if BLOCK_PAGE.search(err):  # (its page snapshot shows the security software's block page)
        return "infrastructure", BLOCKED_WHY, "high"
    if "[rule-confirmed]" in err:  # (you answered in the review: not allowed -> a bug of the website)
        q = _tagged(err, "rule-confirmed")
        return "product_defect", (q or "A rule you confirmed is not kept.")[:300], "high"
    if "[rule]" in err:  # a common convention between fields the site does not keep: a QUESTION, not a proven bug
        q = _tagged(err, "rule")
        return "rule_violation", (q or "A rule between fields was not kept.")[:300], "medium"
    if "gave no visible response" in err:  # (it did nothing while exploring either: no evidence what it should do)
        return "suspect", ("The control did nothing - while exploring and in its test. It may be broken, or only "
                           "decoration: a person should look."), "medium"
    if "blocked by the test sandbox" in err:
        return "test_defect", "The generated script tried something the sandbox forbids (it was stopped).", "high"
    # (a Python error of the script itself - not the WEBSITE's JavaScript 'TypeError' quoted in an assertion: "E
    # AssertionError: JavaScript errors on .../checkout: ERROR TypeError: Cannot read properties of null ...")
    if etype == "CollectionError" or re.fullmatch(PY_ERROR, etype) or (etype != "AssertionError" and re.search(
            rf"^E\s+({PY_ERROR})\b|fixture '.*' not found", err, re.M)):
        return "test_defect", "The generated script itself has a coding error.", "high"
    if etype == "TestTimeout" or "TestTimeout" in err:
        return "timeout", "The test hit its time limit and was stopped.", "medium"
    if re.search(r"no test account|TEST_USERNAME", err):
        return "test_data", "The test needs a test account, and none was given.", "high"
    if re.search(r"sent me back to the login page|login did not hold|did not work: the login form is still shown|"
                 r"HTTP 40[13]\b", err):
        return "auth_problem", "The login was refused or did not hold (sent back to the login page / 401 / 403).", "medium"
    if re.search(r"net::ERR_(?!BLOCKED_BY_CLIENT)|ECONNREFUSED|ECONNRESET|ETIMEDOUT|ENOTFOUND|socket hang up|"
                 r"Connection refused|HTTP 429|Too Many Requests|503 Service Unavailable|HTTP 503 from the website|"
                 r"Target page, context or browser has been closed", err):
        return "infrastructure", ("Network, rate limit or browser problem (the website refused or dropped the "
                                  "connection), not the website logic."), "medium"
    asserted = etype == "AssertionError" or "AssertionError" in err
    website_said = re.search(r"the website said|no visible response|caused JavaScript errors", err)
    if _control_gone(err) and not website_said:
        return "locator", ("The element the test uses was not found on the page (renamed, moved or removed) - not "
                           "proof of a website bug: self-healing tries to repair the script; if no replacement is "
                           "found, the feature may be gone."), "medium"
    if r.get("file") == "test_learned.py" and asserted and not website_said:
        return "assertion_failure", ("The control did not do what it did while exploring - an exploratory "
                                     "expectation, not a written rule: the website may have changed."), "low"
    if r.get("file") == "test_flows_ai.py" and asserted and not website_said and "strict mode violation" not in err:
        return "assertion_failure", ("An AI-written expectation was not met. The AI wrote it from the page "
                                     "descriptions - it was never seen while exploring - so it may be a wrong guess "
                                     "(e.g. a message the website shows differently). Review it before calling it a "
                                     "bug."), "low"
    if "intercepts pointer events" in err or "covered by another part of the page" in err:
        return "locator", ("Another part of the page lay over the element when the test clicked it (a banner, a sticky "
                           "header, an animation) - review the screenshot: if a person can't click it either, it is a "
                           "website problem."), "medium"
    if "the page took too long to open" in err:
        return "timeout", "The page took too long to open - a slow site or a slow connection.", "medium"
    if re.search(r"strict mode violation|waiting for (locator|get_by)|resolved to 0 elements|element is not (visible|attached)"
                 r"|was not found on the page", err):
        return "locator", ("The element the test uses was not found or could not be used (not unique, hidden, "
                           "detached) - the script or the page structure changed; not proof of a website bug."), "medium"
    if "showed nothing (no menu / details)" in err:  # (a hover menu: the sub-menu is in the page, hidden)
        return "assertion_failure", ("Pointing at the menu (or clicking its button) showed nothing in the test - its "
                                     "sub-menu is in the page; some menus need a real mouse. Review it by hand before "
                                     "calling it a bug."), "low"
    if "Timeout" in etype or "Timeout" in err:
        return "timeout", "Page or element took too long - slow site, or a wait in the script is wrong.", "low"
    if etype == "AssertionError" or "AssertionError" in err or "expect(" in err:
        # the check itself failed: the website did not behave as expected. Built-in checks are precise;
        # an AI-written check may itself be wrong, so it gets less confidence.
        conf = "medium" if r.get("file") == "test_flows_ai.py" else "high"
        return "product_defect", "The website did not behave as expected.", conf
    return "inconclusive", "Unexpected failure - the evidence does not show whose problem it is. Needs a human look.", "low"


LOCATOR_TROUBLE = re.compile(r"strict mode violation|waiting for (locator|get_by)|resolved to 0 elements|"
                             r"element is not (visible|attached)|was not found on the page")


def healable(f: dict) -> bool:
    """Can a repair of the SCRIPT fix this failure (self-healing)? A broken script or a lost element - also when the AI
    looked at the screenshots and called it a test mistake because of such an element ('text=Blue Top' matched the
    card's name twice: automationexercise.com, your own test - it was never repaired)."""
    return f.get("source") == "test" and (f.get("category") in ("test_defect", "locator") or (
        f.get("category") == "test_mistake" and bool(LOCATOR_TROUBLE.search(f.get("error") or ""))))


def _short_error(err: str | None) -> str:
    if not err:
        return ""
    lines = [l for l in err.splitlines() if l.strip()]
    key = [l for l in lines if l.lstrip().startswith("E ")]
    return "\n".join((key or lines)[-6:])[:600]


def _severity(cat: str, r: dict, err: str) -> tuple[str, str | None]:
    """Severity of a test finding (fixed rules), and a better explanation when the rule knows one."""
    sev, why, test = SEVERITY[cat], None, r["test"]
    if cat != "product_defect":
        return sev, why
    if re.search(r"console|image|maxlength", test):
        sev = "medium" if "console" in test else "low"  # real bugs, but not release blockers
    if test.startswith("test_link[ext_") or test.startswith("test_button_click["):
        sev = "medium"  # broken external link / button error: real problem, not a release blocker
    if test.startswith("test_data_"):
        if "XSS" in err:
            sev, why = "high", "Text typed into an input box ran as a script (XSS security risk)."
        else:  # input validation gaps are real but rarely release blockers
            sev, why = "medium", "An input box does not handle this test value as expected (validation gap)."
    if test.startswith("test_link[int_"):
        why = "A link on this website points to a page that does not work (broken internal link)."
    if "intercepts pointer events" in err or "covered by another part of the page" in err:
        sev = "medium"  # a real usability problem, but not a release blocker
    if test.startswith("test_section_link["):
        sev, why = "medium", "A link points to a part of a page (#section) that does not exist - clicking it goes nowhere."
    if "no error message was shown" in err:
        sev, why = "medium", ("The empty form was not sent, but no message tells the visitor what is missing "
                              "(a usability problem).")
    if "the same price, written differently" in err:  # ('$46.5' on the card, '$46.50' on its page)
        sev, why = "low", "The same price is written differently on the item's card and on its page (a display slip)."
    return _business_impact(sev, r, err), why


# What the bug costs, not how it was found (the way TestOptim sorts them): money or a blocked core journey first.
MONEY_ERR = re.compile(r"total|price|amount|subtotal|\$|€|£|₹|quantity in the cart|cart total|went \d", re.I)
CORE_JOURNEY = re.compile(r"log ?in|sign ?up|regist|checkout|check out|payment|\bpay\b|cart|basket|order", re.I)
COSMETIC = re.compile(r"outside the screen|horizontal scroll|written differently|broken pictures", re.I)


def _business_impact(sev: str, r: dict, err: str) -> str:
    """The severity by business impact (website bugs only; a test problem keeps its own):
    critical  money / a total is wrong, or a core journey (login, sign-up, cart, checkout, payment, orders) is blocked
    high      another core flow is broken, or a required box is not checked
    medium    other wrong behaviour that does not block a flow
    low       cosmetic (layout, pictures, a price written differently)"""
    test, said = r.get("test") or "", err.lower()
    if "javascript error" in said or "js exception" in said or test.startswith("test_no_console_errors"):
        return sev  # (a coding error on the page: what it breaks is checked by the tests of the features it hits)
    if COSMETIC.search(said) or test.startswith("test_images_load"):
        return "low"
    if MONEY_ERR.search(said) and re.search(r"cart|total|price|order", f"{test} {said}", re.I):
        return "critical"
    if test.startswith("test_journey") and CORE_JOURNEY.search(said + " " + test):
        return "critical"
    if re.search(r"required|left empty|empty form was accepted", said) and "no error message was shown" not in said:
        return "high"
    return sev


def _own_host(url: str, host: str) -> bool:
    """Is this request to the website itself (its host or a sub-domain)? Its HOST decides - not the whole address:
    a tracker's address often carries the page's address in its query ('...optimizely.com/event?n=https://site/')."""
    h, base = (urlparse(url.strip()).hostname or "").lower(), host.lower().removeprefix("www.")
    return bool(h) and (h == base or h.endswith("." + base))


# (a comma does not end an address: Google Fonts' 'css?family=Roboto:400,300,700' - three fonts were three findings)
URL_IN_TEXT = re.compile(r"https?://\S+?(?=['\"\s)]|$)")
# an insecure (http://) style / font / picture on an https:// page - the same rule as the tests' (templates/conftest.py)
PASSIVE_MIXED = re.compile(r"Mixed Content:.*\binsecure (stylesheet|font|image|video|audio|favicon|element)\b", re.I)


def same_message(text: str) -> str:
    """A message without the addresses in it: 'Mixed Content: The page at <url> was loaded over HTTPS, but requested
    <url>' is ONE problem on every page that shows it (automationexercise.com: 73 findings for one)."""
    return URL_IN_TEXT.sub("<address>", text or "").strip()


def _same_problem(i: dict) -> str:
    """One problem seen on many pages is one finding: a failed request counts by its error and address WITHOUT the
    query (a tracker's every call has its own time stamp / visitor id); a console error by its words without the
    addresses in them."""
    if i["type"] == "console_error":
        return same_message(i["detail"])
    if i["type"] != "failed_request":
        return i["detail"]
    err, _, url = i["detail"].partition("→")
    return f"{err.strip()} → {url.strip().split('?')[0]}"


def _one_per_problem(failures: list[dict]) -> list[dict]:
    """The same coding error on many pages ('no JavaScript errors' failed on 17 pages with one 'Mixed Content' message)
    is ONE finding, with the pages it was seen on - not 17. Other findings are kept as they are."""
    out, first = [], {}
    for f in failures:
        if not (f.get("test") or "").startswith("test_no_console_errors") or f["category"] != "product_defect":
            out.append(f)
            continue
        said = "\n".join((f.get("error") or "").splitlines()[1:]) or f.get("error") or ""  # (without 'errors on <url>:')
        key = same_message(re.sub(r"\(after: [^)]*\)", "", said))
        if key in first:
            g = first[key]
            g["pages"].append(f.get("page_url"))
            g["explanation"] = f"{g['base_explanation']} Seen on {len(g['pages'])} pages."
            g["evidence"] += [x for x in f.get("evidence") or [] if x not in g["evidence"]][:2]
            continue
        f = dict(f, pages=[f.get("page_url")], base_explanation=f.get("explanation") or "")
        first[key] = f
        out.append(f)
    for n, f in enumerate(out):
        f["id"] = n
        f.pop("base_explanation", None)
    return out


def _gone_items(run_dir) -> set[str]:
    """The item addresses the tests found gone (the website rebuilt its data): from pytest's own output."""
    out = set()
    for f in Path(run_dir).glob("*_pytest_output.txt") if run_dir else []:
        try:
            out.update(DATA_CHANGED.findall(f.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            pass
    return out


def _case_of(r: dict, cases: list[dict]) -> dict | None:
    from ..excel import case_hits
    return next((c for c in cases if r in case_hits(c, [r])), None)


def failure_analysis_agent(state: QAState) -> QAState:
    if state.get("target_type") == "mobile":
        from ..android_reporting import analyze
        return analyze(state)
    cases = state.get("test_cases", [])
    pages = {p["url"]: p for p in state.get("app_map", [])}
    failures = []
    from ..vision import review_results
    review_results(state)  # the AI looks at the failed tests' screenshots first (result["vision"]; VISION=off: nothing)
    # once security software blocked the website, an 'HTTP 403' is its block page too - not the login's answer
    blocked = any(BLOCK_PAGE.search(r.get("error") or "") for r in state.get("results", []))
    for r in state.get("results", []):
        if r["outcome"] not in ("failed", "error", "inconclusive"):
            continue
        cat, why, conf = classify(r)
        err = r.get("error") or ""
        if blocked and cat == "auth_problem" and re.search(r"HTTP 403\b", err):
            cat, why, conf = "infrastructure", BLOCKED_WHY, "medium"
        sev, better = _severity(cat, r, err)
        why = better or why
        if r["nodeid"] in state.get("unhealable", []):
            last = next((h for h in reversed(state.get("healing_log", [])) if h.get("nodeid") == r["nodeid"]), {})
            why = (f"A repair of the script was tried, run again and undone ({last.get('why') or 'it did not help'}) - "
                   "the first failure stands. Needs human review." if last.get("status") in ("reverted", "still failing")
                   else "Self-healing could not find a replacement for the element this test uses - "
                        "the feature may have been removed or broken. Needs human review.")
            sev, conf = "medium", "low"
        case = _case_of(r, cases) or {}
        page = pages.get(case.get("url")) or {}
        evidence = [x for x in (r.get("screenshot"), r.get("trace")) if x]
        if page.get("console_errors"):
            evidence.append(f"{len(page['console_errors'])} browser console error(s) on this page while crawling")
        if page.get("failed_requests"):
            evidence.append(f"{len(page['failed_requests'])} failed request(s) on this page while crawling")
        f = {
            "id": len(failures), "source": "test", "nodeid": r["nodeid"], "test": r["test"], "file": r["file"],
            "page_url": r.get("url") or case.get("url"), "category": cat, "category_name": CATEGORY_NAME[cat],
            "severity": sev, "confidence": conf, "explanation": why, "error": _short_error(err),
            "screenshot": r.get("screenshot"), "trace": r.get("trace"), "evidence": evidence,
            "tc_id": case.get("tc_id"), "next_action": BLOCKED_ACTION if why == BLOCKED_WHY else NEXT_ACTION[cat],
        }
        if r.get("vision"):  # what the AI saw on the screenshots (its verdict, the screen's words, its reason)
            f["seen_by_ai"] = r["vision"]
        if cat == "product_defect":  # a bug report a developer can act on
            f["bug"] = {"title": case.get("title") or r["test"], "route": urlparse(case.get("url") or "").path or "/",
                        "feature": case.get("feature") or "", "steps": case.get("steps") or [],
                        "expected": case.get("expected") or "", "actual": _short_error(err).replace("E   ", "")[:400],
                        "severity": sev, "confidence": conf}
        failures.append(f)

    failures = _one_per_problem(failures)
    host = urlparse(state.get("url") or "").hostname or ""
    gone = _gone_items(state.get("run_dir"))
    same: dict[tuple, tuple] = {}  # the same problem on many pages (a script every page loads): ONE finding
    for i in state.get("crawl_issues", []):
        # an item page that was gone by the time it was tested (the website rebuilt its data): its 'not found' and the
        # page's error about it are no bug - a server ERROR (HTTP 5xx) still is one, gone item or not
        stale = i["url"] in gone and (i["type"] == "console_error" or (
            i["type"] == "failed_request" and bool(re.match(r"HTTP 4(04|10)\b", i["detail"]))))
        key = (i["type"], _same_problem(i), stale)
        if key in same:
            f, base = same[key]
            if i["url"] not in f["pages"]:  # (one page that logs the error 38 times is ONE page)
                f["pages"].append(i["url"])
                f["explanation"] = f"{base} Seen on {len(f['pages'])} pages."
            continue
        third_party = i["type"] == "failed_request" and host and not _own_host(i["detail"].split("→")[-1], host)
        # a page that did not answer in time is no error page: slow website, network or a busy test machine
        slow = i["type"] == "page_failed" and "timeout" in i["detail"].lower()
        # an API address the crawl opened from a link (it answers POST / PUT, never a page visit) - and a server that
        # said 'busy' (503 / 429: it limits how fast it is asked) - no broken page either
        api = i["type"] in ("page_failed", "failed_request") and bool(re.match(r"HTTP 405\b", i["detail"]))
        # (and what its error page shows - /api/createAccount's own styles and scripts: no page a visitor uses)
        api_page = not api and (pages.get(i["url"]) or {}).get("status") == 405
        busy = i["type"] in ("page_failed", "failed_request") and bool(re.match(r"HTTP (503|429)\b", i["detail"]))
        # an insecure (http) style / font / picture on an https page: real, but cosmetic - the page still works
        mixed = i["type"] == "console_error" and bool(PASSIVE_MIXED.search(i["detail"]))
        # another website's resource (ERR_BLOCKED_BY_ORB, a blocked tracker / ad): never this website's bug
        cat = "infrastructure" if stale or api or api_page or busy else "timeout" if slow else "third_party" \
            if third_party else "product_defect"
        sev = "low" if third_party or stale or api or api_page or busy or mixed else SEVERITY[
            "timeout" if slow else i["type"]]
        failures.append({
            "id": len(failures), "source": "crawler", "test": i["type"], "file": None,
            "page_url": i["url"], "category": cat, "category_name": CATEGORY_NAME[cat],
            "severity": sev, "confidence": "low" if third_party or slow or i["type"] == "console_error" else "high",
            "explanation": GONE_WHY if stale else
            "The page did not load within the time limit - not proof of an error page." if slow else
            ("An API address (found as a link): it answers its own method (POST / PUT), not a page visit - HTTP 405 "
             "is right, not a broken page.") if api else
            ("Seen on an API address (it answers POST / PUT, not a page visit): its error page is not a page of the "
             "website a visitor uses.") if api_page else
            ("The page asks for a style / font / picture over insecure http:// on an https:// page, so the browser "
             "blocks it: the page may look a little different, nothing a visitor does breaks. Load it over "
             "https:// (one change for the whole site).") if mixed else
            ("The website's server said it was busy (HTTP 503 / 429) - often because it limits how fast it is asked. "
             "Check it again later; one busy answer is no proof of a bug.") if busy else {
                "http_status": "The server returned an error status, while the browser rendered usable application controls. Functional testing continued.",
                "page_failed": "Page did not load or returned an error status.",
                "console_error": "The browser console reported an error on this page.",
                "failed_request": "A resource (API, script, image, style) failed to load"
                                  + (" - from another website (third party)." if third_party else "."),
                "broken_image": "An image on the page is broken.",
                "layout": "At phone width (390 px) the page does not fit: it scrolls sideways, or a control is cut "
                          "off or covered.",
            }[i["type"]], "error": i["detail"], "screenshot": i.get("screenshot"),
            "evidence": [x for x in (i.get("screenshot"),) if x], "next_action": GONE_ACTION if stale else NEXT_ACTION[cat],
            "pages": [i["url"]],
        })
        same[key] = (failures[-1], failures[-1]["explanation"])

    # Optional: the AI explains test failures in plain English. It can SUGGEST another category (shown as a
    # suggestion), but the category, severity and verdict stay the ones the rules decided.
    test_failures = [f for f in failures if f["source"] == "test"]
    if llm_enabled() and test_failures:
        try:
            brief = [{"id": f["id"], "test": f["test"], "category": f["category"], "error": f["error"]}
                     for f in test_failures[:40]]
            for upd in extract_json(ask_llm(load_prompt("failure_analysis").format(failures=json.dumps(brief, indent=1)),
                                            agent="failure_analysis")):
                f = failures[int(upd["id"])]
                if upd.get("explanation"):
                    f["ai_explanation"] = str(upd["explanation"])[:400]
                if upd.get("category") in CATEGORY_NAME and upd["category"] != f["category"]:
                    f["ai_suggested_category"] = upd["category"]
        except (LLMError, json.JSONDecodeError, ValueError, KeyError, IndexError, TypeError) as e:
            print(f"  [failure-analysis] LLM explanation skipped: {e}")

    Path(state["run_dir"], "failures.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")
    counts = {}
    for f in failures:
        counts[f["category"]] = counts.get(f["category"], 0) + 1
    log = state.get("log", []) + [f"Failure analysis: {len(failures)} findings {counts or ''}."]
    return {"failures": failures, "log": log, "results": state.get("results", [])}  # (with what the AI saw on screen)
