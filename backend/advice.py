"""'What you should fix' - turns findings into concrete, prioritised fix advice.

Rules first (always works, free). If an LLM is configured, it rewrites each fix to be specific
to the error; if the LLM is busy or fails, the rule-based advice is kept.
Written to runs/<run_id>/fixes.json and shown in the UI.
"""
import json
import re
from pathlib import Path

from .codefix import Context, ai_fill, code_for
from .llm import LLMError, ask_llm, extract_json, llm_enabled, load_prompt
from .story import why_it_matters

PRIORITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _rule(f: dict) -> tuple[str, str] | None:
    """(title, fix) for one finding, or None to skip it."""
    t, err = f["test"], f.get("error") or ""
    if f["source"] == "crawler":
        if f.get("category") == "third_party":
            return None  # (another website's script / tracker: nothing to fix on this website)
        if t == "layout":
            return (f"Phone width: {err[:120]}",
                    "Check the page at 390 px wide: give wide elements max-width: 100% (or let tables scroll inside "
                    "their own box), and keep buttons inside the screen and above other layers.")
        if t == "page_failed":
            return (f"Page does not load ({err})",
                    "Restore this page, or remove / correct every link that points to it.")
        if t == "failed_request":
            m = re.match(r"HTTP (\d+)\s*→\s*(\S+)", err)
            if m and m.group(1) == "404":
                return (f"Missing file: {m.group(2)}",
                        "Upload the missing file, or fix the path that references it in the page's HTML/CSS/JS.")
            if m:
                return (f"Request fails with HTTP {m.group(1)}: {m.group(2)}",
                        "Check the server / API behind this URL - it returns an error for normal visitors.")
            return (f"Resource failed to load: {err[:120]}",
                    "Check the URL is reachable (network, CORS, mixed http/https content).")
        if t == "broken_image":
            return (f"Broken image: {err}", "Add the image file or correct the <img src=...> path.")
        if t == "console_error":
            if err.startswith("Failed to load resource"):
                return None  # the same problem is already reported as a failed request
            m = re.search(r"(\w+) is not defined", err)
            if m:
                return (f"JavaScript error: '{m.group(1)}' is not defined",
                        f"The page calls '{m.group(1)}' but it doesn't exist. Fix the typo, define the function, "
                        "or load the script that defines it before this code runs.")
            return (f"JavaScript console error: {err[:120]}",
                    "Open the browser DevTools console on this page and fix the reported error.")
        return None

    cat = f["category"]
    if cat in ("third_party", "test_mistake"):
        return None  # (another website's tracker / our own test's mistake: listed with the findings, nothing to fix)
    if cat == "rule_violation":
        return (f"Question: {f.get('explanation') or t}",
                "A common rule between two fields is not kept. If your website allows it, answer 'allowed' in the "
                "review (it is not asked again); if not, add the check - in the page and on the server.")
    if cat == "suspect":
        return (f"Check by hand: a control that does nothing ({t})",
                "It did nothing while exploring and in its test. Use it yourself: if it should do something, fix it; "
                "if it is only decoration, nothing to do.")
    if cat == "test_defect":
        return (f"Test script needs attention: {t}",
                "This is a problem in the generated TEST, not necessarily the website. Check the error; if the "
                "page changed on purpose, run again with --fresh to regenerate the tests.")
    if cat == "locator":
        if "intercepts pointer events" in err or "covered by another part of the page" in err:
            return ("Check: another part of the page lies over a button / link",
                    "The test could not click it because something lay on top of it (a banner, a sticky header, an "
                    "animation). Look at the screenshot: if a person can't click it either, move or shrink the "
                    "covering element (or give it 'pointer-events: none' if it is only decoration).")
        return (f"The test could not find or use an element: {t}",
                "Look at the screenshot: if the element is there and a person can use it, only the test's address of "
                "it changed (self-healing tries to repair it; else run again with 'Fresh start'). If it is gone or "
                "hidden, the feature may be broken.")
    if cat == "inconclusive" and t.startswith("test_data_"):
        return ("Not known: does the website refuse wrong values in an input box?",
                "The box itself does not check the value (it is a plain text box) and forms are never sent, so the "
                "website's own check was not tested. If the value must be refused, let the box say what it is "
                "(type=\"email\", a pattern, min / max) - then the browser checks it too.")
    if cat == "flaky":
        return (f"Unstable behaviour: {t}",
                "Failed once and passed on retry. Look for slow-loading elements, animations or race conditions.")
    if cat == "infrastructure":
        return (f"Network problem: {t}",
                "Check the site is reachable from this PC, then run the test again.")
    if cat == "timeout":
        return (f"Too slow / timed out: {t}",
                "Run again; if it keeps timing out, check the page's loading time (or raise PAGE_TIMEOUT_MS in .env).")
    if cat == "auth_problem":
        return (f"Login / permission problem: {t}",
                "Check the test account (password, role, expiry) and that it may open this page.")
    if cat == "test_data":
        return (f"Test data missing: {t}", "Give a usable test account / test values and run again.")
    if cat == "inconclusive":
        return (f"Not enough evidence: {t}",
                "This test could not show whether the feature works. Look at its screenshot / trace and describe "
                "the expected result for this feature (Advanced settings → workflows).")
    # product defects found by tests
    if "intercepts pointer events" in err or "covered by another part of the page" in err:
        m = re.search(r"\((<[a-z]+[^>]{0,80}>) is on top of it\)|(<[a-z]+[^>]{0,80}>)[^\n]{0,20}intercepts pointer events", err)
        layer = (m.group(1) or m.group(2)) if m else "another element"
        return ("A button / link is covered by another part of the page",
                f"{layer} lies on top of it, so clicks land on that layer instead. Give the covering element "
                "'pointer-events: none' (if it is only decoration), or move / shrink it, or raise the button with z-index.")
    if t.startswith("test_data_"):  # many-values-per-input-box tests
        if "XSS" in err:
            return ("Typed text runs as a script (XSS security risk)",
                    "Never insert what users type into the page as HTML: escape it (show it as text) everywhere it appears.")
        if "JavaScript errors" in err:
            return ("Typing into an input box causes JavaScript errors",
                    "Type the value shown in the details into this box with DevTools open, and fix the error it triggers.")
        if "more than its limit" in err:
            return ("An input box accepts more characters than its limit",
                    "Enforce the length limit (maxlength attribute) and check it again on the server.")
        if "valid value was rejected" in err:
            return ("An input box rejects a normal, valid value",
                    "Check the box's rules (type, pattern, min/max length): a normal value like the one in the details "
                    "should be accepted.")
        if "invalid value was accepted" in err:
            return ("An input box accepts invalid data",
                    "Add validation: the right input type (email, url, number), required / minlength / maxlength / pattern, "
                    "and the same checks on the server.")
    if t.startswith("test_section_link["):
        m = re.search(r"points to #(\S+) on", err)
        return (f"A link goes nowhere: section #{m.group(1) if m else '…'} does not exist",
                "Give the part of the page this link should jump to that id (e.g. <section id=\"" + (m.group(1) if m else "name")
                + "\">), or change the link's href to a section that exists.")
    if t.startswith("test_link[int_"):
        return ("Broken internal link", "A link on this site points to a page that returns an error. "
                                        "Fix the link's href or restore the target page.")
    if t.startswith("test_link[ext_"):
        return ("Broken external link", "This link goes to another website that returns an error. "
                                        "Update the URL or remove the link.")
    if ("required" in t or "empty" in t) and "no error message was shown" in err:
        return ("An empty form shows no error message",
                "Show a message next to each required box that is left empty (e.g. 'This field is required'), "
                "so visitors know what is missing.")
    if "required" in t or "empty" in t:
        return ("Form accepts an empty submission",
                "Mark the required fields with the `required` attribute (and remove `novalidate` from the form), "
                "and validate on the server too.")
    if "email" in t:
        return ("Form accepts an invalid email address",
                "Use <input type=\"email\"> and validate the email format on the server.")
    if "maxlength" in t:
        return ("Text field accepts too many characters", "Add a maxlength attribute and enforce it on the server.")
    if "console" in t:
        return ("JavaScript errors on the page", "Fix the errors shown in the browser DevTools console.")
    if t.startswith("test_button_click["):
        return ("A button causes an error when clicked",
                "Click this button manually with DevTools open and fix the error it triggers.")
    if "image" in t:
        return ("Images do not load", "Add the missing image files or fix their src paths.")
    return (f"Website did not behave as expected: {t}", f["explanation"])


def _where(f: dict, page_of_file: dict[str, str]) -> str:
    """The page (or link) the developer should look at - not where the browser ended up after the test."""
    if f["source"] == "crawler":
        return f.get("page_url") or ""
    if f["test"].startswith("test_link["):  # the broken link itself
        m = re.search(r"HTTP \d+\s+(\S+)|could not be opened: (\S+)", f.get("error") or "")
        if m:
            return m.group(1) or m.group(2)
    return page_of_file.get(f.get("file") or "", f.get("page_url") or "")


def build_fixes(state: dict, *, enrich: bool = True) -> list[dict]:
    ctx = Context(state)
    page_of_file = {name: p["url"] for name, p in ctx.by_file.items()}
    fixes, seen, fails = [], {}, {}
    for f in state.get("failures", []):
        r = _rule(f)
        if r is None:
            continue
        title, fix = r
        case = ctx.case(f) if f["test"].startswith("test_data_") else None
        if case and case.get("field"):  # name the exact box: "The 'Email' box accepts invalid data"
            box = f"the '{case['field']}' box"
            title = re.sub(r"\b[Aa]n input box", box[0].upper() + box[1:], title).replace("into an input box", f"into {box}")
        where = _where(f, page_of_file)
        key = (title, where)
        if key in seen:
            seen[key]["count"] += 1
            fails[id(seen[key])].append(f)
            continue
        item = {"id": len(fixes), "priority": f["severity"], "category": f["category"], "title": title,
                "why": why_it_matters(f, title),
                "where": where, "fix": fix, "error": (f.get("error") or "")[:300],
                "screenshot": f.get("screenshot"), "source": "rules", "count": 1}
        seen[key] = item
        fails[id(item)] = [f]
        fixes.append(item)

    # "code now -> change to" for each fix (built-in rules first, the AI fills in the rest below)
    for x in fixes:
        try:
            x["code"] = code_for(fails[id(x)], ctx)
        except Exception as e:  # a code suggestion must never break the report
            print(f"  [advice] no code suggestion for '{x['title']}': {str(e)[:100]}")
            x["code"] = None

    fixes.sort(key=lambda x: (PRIORITY.get(x["priority"], 9), x["category"] != "product_defect"))
    for n, x in enumerate(fixes):
        x["id"] = n

    if enrich and llm_enabled() and fixes:
        try:
            brief = [{"id": x["id"], "problem": x["title"], "page": x["where"], "error": x["error"]} for x in fixes[:20]]
            for upd in extract_json(ask_llm(load_prompt("fix_advice").format(fixes=json.dumps(brief, indent=1)),
                                            agent="fix_advice")):
                x = fixes[int(upd["id"])]
                if (upd.get("fix") or "").strip():
                    x["fix"], x["source"] = upd["fix"].strip(), "ai"
        except (LLMError, json.JSONDecodeError, ValueError, KeyError, IndexError, TypeError) as e:
            print(f"  [advice] AI advice skipped, using built-in advice: {str(e)[:150]}")
    if enrich:
        ai_fill(fixes)

    Path(state["run_dir"], "fixes.json").write_text(json.dumps(fixes, indent=2), encoding="utf-8")
    return fixes
