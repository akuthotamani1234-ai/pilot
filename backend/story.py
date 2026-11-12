"""Plain-English explanations for the final report: the one-line verdict, "what works well",
and "why it matters" for every problem. No technical words, so anyone can read the report."""
import re

VERDICT_STORY = {
    "Ready": ("🎉", "Ready to release",
              "Everything that ran in this test passed. That is not a claim that every page or feature of the site was tested."),
    "Ready with Risks": ("⚠️", "Almost ready",
                         "Most things that ran work. We found {fixes} thing(s) worth fixing, but nothing that stops a release."),
    "Not Ready": ("🛑", "Not ready yet",
                  "We found {blockers} serious problem(s) that visitors will notice. Please fix those first."),
    "Insufficient Evidence": ("❔", "We couldn't test enough", "{reason}"),
}


def headline(verdict: str, fixes: list[dict], reasons: list[str], *, partial_coverage: bool = False) -> dict:
    emoji, title, text = VERDICT_STORY.get(verdict, ("ℹ️", verdict, ""))
    blockers = sum(1 for x in fixes if x.get("priority") in ("critical", "high"))
    text = text.format(fixes=len(fixes), blockers=blockers or "some", reason=(reasons or ["Not enough could be tested."])[0])
    if partial_coverage and verdict != "Insufficient Evidence":
        text += " Coverage was incomplete: unvisited pages, blocked or skipped checks, and limits are listed in the report."
    return {"emoji": emoji, "title": title, "text": text}


def why_it_matters(f: dict, title: str) -> str:
    """One sentence a non-developer understands: what happens to visitors because of this problem."""
    t, cat, err = f.get("test") or "", f.get("category"), f.get("error") or ""
    if cat == "test_defect":
        return "This is a problem in our automated test, not in your website - no action needed on the website."
    if cat == "test_mistake":
        return ("The AI looked at the screenshots: your website did the right thing, our test expected something "
                "else - no action needed on the website.")
    if cat == "locator":
        return ("Our test could not find or use this element - that alone does not show a website problem; the "
                "screenshot shows whether a person could use it.")
    if cat == "flaky":
        return "It sometimes works and sometimes not, so some visitors will see it fail now and then."
    if cat in ("infrastructure", "timeout"):
        return "The website was slow or could not be reached during the test - check it is online and fast enough."
    if cat == "auth_problem":
        return "Signed-in visitors may be sent back to the login page or refused access."
    if cat == "test_data":
        return "Part of the website could not be tested because test data (e.g. a test account) was missing."
    if cat == "inconclusive":
        return "We could not tell whether this works - it needs a human look before you rely on it."
    if t == "page_failed":
        return "Visitors can't open this page at all - they see an error instead."
    if t == "broken_image" or "image" in title.lower():
        return "Visitors see a broken picture, which makes the site look unfinished."
    if t == "failed_request" or title.lower().startswith("missing file"):
        return "A file the page needs is missing, so part of the page may look wrong or not work."
    if t == "console_error" or "javascript" in title.lower():
        return "A coding error on the page - some buttons or features may silently not work."
    if t.startswith("test_link[int_"):
        return "Visitors who click this link land on an error page."
    if t.startswith("test_link[ext_"):
        return "A link to another website is broken - visitors who click it get an error."
    if "XSS" in err or "runs as a script" in title.lower():
        return "Security risk: an attacker could run their own code in your visitors' browsers."
    if "empty submission" in title.lower() or "required" in t:
        return "People can send the form without filling it in, so you receive empty or useless data."
    if "invalid" in title.lower() or "email" in title.lower():
        return "Wrong data (like a fake email address) can be entered and saved."
    if "more characters than its limit" in title.lower() or "too many characters" in title.lower():
        return "Very long text is accepted, which can break the layout or the database."
    if "rejects a normal" in title.lower():
        return "Real users who type a normal value are blocked - they can't complete the form."
    if t.startswith("test_button_click["):
        return "Clicking this button causes an error - the feature behind it may not work."
    return "The website did not behave the way a visitor would expect here."


def working_well(app_map: list[dict], results: list[dict], cases: list[dict], m: dict | None = None) -> list[str]:
    """Good news first: what we checked and found working, in plain words (only things that were tested). The
    numbers are the report's own (metrics), each one says what it counts."""
    out = []
    ok_pages = [p for p in app_map if not p.get("error") and (p.get("status") or 0) < 400]
    if app_map:
        out.append(f"All {len(app_map)} pages open without errors" if len(ok_pages) == len(app_map)
                   else f"{len(ok_pages)} of {len(app_map)} pages open without errors")

    def count(prefix: str) -> tuple[int, int]:
        rs = [r for r in results if r["test"].startswith(prefix)]
        return sum(r["outcome"] == "passed" for r in rs), sum(r["outcome"] in ("passed", "failed", "error") for r in rs)

    if m:
        h = m["headline"]
        if h["of"]:
            out.append(f"{h['passed']} of {h['of']} functional test cases passed" if h["passed"] < h["of"]
                       else f"All {h['of']} functional test cases passed")
        for w in m["workflows"]["list"]:  # each end-to-end workflow, with the steps it verified
            if w["status"] == "Passed":
                out.append(f"Workflow works: {w['title'][:90]}"
                           + (f" ({len(w['steps_verified'])} steps verified)" if w["steps_verified"] else ""))
    ok, n = count("test_link[")
    if n:
        out.append(f"{ok} of {n} links work" if ok < n else f"All {n} links work")
    ok, n = count("test_button_click[")
    if ok:
        out.append(f"{ok} of {n} buttons can be clicked without errors" if ok < n else f"All {n} buttons can be clicked without errors")
    ok, n = count("test_no_console_errors")
    if ok:
        out.append(f"No coding errors on {ok} of {n} pages" if ok < n else f"No coding errors on any of the {n} pages checked")
    ok, n = count("test_images_load")
    if ok:
        out.append(f"Pictures load on {ok} of {n} pages" if ok < n else "All pictures load")
    ok, n = count("test_data_")
    if n:
        boxes = len({x.get("field") for c in cases for x in [c] + list(c.get("checks") or []) if x.get("type") == "data"})
        out.append(f"Input boxes handled {ok} of {n} unusual values correctly ({boxes} box(es) checked)")
    forms_ok = [r for r in results if re.match(r"test_form\d+_required_validation", r["test"]) and r["outcome"] == "passed"]
    if forms_ok:
        out.append(f"{len(forms_ok)} form(s) correctly refuse to be sent empty")
    return out
