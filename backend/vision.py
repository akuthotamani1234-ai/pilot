"""The AI's eyes: it LOOKS at screenshots, the way a person checks a website.

  look_at_pages()    after exploring: what each page shows a person - its features (search, forms, tables, tabs ...)
                     and the messages on it. Saved as page["seen"]: the AI's test cases are written from it, and the
                     report lists what was seen on screen but not tested.
  review_results()   after the tests: for every failed test, the picture just before the step that failed (from the
                     test's Playwright recording) and the picture when it failed -> website bug / test mistake / can't
                     tell. Saved as result["vision"]; failure_analysis.classify() uses it, so the report, the Excel file
                     and the feature statuses agree.

What it never does: look at a page with a password box (that page is never sent), judge what a picture can't show
(JavaScript errors, HTTP status codes), or turn a failure into a proven website bug - a bug it sees in a test that
was not a check of the website becomes "suspect" (a person confirms). Off with VISION=off or a text-only AI model.
"""
import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from . import runctl
from .config import settings
from .llm import LLMError, ask_structured, load_prompt, vision_enabled

MAX_PAGES = 40           # pages looked at per run (the app behind the login first)
MAX_IMAGE_BYTES = 6_000_000
WORKERS = 4              # pictures looked at at the same time
SYSTEM = ("You are a senior QA tester who looks at screenshots of a website. You report only what the pictures "
          "really show, quoting the words on the screen.")


KINDS = ("navigation", "search", "filter", "sort", "pagination", "form", "table", "list", "tabs", "menu", "button",
         "cart", "dialog", "upload", "download", "media", "account", "content", "other")


class SeenFeature(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = "other"
    does: str = Field(default="", max_length=200)

    @field_validator("name", "does", mode="before")
    @classmethod
    def _short(cls, v, info):  # (a long name is cut, not a reason to throw the whole answer away)
        return str(v or "")[:80 if info.field_name == "name" else 200]

    @field_validator("kind", mode="before")
    @classmethod
    def _known_kind(cls, v):  # ('dropdown', 'link' ... -> other: the feature is kept)
        v = str(v or "").strip().lower()
        return v if v in KINDS else "other"


class PageSeen(BaseModel):
    purpose: str = Field(default="", max_length=300)
    features: list[SeenFeature] = Field(default_factory=list, max_length=40)
    messages: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("features", "messages", mode="before")
    @classmethod
    def _first_ones(cls, v, info):  # (a busy page's 42 features: the first 40 are kept - no second, paid AI call)
        return list(v or [])[:40 if info.field_name == "features" else 20]

    @field_validator("purpose", mode="before")
    @classmethod
    def _cut(cls, v):
        return str(v or "")[:300]


class FailureSeen(BaseModel):
    verdict: Literal["website_bug", "test_mistake", "cannot_tell"]
    seen: str = Field(default="", max_length=400)
    reason: str = Field(min_length=3, max_length=400)

    @field_validator("seen", "reason", mode="before")
    @classmethod
    def _cut(cls, v):  # (a long quote of the screen is cut, the verdict is kept)
        return str(v or "")[:400]


# ---------------------------------------------------------------- what may be sent

def _password_page(p: dict | None, url: str = "") -> bool:
    """A page with a password box, or a login address: never sent (its picture could show what is typed in it - or a
    demo site's own 'Password: ...' hint)."""
    from .agents.discovery import _auth_link
    if p and (p.get("page_type") == "login" or any((i.get("type") or "") == "password" for i in p.get("inputs", []))):
        return True
    return bool(url) and bool(_auth_link(url))


def _read(run_dir: Path, rel: str | None) -> bytes | None:
    if not rel:
        return None
    f = Path(run_dir) / rel
    try:
        data = f.read_bytes() if f.is_file() else b""
    except OSError:
        return None
    return data if 0 < len(data) <= MAX_IMAGE_BYTES else None


# ---------------------------------------------------------------- 1. every page, after exploring

def can_look(p: dict) -> bool:
    """May (and can) the AI look at this page's screenshot?"""
    return (vision_enabled() and bool(p.get("screenshot")) and not p.get("error") and (p.get("status") or 0) < 400
            and not _password_page(p, p.get("url") or ""))


def look_at_page(p: dict, run_dir: Path) -> bool:
    """The AI looks at one page's screenshot and lists what a person can use there: page["seen"]. Called by the
    crawl right after the screenshot, so the explorer can try what the AI saw (observe.Explorer). False = it could
    not look (nothing is guessed then)."""
    if p.get("seen") or not can_look(p) or runctl.stopping():
        return bool(p.get("seen"))
    img = _read(run_dir, p["screenshot"])
    if img is None:
        return False
    try:
        seen = ask_structured(load_prompt("vision_page").format(url=p["url"], title=p.get("title") or ""),
                              PageSeen, system=SYSTEM, agent="vision", page=p.get("slug") or "", images=[img])
    except LLMError as e:
        print(f"  [vision] could not look at {p['url']}: {str(e)[:120]}")
        return False
    p["seen"] = seen.model_dump()
    return True


def look_at_pages(app_map: list[dict], run_dir: Path) -> int:
    """After exploring: the pages the AI has not looked at yet (the crawl looks at each one as it goes). Returns how
    many pages have been looked at in all."""
    todo = [p for p in sorted(app_map, key=lambda p: not p.get("auth")) if can_look(p) and not p.get("seen")]
    todo = todo[:max(0, MAX_PAGES - sum(1 for p in app_map if p.get("seen")))]
    if todo:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            list(pool.map(lambda p: look_at_page(p, run_dir), todo))
    looked = [p for p in app_map if p.get("seen")]
    if looked:
        n = sum(len(p["seen"].get("features", [])) for p in looked)
        print(f"  [vision] the AI looked at {len(looked)} page(s): {n} feature(s) seen on screen")
    return len(looked)


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", s.lower()) if w not in {"the", "and", "for", "button", "link", "box"}}


def not_tested(page: dict, tested_names: list[str]) -> list[dict]:
    """Features the AI saw on this page that no test of the page names (by their words): what the rules missed.
    The site's menu / header ('navigation') and plain content are left out."""
    names = [_words(n) for n in tested_names if n]
    out = []
    for f in (page.get("seen") or {}).get("features", []):
        if f.get("kind") in ("navigation", "content", "media"):
            continue
        w = _words(f.get("name") or "")
        if w and not any(w & n for n in names):
            out.append(f)
    return out


def coverage(app_map: list[dict], cases: list[dict]) -> dict:
    """What the AI saw on screen and whether a test case of that page names it: {page url: [features not tested]}."""
    by_page: dict[str, list[str]] = {}
    url_of = {p.get("slug"): p["url"] for p in app_map}
    for c in cases:  # (a journey names every page it visits)
        for u in {c.get("url") or ""} | {url_of[s] for s in (c.get("pages") or []) if s in url_of}:
            by_page.setdefault(u, []).extend([c.get("title") or "", c.get("feature") or "", c.get("element") or "",
                                              " ".join(str(s) for s in c.get("steps") or [])])
    out = {}
    for p in app_map:
        if not p.get("seen"):
            continue
        tested = by_page.get(p["url"], []) + [b.get("text") or "" for b in p.get("buttons", [])] + [
            i.get("label") or i.get("name") or i.get("placeholder") or "" for i in p.get("inputs", [])] + [
            l.get("text") or "" for l in p.get("links", [])]
        missing = not_tested(p, tested)
        if missing:
            out[p["url"]] = missing
    return out


# ---------------------------------------------------------------- 2. every failed test, after the tests

# tests about something a picture can't show: the browser's JavaScript errors, HTTP status codes, typed input values
UNSEEABLE_TEST = re.compile(r"^test_(no_console_errors|page_loads|link\[|section_link|data_|images_load)")
UNSEEABLE_ERROR = re.compile(r"JavaScript error|JS exception|caused JavaScript errors|console error|HTTP \d{3}\b|"
                             r"returned HTTP|net::ERR_", re.I)
# who wrote the test: the AI judges an expectation that was only a guess differently from a built-in check
ORIGIN = {"test_flows_ai.py": "an AI wrote this test from text descriptions of the pages, without seeing them - its "
                              "expected messages and names may be guesses",
          "test_learned.py": "this test repeats what the control did while the website was explored"}


def _said(err: str) -> str:
    """The error lines of pytest's output ('E   ...'), not the test's source code above them (`console_errors`)."""
    return "\n".join(ln for ln in err.splitlines() if ln.lstrip().startswith("E ")) or err
REVIEWED = {"product_defect", "assertion_failure", "locator", "timeout", "suspect", "inconclusive"}
ACTING = {"click", "dblclick", "fill", "press", "type", "selectOption", "check", "uncheck", "tap", "dispatchEvent",
          "setInputFiles", "hover", "goto"}


def before_picture(trace: Path) -> bytes | None:
    """From a test's Playwright recording (trace.zip): the screen just before its LAST action (the click / typing that
    the failure followed)."""
    try:
        z = zipfile.ZipFile(trace)
    except (OSError, zipfile.BadZipFile):
        return None
    with z:
        events = []
        for name in (n for n in z.namelist() if n.endswith(".trace")):
            for line in z.read(name).decode("utf-8", "replace").splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
        frames = sorted((e["timestamp"], e.get("sha1") or e.get("file") or "") for e in events
                        if e.get("type") == "screencast-frame" and "timestamp" in e)
        acts = [e for e in events if e.get("type") == "before" and e.get("method") in ACTING and "startTime" in e]
        if not frames or not acts:
            return None
        start = max(a["startTime"] for a in acts)
        earlier = [f for f in frames if f[0] <= start]
        _ts, ref = (earlier or frames)[-1]
        for name in (ref, f"resources/{ref}"):
            if name in z.namelist():
                data = z.read(name)
                return data if len(data) <= MAX_IMAGE_BYTES else None
    return None


def _case_of(r: dict, cases: list[dict]) -> dict:
    from .excel import case_hits
    return next((c for c in cases if r in case_hits(c, [r])), {})


def _key(r: dict) -> str:
    return f"{r.get('nodeid')}|{(r.get('error') or '')[-300:]}"


def review_results(state: dict) -> int:
    """The AI looks at the failed tests (before / after pictures) and gives its verdict: result["vision"].
    Cached in runs/<run>/vision_failures.json, so a test that fails again the same way after self-healing is not
    looked at twice. Returns how many tests it looked at in this call."""
    if not vision_enabled() or not state.get("run_dir"):
        return 0
    from .agents.failure_analysis import _rule_classify
    run_dir = Path(state["run_dir"])
    cache_file = run_dir / "vision_failures.json"
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    except (OSError, ValueError):
        cache = {}
    pages = {p["url"]: p for p in state.get("app_map", [])}
    cases = state.get("test_cases", [])
    # what the website really has (item names seen while exploring): 'no result for LIMITED' is only right when no
    # item is called that - the pictures alone can't tell
    known = list(dict.fromkeys(n.strip()[:60] for p in state.get("app_map", []) for n in (p.get("itemNames") or [])
                               if n and n.strip()))[:60]
    todo = []
    for r in state.get("results", []):
        if r.get("outcome") not in ("failed", "error") or r.get("flaky"):
            continue
        if _key(r) in cache:
            r["vision"] = cache[_key(r)]
            continue
        cat = _rule_classify(r)[0]
        err = r.get("error") or ""
        if cat not in REVIEWED or UNSEEABLE_TEST.match(r.get("test") or "") or UNSEEABLE_ERROR.search(_said(err)):
            continue
        case = _case_of(r, cases)
        url = r.get("url") or case.get("url") or ""
        if _password_page(pages.get(url), url):
            continue
        todo.append((r, case, url))
    todo = todo[:max(0, settings.vision_max_failures - len(cache))]

    def one(item) -> bool:
        r, case, url = item
        after = _read(run_dir, r.get("screenshot"))
        before = before_picture(run_dir / r["trace"]) if r.get("trace") else None
        caption = "Picture 1: just before the step that failed (from the test's recording). "
        if before is None:  # (no recording: how the page looked while exploring)
            before = _read(run_dir, (pages.get(url) or {}).get("screenshot"))
            caption = "Picture 1: how this page looked while the website was explored, before the test. "
        pics = [x for x in (before, after) if x]
        if not after or runctl.stopping():
            return False
        caption = (caption if len(pics) == 2 else "") + f"Picture {len(pics)}: the screen when the test failed."
        from .agents.failure_analysis import _short_error
        try:
            v = ask_structured(load_prompt("vision_failure").format(
                title=case.get("title") or r.get("test"), steps=json.dumps((case.get("steps") or [])[:12]),
                origin=ORIGIN.get(r.get("file") or "", "a built-in check of the testing tool"),
                known=json.dumps(known, ensure_ascii=False) if known else "(none recorded)",
                expected=case.get("expected") or "(not written)", error=_short_error(r.get("error"))[:900],
                pictures=caption), FailureSeen, system=SYSTEM, agent="vision", page=url, test=r.get("test") or "",
                images=pics)
        except LLMError as e:
            print(f"  [vision] could not look at {r.get('test')}: {str(e)[:120]}")
            return False
        r["vision"] = cache[_key(r)] = v.model_dump()
        return True

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        done = sum(pool.map(one, todo))
    if todo:
        verdicts = [r["vision"]["verdict"] for r, _c, _u in todo if r.get("vision")]
        print(f"  [vision] the AI looked at {done} failed test(s): " + ", ".join(
            f"{verdicts.count(v)} {v.replace('_', ' ')}" for v in ("website_bug", "test_mistake", "cannot_tell")))
        try:
            cache_file.write_text(json.dumps(cache, indent=1), encoding="utf-8")
        except OSError:
            pass
    return done
