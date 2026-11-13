"""Separate rendered application usability from HTTP transport correctness."""
import re

ERROR_PAGE = re.compile(r"(?:^|\b)(?:404(?:\s+|[:\-])*(?:not found)?|page not found|"
                        r"access denied|forbidden|service unavailable|internal server error|"
                        r"this (?:page|site) (?:does not|doesn't) exist)\b", re.I)
RENDER_EVIDENCE_JS = r"""() => {
  const visible = e => !!(e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
  const main = document.querySelector('main,[role=main],#root,#app,[data-reactroot]') || document.body;
  const title = document.title || '';
  const headings = [...document.querySelectorAll('h1,h2,[role=alert]')].filter(visible)
    .map(e => (e.innerText || '').trim()).join(' ').slice(0,300);
  const error = /(^|\b)(404(\s|:|-)*(not found)?|page not found|access denied|forbidden|service unavailable|internal server error)\b/i;
  return {
    application_mount: !!document.querySelector('#root,#app,[data-reactroot]') && document.scripts.length > 0,
    visible_controls: [...main.querySelectorAll('button,input:not([type=hidden]),select,textarea,[role=button],a[href]')]
      .filter(visible).length,
    text_length: (main.innerText || '').trim().length,
    error_document: error.test(title + ' ' + headings)
  };
}"""


def rendered_application(page: dict, evidence: dict) -> bool:
    """Only a proven client-rendered 404 may keep its UI eligible; never override auth/rate/server errors."""
    return bool(page.get("status") == 404 and not page.get("error") and not page.get("needs_permission")
                and evidence.get("application_mount") and evidence.get("visible_controls", 0) >= 2
                and evidence.get("text_length", 0) >= 80 and not evidence.get("error_document")
                and not ERROR_PAGE.search(page.get("title") or ""))


def page_testable(page: dict) -> bool:
    if page.get("error") or page.get("needs_permission"):
        return False
    status = page.get("status") or 0
    return status < 400 or (status == 404 and page.get("rendered_application") is True)


def exploration_status(crawl: dict) -> dict:
    pending = crawl.get("not_visited_count", 0)
    stopped = bool(crawl.get("stopped") or crawl.get("time_limit_reached"))
    depth_limited = any("depth" in item.get("reason", "").lower() for item in crawl.get("skipped", []))
    sampled = bool(crawl.get("sampled"))
    login_blocked = bool(crawl.get("login_blocked")) or (bool(crawl.get("needs_login")) and not crawl.get("logged_in_pages"))
    actions_limited = bool((crawl.get("actions") or {}).get("not_tried_limit"))
    exhausted = not pending and not stopped and not depth_limited and not sampled and not login_blocked and not actions_limited
    return {
        "status": "routes_processed" if exhausted else "partial",
        "frontier_exhausted": not pending and not stopped and not actions_limited,
        "within_selected_scope": exhausted,
        "visited": crawl.get("visited", 0), "unvisited": pending,
        "depth_limited": depth_limited, "sampled": sampled, "actions_limited": actions_limited,
        "login_blocked": login_blocked,
        "permissions_blocked": len(crawl.get("needs_permission", [])),
        "statement": (
            "Discovered routes were processed within the selected scope and exploration budgets "
            "(not exhaustive product reachability)."
            if exhausted else
            "Exploration is partial (pending URLs, crawl/time limits, and/or interaction limits); "
            "do not claim every reachable page or workflow was visited."),
        "limitation": ("Visited URLs ≠ route patterns ≠ controls ≠ interaction checks ≠ features ≠ "
                       "business workflows. Route discovery is not proof that every component state "
                       "or business workflow was tested."),
    }
