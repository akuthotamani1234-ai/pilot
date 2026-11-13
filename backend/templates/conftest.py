"""Shared fixtures for the AI-generated tests (copied into every run's generated_tests/ folder).

Fixtures available to every generated test:
  page            -> the Playwright page (sync API); one shared window, cleaned before every test
  console_errors  -> list that collects browser console errors for that page
On failure, a screenshot and a Playwright trace are saved and every result is written to results.jsonl.

SANDBOX - the generated code is untrusted, so while a test runs:
  * it can't start programs, open network connections or write files outside this run's folder (Python audit hook)
  * the browser only opens the approved website; private-network and cloud-metadata addresses are always blocked
  * requests sent from the test itself (page.request) may only READ (GET / HEAD), with every redirect checked
  * each test has a time limit (QA_TEST_TIMEOUT_S)
  * the test password is never shown on screen, in results or in traces
A test that passes without running a single check (assert / expect) is reported as INCONCLUSIVE, not passed.
"""
import ctypes
import ipaddress
import json
import os
import re
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote, quote_plus, urljoin, urlparse

import playwright.sync_api as _pw
import pytest
from playwright._impl._sync_base import SyncBase
from playwright.sync_api import APIRequestContext, Locator, Page, sync_playwright

RESULTS_FILE = Path(os.environ.get("QA_RESULTS_FILE", "results.jsonl"))
if os.environ.get("PYTEST_XDIST_WORKER"):  # tests run in parallel: each worker writes its own file (merged later)
    RESULTS_FILE = RESULTS_FILE.with_name(f"{RESULTS_FILE.stem}.{os.environ['PYTEST_XDIST_WORKER']}{RESULTS_FILE.suffix}")
SHOT_DIR = Path(os.environ.get("QA_SCREENSHOT_DIR", "failure_screenshots"))
TRACE_DIR = Path(os.environ.get("QA_TRACE_DIR", "traces"))
RECORD_TRACES = os.environ.get("QA_TRACES", "true").lower() != "false"
HEADLESS = os.environ.get("HEADLESS", "true").lower() != "false"
SLOW_MO_MS = int(os.environ.get("SLOW_MO_MS", "0"))
NAV_TIMEOUT_MS = int(os.environ.get("QA_NAV_TIMEOUT_MS", "30000"))  # time a page may take to open
TEST_TIMEOUT_S = float(os.environ.get("QA_TEST_TIMEOUT_S", "180"))
RUN_DIR = Path(os.environ.get("QA_RUN_DIR") or Path(__file__).resolve().parent.parent).resolve()
ALLOWED_HOSTS = [h.strip().lower() for h in os.environ.get("QA_ALLOWED_HOSTS", "").split(",") if h.strip()]
TARGET_LOCAL = os.environ.get("QA_TARGET_LOCAL") == "1"
VIDEO_DIR = os.environ.get("QA_VIDEO_DIR", "")  # set: a video of every browser window is saved there (RECORD_VIDEO)
# the website's address: `expect(page).to_have_url('/product/7')` (an address as its links write it) means this website
# (practicesoftwaretesting.com, Nov 3, 2026: compared with '/product/7' itself, the right page failed)
BASE_URL = os.environ.get("QA_BASE_URL", "")
# watching: the browser scaled so its whole window fits the screen, at its top left (discovery.fit_window_args)
WINDOW_ARGS = [a for a in json.loads(os.environ.get("QA_WINDOW_ARGS") or "[]")
               if re.fullmatch(r"--(start-maximized|window-position=\d+,\d+|window-size=\d+,\d+)", a)]
CAPTION_MS = 0  # pacing happens once per user action, outside presentation-only captions
ACTION_DELAY_MS = 0 if HEADLESS else max(0, min(SLOW_MO_MS, 3000))
EVENT_SESSION = uuid.uuid4().hex[:12]
EVENT_FILE = RUN_DIR / f"events.{EVENT_SESSION}.{os.environ.get('PYTEST_XDIST_WORKER', 'main')}.jsonl"
_EVENT_SEQUENCE = 0
SHOT_DIR.mkdir(parents=True, exist_ok=True)
REDACTED = "[REDACTED]"


def _secrets() -> list[str]:
    pw = os.environ.get("TEST_PASSWORD", "")
    return [s for s in dict.fromkeys([pw, quote_plus(pw), quote(pw, safe=""), json.dumps(pw)[1:-1]]) if len(s) >= 4]


def _redact(text):
    if not isinstance(text, str):
        return text
    for s in _secrets():
        text = text.replace(s, REDACTED)
    return text


# ------------------------------------------------------------------ sandbox: where the browser and the test may go

METADATA = {"169.254.169.254", "169.254.170.2", "100.100.100.200", "fd00:ec2::254", "metadata.google.internal",
            "metadata.goog", "metadata"}


def _private(host: str) -> bool:
    h = (host or "").lower().strip("[]")
    if h == "localhost" or h.endswith(".localhost") or h.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified


def _approved(host: str) -> bool:
    h = (host or "").lower()
    return not ALLOWED_HOSTS or any(h == a or (a.startswith("*.") and h.endswith(a[1:])) for a in ALLOWED_HOSTS)


def _blocked(url: str, navigation: bool = False) -> str | None:
    """Why the sandbox stops a request to this address (None = allowed)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https", "ws", "wss"):
        return None
    h = (p.hostname or "").lower()
    if h in METADATA:
        return "cloud metadata address"
    if _private(h) and not TARGET_LOCAL and not _approved(h):
        return "private network / this PC"
    if navigation and not _approved(h):
        return f"outside the approved website ({h})"
    return None


AD_RX = re.compile(os.environ.get("QA_AD_RX") or r"(?!x)x", re.I)  # ad / tracker networks (backend/safety.py)


def _guard(context) -> None:
    """Browser side: abort blocked requests, and main-page navigations that leave the approved website. Ads and
    trackers are stopped too (never the website under test; pages full of ads never go quiet)."""
    def handle(route):
        req = route.request
        try:
            top = req.is_navigation_request() and req.frame.parent_frame is None
        except Exception:
            top = False
        try:
            host = (urlparse(req.url).hostname or "").lower()
            if (AD_RX.search(host) and not (ALLOWED_HOSTS and _approved(host))) or _blocked(req.url, navigation=top):
                route.abort("blockedbyclient")
            else:
                route.continue_()
        except Exception:
            pass  # the page was closed meanwhile
    context.route("**/*", handle)


# requests sent by the test code itself (page.request.get ...): read-only, every redirect hop checked
_real_get = APIRequestContext.get
_real_head = APIRequestContext.head


def _checked(real):
    def call(self, url, **kwargs):
        hops, current = 0, url
        while True:
            why = _blocked(current)
            if why:
                raise PermissionError(f"blocked by the test sandbox: {current} ({why})")
            r = real(self, current, **dict(kwargs, max_redirects=0))
            location = r.headers.get("location")
            if r.status in (301, 302, 303, 307, 308) and location and hops < 5:
                current, hops = urljoin(current, location), hops + 1
                continue
            return r
    return call


def _read_only(*args, **kwargs):
    raise PermissionError("blocked by the test sandbox: generated tests may only read (GET / HEAD), "
                          "never send data with page.request")


if not getattr(APIRequestContext, "_qa_guarded", False):
    APIRequestContext._qa_guarded = True
    APIRequestContext.get, APIRequestContext.head = _checked(_real_get), _checked(_real_head)
    for _name in ("post", "put", "patch", "delete", "fetch"):
        setattr(APIRequestContext, _name, _read_only)


# Python side: while a test (or a test file being imported) runs, no programs, no network, no files outside the run
_SANDBOX = {"thread": None}
_PROCESS_EVENTS = ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.startfile",
                   "os.fork", "os.forkpty", "os.kill", "os.killpg", "_winapi.CreateProcess", "ctypes.dlopen",
                   "ctypes.dlsym", "ctypes.call_function", "ctypes.cdata", "_thread.start_new_thread", "os.chdir",
                   "os.chmod", "webbrowser.open", "winreg.OpenKey", "winreg.CreateKey", "winreg.SetValue")
# (environment changes are allowed: pytest itself sets PYTEST_CURRENT_TEST, and this process has no secrets to leak)
_NET_EVENTS = ("socket.__new__", "socket.connect", "socket.bind", "socket.getaddrinfo", "socket.gethostbyname",
               "socket.sendto", "socket.sendmsg", "http.client.connect")
_FILE_EVENTS = ("os.remove", "os.rename", "os.replace", "os.rmdir", "os.mkdir", "shutil.rmtree", "shutil.move",
                "shutil.copyfile", "os.truncate", "os.symlink", "os.link")
SENSITIVE = re.compile(r"(^|[\\/])(\.env|accounts|\.private|auth\.json|id_rsa|\.ssh|\.aws|\.git-credentials)([\\/]|$)",
                       re.I)


def _inside_run(path) -> bool:
    try:
        return Path(os.fsdecode(path)).resolve().is_relative_to(RUN_DIR)
    except (TypeError, ValueError, OSError):
        return False


def _audit(event, args):
    if _SANDBOX["thread"] is None or threading.get_ident() != _SANDBOX["thread"]:
        return
    if event in _PROCESS_EVENTS or event in _NET_EVENTS:
        raise PermissionError(f"blocked by the test sandbox: {event}")
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        path, mode, flags = (list(args) + [None, None])[:3]
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT))
        if SENSITIVE.search(os.fsdecode(path)) or (writing and not _inside_run(path)):
            raise PermissionError(f"blocked by the test sandbox: open {os.fsdecode(path)!r}")
    if event in _FILE_EVENTS and args and not all(_inside_run(a) for a in args[:2] if isinstance(a, (str, bytes))):
        raise PermissionError(f"blocked by the test sandbox: {event}")


if not getattr(sys, "_qa_sandbox", False):
    sys._qa_sandbox = True
    sys.addaudithook(_audit)


class TestTimeout(BaseException):
    """The test took longer than QA_TEST_TIMEOUT_S and was stopped. (A BaseException, like Ctrl+C: the test's own
    `except Exception:` - e.g. "the page never goes idle, carry on" - can't swallow it and run on without a limit.)"""


# A test past its time limit is stopped at its NEXT BROWSER ACTION, raised right there in the test's own code. (A
# signal sent from another thread lands wherever the thread is - while the browser works, inside Playwright's event
# loop, where it is lost: the test then ran on for ever and the browser window looked stuck.)
_OVERTIME: dict = {}    # thread -> its test is past the time limit
_IN_BROWSER: dict = {}  # thread -> browser actions running right now (nested)


def _limited(real):
    def _sync(self, coro):
        me = threading.get_ident()
        if _OVERTIME.get(me):
            coro.close()
            raise TestTimeout(f"the test took longer than {TEST_TIMEOUT_S:g} s and was stopped")
        _IN_BROWSER[me] = _IN_BROWSER.get(me, 0) + 1
        try:
            return real(self, coro)
        finally:
            _IN_BROWSER[me] -= 1
    return _sync


if not getattr(SyncBase, "_qa_limited", False):
    SyncBase._qa_limited = True  # patch only once
    SyncBase._sync = _limited(SyncBase._sync)


# which test this browser is running now, and since when: the chat shows "running for 2:35 (stops at 3:00)", so a
# long test never looks like a stuck run
RUNNING_FILE = RESULTS_FILE.parent / f"running.{RESULTS_FILE.stem}.{os.environ.get('PYTEST_XDIST_WORKER', 'main')}.json"


def _running(item=None) -> None:
    """Which test this browser runs now, since when, and its steps so far (the chat shows them ticking)."""
    try:
        RUNNING_FILE.write_text(json.dumps({"file": Path(str(item.fspath)).name, "test": item.name,
                                            "since": getattr(item, "_qa_t0", time.time()), "limit_s": TEST_TIMEOUT_S,
                                            "steps": getattr(item, "_qa_steps", [])[-MAX_STEPS:]}
                                           if item else {}), encoding="utf-8")
    except OSError:
        pass


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """Run the test body inside the sandbox, with a time limit."""
    me, done, lock = threading.get_ident(), threading.Event(), threading.Lock()
    item._qa_checks, item._qa_steps, item._qa_t0 = 0, [], time.time()
    _CURRENT["item"] = item
    _running(item)

    def watchdog():
        if done.wait(TEST_TIMEOUT_S):
            return
        _OVERTIME[me] = True  # its next browser action raises TestTimeout
        if done.wait(5):
            return
        while True:  # no browser action for a while (a loop in plain Python): raise it inside the test's thread -
            with lock:  # only while it is not inside a browser action, again every 5 s until the test has stopped
                if done.is_set():
                    return
                if not _IN_BROWSER.get(me):
                    ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(me), ctypes.py_object(TestTimeout))
            if done.wait(5):
                return
    threading.Thread(target=watchdog, daemon=True).start()  # (started before the sandbox is switched on)
    _SANDBOX["thread"] = me
    try:
        yield
    finally:
        _SANDBOX["thread"] = None
        with lock:
            done.set()
            _OVERTIME.pop(me, None)  # (the clean-up after the test may use the browser again)
        _running(None)


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    """Importing a generated test file runs its top-level code: in the sandbox too."""
    if isinstance(collector, pytest.Module):
        _SANDBOX["thread"] = threading.get_ident()
        try:
            yield
        finally:
            _SANDBOX["thread"] = None
    else:
        yield


# ------------------------------------------------------------------ "passed" needs at least one real check

_CURRENT: dict = {"item": None}


class _CountingExpect:
    """Playwright's expect(...), counting every check (expect.set_options etc. still work)."""

    def __init__(self, real):
        self._real = real

    def __call__(self, *args, **kwargs):
        if _CURRENT["item"] is not None:
            _CURRENT["item"]._qa_checks = getattr(_CURRENT["item"], "_qa_checks", 0) + 1
        return self._real(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


if not getattr(_pw, "_qa_counting", False):  # (test files import expect AFTER this file: they get this one)
    _pw._qa_counting = True
    _pw.expect = _CountingExpect(_pw.expect)

# A website whose addresses are '#/' routes (AngularJS): its home page IS 'https://site.com/#/' - a test expecting
# 'https://site.com/' saw the right page and failed (advantageonlineshopping.com, Nov 3, 2026: 4 AI journeys). Only an
# EMPTY route ('#', '#/') is the same page; '#/product/3' stays another page.
EMPTY_ROUTE = re.compile(r"/?#/?$")


def _empty_route_matches(assertions, want) -> bool:
    try:
        page = assertions._impl_obj._actual_page
        url, base = page.url, page.context._base_url or ""
    except Exception:
        return False
    if not EMPTY_ROUTE.search(url):
        return False
    here = EMPTY_ROUTE.sub("/", url)
    if isinstance(want, re.Pattern):
        return bool(want.search(here) or want.search(here.rstrip("/")))
    return isinstance(want, str) and urljoin(base or here, want).rstrip("/") == here.rstrip("/")


def _same_page_url(real):
    def to_have_url(self, url_or_reg_exp, *args, **kwargs):
        try:
            return real(self, url_or_reg_exp, *args, **kwargs)
        except AssertionError:
            if not _empty_route_matches(self, url_or_reg_exp):
                raise
    return to_have_url


if not getattr(_pw.PageAssertions, "_qa_routes", False):
    _pw.PageAssertions._qa_routes = True
    _pw.PageAssertions.to_have_url = _same_page_url(_pw.PageAssertions.to_have_url)


def pytest_assertion_pass(item, lineno, orig, expl):
    item._qa_checks = getattr(item, "_qa_checks", 0) + 1
    _step(f"Check: {re.sub(r'\s+', ' ', orig)[:90]}", True)


# ------------------------------------------------------------------ the steps of the running test, live
# Every browser action of a test is a step in plain words ("Open /catalog", "Click 'Add to cart'", "Type 'Tomato' into
# 'Search'"), and so is every check that passed and every `_step_ok()` line - with ✓ / ✗ and the time. They are written
# to running.*.json while the test runs (the chat shows them ticking) and kept with the result (results.jsonl).
MAX_STEPS = 60
STEP_NAME_JS = """e => {
  const labels = e.labels ? [...e.labels] : [];
  const l = labels.find(l => l.parentElement === e.parentElement) || labels[0];
  const adjacent = e.previousElementSibling?.tagName === 'LABEL' ? e.previousElementSibling.innerText : '';
  const t = (adjacent || l?.innerText || e.innerText || e.getAttribute('aria-label') || e.getAttribute('placeholder')
  || e.getAttribute('title') || e.getAttribute('name') || '').trim().split('\\n')[0];
  if (t) return t.slice(0, 50);
  return e.tagName.toLowerCase(); }"""


def _step(text: str, ok=None) -> None:
    item = _CURRENT["item"]
    if item is None:
        return
    steps = item.__dict__.setdefault("_qa_steps", [])
    _event(text, "failed" if ok is False else "completed" if ok else "info")
    if len(steps) >= MAX_STEPS:
        del steps[0]  # the durable event file retains the complete history
    steps.append({"text": _redact(text)[:140], "ok": ok, "t": round(time.time() - getattr(item, "_qa_t0", time.time()), 1)})
    _running(item)


pytest.qa_step = _step  # (a journey's own verified steps - `_step_ok()` in the generated tests - tick live too)


def _event(text, status, **details):
    global _EVENT_SEQUENCE
    item = _CURRENT["item"]
    if item is None:
        return
    _EVENT_SEQUENCE += 1
    page = getattr(item, '_qa_page', None)
    value = {"id": f"{EVENT_SESSION}:{_EVENT_SEQUENCE}", "timestamp": time.time(),
             "worker": os.environ.get("PYTEST_XDIST_WORKER", "main"), "test": item.name,
             "url": _redact(page.url) if page is not None and not page.is_closed() else "",
             "nodeid": item.nodeid, "status": status, "text": _redact(text)[:500],
             "elapsed": round(time.time() - getattr(item, "_qa_t0", time.time()), 2), **details}
    try:
        with EVENT_FILE.open("a", encoding="utf-8") as stream:
            stream.write(_redact(json.dumps(value)) + "\n")
    except OSError as exc:
        print(f"[qa-note] Live event could not be saved: {type(exc).__name__}")


def _pace(page):
    if ACTION_DELAY_MS:
        page.wait_for_timeout(ACTION_DELAY_MS)


def _named(loc) -> str:
    try:
        return loc.first.evaluate(STEP_NAME_JS, timeout=1000)
    except Exception:
        return re.sub(r"^.*?(text=|has-text\()", "", str(getattr(loc, "_selector", "")))[:50] or "an element"


ACTION_WORDS = {"click": "Click", "dblclick": "Double-click", "tap": "Tap", "check": "Tick", "uncheck": "Untick",
                "hover": "Point at", "fill": "Type", "type": "Type", "press": "Press", "select_option": "Choose",
                "set_input_files": "Upload into"}


def _stepped(method, verb):
    def wrapper(self, *args, **kwargs):
        if _CURRENT["item"] is None:
            return method(self, *args, **kwargs)
        name = _named(self)
        what = (f"{verb} '{_shown_value(self, args[0])[:40]}' into '{name}'" if verb == "Type" and args else
                f"Press {args[0]} in '{name}'" if verb == "Press" and args else
                f"Choose '{str(args[0])[:40]}' in '{name}'" if verb == "Choose" and args else f"{verb} '{name}'")
        _event(what, "running", selector=_redact(str(getattr(self, "_selector", "")))[:300])
        try:
            _pace(self.page)
            out = method(self, *args, **kwargs)
        except Exception:
            _step(what, False)
            raise
        _step(what, True)
        return out
    return wrapper


def _goto_stepped(method):
    def wrapper(self, url, *args, **kwargs):
        if _CURRENT["item"] is None:
            return method(self, url, *args, **kwargs)
        shown = urlparse(str(url)).path or "/"
        _event(f"Open {shown}", "running")
        try:
            _pace(self)
            out = method(self, url, *args, **kwargs)
        except Exception:
            _step(f"Open {shown}", False)
            raise
        if not str(url).startswith("about:"):
            _step(f"Open {shown}", True)
        return out
    return wrapper


# ------------------------------------------------------------------ opening pages
# page.goto() waits for "load" by default: EVERY picture, map, video and chat widget. Busy sites (and 4 browsers
# testing at once) often need more than the 10 s action timeout for that, which made tests fail although the page
# was fine. Like the crawler: wait for the page's own content, with enough time, then give the rest a moment.

# A cookie / consent banner over the page is closed with the LEAST consent it offers (reject / only necessary, then
# close / got it / OK, accept only when it is the only choice) - never another popup. (the same script as
# backend/observe.py CLOSE_CONSENT_JS)
CLOSE_CONSENT_JS = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
                     return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const onTop = e => { for (let a = e; a && a !== document.body; a = a.parentElement) {
    if (['fixed', 'sticky'].includes(getComputedStyle(a).position) || a.matches('dialog, [role=dialog], [role=alertdialog]'))
      return true; } return false; };
  const banners = [...document.querySelectorAll('div, section, aside, footer, form, dialog, [role=dialog], [role=alertdialog], [role=region]')]
    .filter(e => vis(e) && /cookie|consent|gdpr/i.test((e.innerText || '').slice(0, 800)) && (e.innerText || '').length < 1500 && onTop(e))
    .sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);
  if (!banners.length) return '';
  const name = b => (b.innerText || b.value || b.getAttribute('aria-label') || b.getAttribute('title') || '').trim();
  const buttons = [...banners[0].querySelectorAll('button, [role=button], a, input[type=button], input[type=submit]')].filter(vis);
  for (const rx of [/^(reject|decline|deny|refuse)\b|necessary only|only necessary|essential only|only essential/i,
                    /^(close|dismiss|×|✕|x|no,? thanks|not now|got it|ok|okay|understood)$/i,
                    /^(i )?(accept|agree|allow)\b/i]) {
    const b = buttons.find(x => rx.test(name(x)));
    if (b) { b.click(); return name(b) || 'close'; }
  }
  return '';
}"""


SHOWS_JS = "() => !!document.body && document.body.innerText.trim().length > 0"

# ------------------------------------------------------------------ the website stops answering
# advantageonlineshopping.com, Nov 3, 2026: the website went down in the middle of the tests (for everyone) - every
# later test waited for it and FAILED: 138 'failures', and the retries would have waited for all of them again. A page
# the website does not answer AT ALL says nothing about the page: that test is NOT RUN. After DOWN_AFTER pages in a row
# did not open, the website is asked again at most every DOWN_PROBE_S: while it is still down the next tests are not
# run at all (no waiting); when it answers again, they run again.
UNREACHABLE = re.compile(r"net::ERR_(CONNECTION_(TIMED_OUT|REFUSED|RESET|CLOSED|FAILED|ABORTED)|TIMED_OUT|"
                         r"NAME_NOT_RESOLVED|ADDRESS_UNREACHABLE|INTERNET_DISCONNECTED|NETWORK_CHANGED|EMPTY_RESPONSE|"
                         r"SOCKET_NOT_CONNECTED)")
DOWN_AFTER, DOWN_PROBE_S = 3, 30
_DOWN = {"row": 0, "since": "", "why": "", "probed": 0.0, "up": True}
NOT_RUN_DOWN = "Not run: the website did not answer ({why}) - it was down or unreachable from this computer since {since}"


def _the_website(url) -> bool:
    host = urlparse(str(url)).hostname
    return not host or not ALLOWED_HOSTS or _approved(host.lower())  # (a relative address is this website)


def _did_not_open(url, e: Exception) -> None:
    """A page of the website did not open: counted. It did not answer at all: the running test is NOT RUN."""
    if not _the_website(url):
        return
    _DOWN["row"] += 1
    hit = UNREACHABLE.search(str(e))
    if hit:
        _DOWN["since"], _DOWN["why"] = _DOWN["since"] or time.strftime("%H:%M"), hit.group(0)
        if _CURRENT["item"] is not None:
            pytest.skip(NOT_RUN_DOWN.format(why=hit.group(0), since=_DOWN["since"]))


def _website_answers(context) -> bool:
    """After DOWN_AFTER pages in a row did not open: does the website answer at all? (asked at most every
    DOWN_PROBE_S - meanwhile the last answer counts)"""
    if _DOWN["row"] < DOWN_AFTER or not BASE_URL:
        return True
    if time.monotonic() - _DOWN["probed"] >= DOWN_PROBE_S:
        _DOWN["probed"] = time.monotonic()
        try:
            context.request.get(BASE_URL, timeout=10000, fail_on_status_code=False)
            _DOWN.update(row=0, since="", up=True)
        except Exception as e:
            hit = UNREACHABLE.search(str(e))
            _DOWN["up"] = False
            _DOWN["since"] = _DOWN["since"] or time.strftime("%H:%M")
            _DOWN["why"] = hit.group(0) if hit else (_DOWN["why"] or "no answer in 10 s")
    return _DOWN["up"]


def _patched_goto(real):
    def goto(self, url, **kwargs):
        try:
            return _open(self, url, kwargs)
        except _pw.Error as e:
            _did_not_open(url, e)
            raise

    def _open(self, url, kwargs):
        kwargs.setdefault("wait_until", "domcontentloaded")
        kwargs.setdefault("timeout", NAV_TIMEOUT_MS)
        if kwargs["wait_until"] != "domcontentloaded" or not kwargs["timeout"]:
            response = real(self, url, **kwargs)
        else:  # the server's answer first, then the page's own content
            t0 = time.monotonic()
            response = real(self, url, **dict(kwargs, wait_until="commit"))
            try:
                self.wait_for_load_state("domcontentloaded",
                                         timeout=max(1000, kwargs["timeout"] - (time.monotonic() - t0) * 1000))
            except _pw.TimeoutError:
                # the page shows, but a file the busy server never sends keeps it 'loading': a person uses it as it
                # is - only a page with nothing on it did not open (the crawler does the same)
                try:
                    shows = self.evaluate(SHOWS_JS)
                except Exception:
                    shows = False
                if not shows:
                    raise
        if _the_website(url) and not str(url).startswith("about:"):
            _DOWN.update(row=0, since="", up=True)  # (it answers)
        try:
            self.wait_for_load_state("load", timeout=5000)
        except Exception:
            pass  # pictures / maps still loading: the page itself is there
        try:
            if self.evaluate(CLOSE_CONSENT_JS):
                self.wait_for_timeout(400)
        except Exception:
            pass  # (the page moved on meanwhile)
        return response
    return goto


if not getattr(Page, "_qa_goto", False):
    Page._qa_goto = True  # patch only once (pytest may import this file more than once)
    Page.goto = _patched_goto(Page.goto)


# ------------------------------------------------------------------ live captions
# When the browser is visible, show WHAT the test is doing: a red bar at the top of the page
# ("Typing 'not-an-email' into #email") and a red outline around the element being used.
# A password is never shown: typing into a password box (or typing the test password) shows dots.
# The bar's words are CSS content (::after), never text of the page: a test that compares the page's text before and
# after an action must not see the caption change (automationexercise.com, watched: 'Pressing Enter' changed the
# text, so the search looked done and its button was never clicked - a false 'search still shows 34 items').

CAPTION_JS = """(el, msg) => {
  el.scrollIntoView({block: 'center'});
  el.style.outline = '3px solid #c62828';
  el.style.outlineOffset = '2px';
  let bar = document.getElementById('__qa_caption');
  if (!bar) {
    bar = document.createElement('div'); bar.id = '__qa_caption'; bar.setAttribute('aria-hidden', 'true');
    document.body.appendChild(bar);
    const css = document.createElement('style');
    css.textContent = '#__qa_caption::after { content: attr(data-qa-caption); }';
    (document.head || document.documentElement).appendChild(css);
  }
  bar.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;background:#c62828;color:#fff;' +
                      'font:bold 16px system-ui,sans-serif;padding:8px 12px;text-align:center;pointer-events:none';
  bar.setAttribute('data-qa-caption', msg);
}"""
# The running test's name is kept on the Locator class, so it is shared even if pytest
# imports this conftest more than once.
Locator._qa_test_name = ""


def _describe(loc) -> str:
    name = _named(loc)
    if name:
        return name
    m = re.search(r"selector='(.*)'", str(loc))
    return m.group(1) if m else "element"


def _shown_value(loc, value) -> str:
    """What the caption may show of a typed value: dots for a password."""
    value = str(value)
    if value and value in _secrets():
        return "••••••"
    try:
        if loc.first.get_attribute("type", timeout=500) == "password":
            return "••••••"
    except Exception:
        pass
    return value


def _caption(loc, text: str) -> None:
    """Show the red bar + outline, then pause so a person can read it."""
    try:
        loc.first.evaluate(CAPTION_JS, f"{Locator._qa_test_name}  |  {text}", timeout=3000)
        loc.page.wait_for_timeout(CAPTION_MS)  # long enough to read, bounded so big websites still finish
    except Exception:
        pass  # caption is only a visual aid - never let it break a test


def _with_caption(method, describe):
    def wrapper(self, *args, **kwargs):
        _caption(self, describe(self, *args))
        return method(self, *args, **kwargs)
    return wrapper


if not HEADLESS and not getattr(Locator, "_qa_captions", False):
    Locator._qa_captions = True   # patch only once
    for name, describe in {
        "fill":          lambda l, value="", *a: f"Typing '{_shown_value(l, value)}' into {_describe(l)}",
        "type":          lambda l, value="", *a: f"Typing '{_shown_value(l, value)}' into {_describe(l)}",
        "press":         lambda l, key="", *a: f"Pressing {key} in {_describe(l)}",
        "click":         lambda l, *a: f"Clicking {_describe(l)}",
        "check":         lambda l, *a: f"Ticking {_describe(l)}",
        "uncheck":       lambda l, *a: f"Unticking {_describe(l)}",
        "select_option": lambda l, value=None, *a: f"Choosing {value} in {_describe(l)}",
    }.items():
        setattr(Locator, name, _with_caption(getattr(Locator, name), describe))

        # page.fill("#email", "x") style calls -> show the caption on page.locator("#email")
        def _page_wrapper(method, describe=describe):
            def wrapper(self, selector, *args, **kwargs):
                loc = self.locator(selector)
                _caption(loc, describe(loc, *args))
                return method(self, selector, *args, **kwargs)
            return wrapper
        if name != "type":
            setattr(Page, name, _page_wrapper(getattr(Page, name)))


# No generated test may click a protected action: it could pay, order, delete, send or log out. The same rule as the
# explorer (backend/actions.py, passed in by the executor): what the control SAYS decides first ("Search" with
# id="search-submit" only searches). Always allowed: the login button of a login form. A built-in test may mark ONE
# planned click as approved (an empty form sent to check it is refused, on a test environment; removing the cart line
# it added itself) - code the AI wrote can't: in its files the guard is strict.
AI_FILES = {"test_flows_ai.py"}
PROTECTED_RX = re.compile(os.environ.get("QA_PROTECTED_RX") or
                          r"delete|remove|\btrash|log ?out|sign ?out|\bpay\b(?![\s_-]*grades?\b)|payment|\bbuy\b|"
                          r"purchase|check ?out|place (your )?order", re.I)
TEST_ACCOUNT_RX = re.compile(os.environ.get("QA_TEST_ACCOUNT_RX") or r"add to (cart|basket|bag|trolley)|wish ?list", re.I)
SAFE_TEXT_RX = re.compile(os.environ.get("QA_SAFE_TEXT_RX") or r"^\s*(search|log ?in|sign ?in)\s*$", re.I)
UNSAFE_LINK_RX = re.compile(os.environ.get("QA_UNSAFE_LINK_RX") or
                            r"logout|log-out|signout|sign-out|delete|remove|unsubscribe|deactivate|cancel-account", re.I)
# Same pay-grade exclusion as backend/actions.py - admin "Pay Grades" nav is not a payment submit.
MONEY_RX = re.compile(r"check ?out|\bbuy\b|place (your )?order|\bpay\b(?![\s_-]*grades?\b)", re.I)
# words that only SEND something when a button / form does it - a link with them only opens a page ('View post')
WRITE_RX = re.compile(os.environ.get("QA_WRITE_RX") or
                      r"\bsend\b|\bpost\b|publish|\bshare\b|\binvite\b|\bsave\b|submit|\bupdate\b|\bsubscribe\b", re.I)
# [shown text, aria-label, title, link address, its icon] - a button without words is judged by its icon ('bi-trash')
CONTROL_TEXT_JS = """(e, strict) => { if (!strict && e.getAttribute('data-qa-approved')) return null;
  const f = e.closest('form'), said = (e.innerText || e.value || '').trim();
  if (f && f.querySelectorAll('input[type=password]').length === 1 && !/regist|sign ?up|create|join/i.test(said)) return null;
  const box = /^(INPUT|TEXTAREA|SELECT)$/.test(e.tagName) && !/^(button|submit|reset|image)$/i.test(e.type || '');
  const i = said ? null : e.querySelector('i, svg, img, [class*=icon]');
  const icon = i ? [i.getAttribute('class'), i.getAttribute('data-icon'), i.getAttribute('aria-label'),
                    i.getAttribute('alt')].filter(Boolean).join(' ').replace(/[-_]+/g, ' ') : '';
  return [box ? '' : said, e.getAttribute('aria-label') || '', e.getAttribute('title') || '', e.getAttribute('href') || '',
          icon, e.tagName.toLowerCase(), e.getAttribute('role') || '', f ? 'in_form' : ''].map(s => s.trim().slice(0, 100)); }"""


def _risky(names: list) -> bool:
    shown, other = names[0], " ".join(names[1:])
    both = f"{shown} {other}"
    href = names[3] if len(names) > 3 else ""
    reference = re.compile(os.environ.get('QA_REFERENCE_NAV_RX') or r'(?!)', re.I)
    if len(names) >= 8 and reference.fullmatch(shown) and names[5] == 'a' and not names[7] and (
            names[6] == 'menuitem' or bool(href and href != '#')) and not re.search(
                r'javascript:|/(?:pay|checkout|purchase|transfer|confirm|delete|logout)(?:/|$)|'
                r'[?&](?:action|do|cmd)=(?:pay|buy|delete|transfer|confirm)', href, re.I):
        return False
    if TEST_ACCOUNT_RX.search(both) and not MONEY_RX.search(both):
        return False
    link = bool(shown and href and not href.startswith("#") and not href.lower().startswith("javascript"))
    if PROTECTED_RX.search(WRITE_RX.sub(" ", shown) if link else shown):  # (pay / delete / log out: even a link)
        return True
    if SAFE_TEXT_RX.search(shown):
        return False
    if link:
        # a link that SAYS where it goes ('Cart' -> index.php?rt=checkout/cart) only opens that page: only an address
        # that changes data (delete, remove, log out ...) makes it protected - the crawler's rule for links
        return bool(UNSAFE_LINK_RX.search(href))
    return bool(PROTECTED_RX.search(other))  # no telling text: its label / address decides


def _refuse_protected(loc) -> None:
    """A click on a protected control is not done - the test step is Blocked instead."""
    if not getattr(Locator, "_qa_guard", False):
        return
    try:  # [visible text, aria-label, title, link address] - None = allowed (login button / an approved click)
        names = loc.first.evaluate(CONTROL_TEXT_JS, bool(getattr(Locator, "_qa_strict", False)), timeout=3000)
    except Exception:
        return  # not found (yet): the real call reports that
    if names and _risky(names):
        label = next((n for n in names if n), "control").splitlines()[0][:60]
        pytest.skip(f"Blocked: '{label}' is a protected action (it could pay, order, delete, send or log out) - "
                    "never clicked without ALLOW_ACTIONS naming the class "
                    "(and TEST_PAYMENT=1 for pay, staging only)")


def _acts(key_arg, args, kwargs) -> bool:
    """A click always acts; press('Enter') / dispatch_event('click') act like one, other keys and events don't."""
    key = (args[0] if args else kwargs.get("key") or kwargs.get("type")) or ""
    return not key_arg or key in ("Enter", "Space", " ", "click")


def _guarded(method, key_arg=False):
    def wrapper(self, *args, **kwargs):
        if _acts(key_arg, args, kwargs):
            _refuse_protected(self)
        return method(self, *args, **kwargs)
    return wrapper


def _page_guarded(method, key_arg=False):
    def wrapper(self, selector, *args, **kwargs):
        if _acts(key_arg, args, kwargs):
            _refuse_protected(self.locator(selector))
        return method(self, selector, *args, **kwargs)
    return wrapper


# The website rebuilt its data while it was tested (demo shops do this every few minutes): an item page the crawler
# saved (/product/01M5...) is gone. The test then opens a CURRENT item of the same kind from its list and goes on.
ITEM_LISTS = json.loads(os.environ.get("QA_ITEM_LISTS") or "{}")
_REPLACED = {}  # saved item address -> the current item used instead (found once, then reused)


def _settle_quietly(page, ms):
    try:
        page.wait_for_load_state("networkidle", timeout=ms)
    except Exception:
        pass  # some sites never go fully idle


def _goto_current_item(real_goto):
    def goto(self, url, *args, **kwargs):
        path = urlparse(str(url)).path
        rx = next((r for r in ITEM_LISTS if re.match(r, path)), None)
        if not rx:
            return real_goto(self, url, *args, **kwargs)
        if str(url) in _REPLACED:
            return real_goto(self, _REPLACED[str(url)], *args, **kwargs)
        item = path.rstrip("/").rsplit("/", 1)[-1]
        gone = []  # the page itself, or the data it loads for this item, answered "not found"
        watch = lambda r: gone.append(r.url) if r.status in (404, 410) and item in r.url else None  # noqa: E731
        Page.on(self, "response", watch)
        try:
            resp = real_goto(self, url, *args, **kwargs)
            _settle_quietly(self, 5000)
        finally:
            self.remove_listener("response", watch)
        if not gone:
            return resp
        real_goto(self, ITEM_LISTS[rx])
        _settle_quietly(self, 8000)
        hrefs = self.eval_on_selector_all("a[href]", "links => links.map(a => a.href)")
        fresh = next((h for h in hrefs if re.match(rx, urlparse(h).path) and item not in h), None)
        if not fresh:
            return resp
        print(f"[data changed] {url} no longer exists - testing the same kind of page: {fresh}")
        _REPLACED[str(url)] = fresh
        return real_goto(self, fresh, *args, **kwargs)
    return goto


if ITEM_LISTS and not getattr(Page, "_qa_items", False):
    Page._qa_items = True  # patch only once
    Page.goto = _goto_current_item(Page.goto)


if not getattr(Locator, "_qa_guarded", False):
    Locator._qa_guarded = True  # patch only once
    for _n in ("click", "dblclick", "tap", "check", "set_checked"):
        setattr(Locator, _n, _guarded(getattr(Locator, _n)))
        setattr(Page, _n, _page_guarded(getattr(Page, _n)))
    for _n in ("press", "dispatch_event"):  # Enter / Space on a button, or a click event sent by code
        setattr(Locator, _n, _guarded(getattr(Locator, _n), key_arg=True))
        setattr(Page, _n, _page_guarded(getattr(Page, _n), key_arg=True))

if not getattr(Locator, "_qa_stepped", False):  # (around the guard: a refused click is Blocked, never a step)
    Locator._qa_stepped = True  # patch only once
    for _n, _verb in ACTION_WORDS.items():
        setattr(Locator, _n, _stepped(getattr(Locator, _n), _verb))
    Page.goto = _goto_stepped(Page.goto)


class _Browser:
    """The run's browser - started again when it went away (its window was closed by hand, or Chrome stopped), so the
    remaining tests of this browser still run instead of all failing on a closed window."""

    def __init__(self, pw):
        self.pw, self.b = pw, None

    def _now(self):
        if self.b is None or not self.b.is_connected():
            self.b = self.pw.chromium.launch(headless=HEADLESS, slow_mo=0, args=[] if HEADLESS else WINDOW_ARGS)
        return self.b

    def new_context(self, **opts):
        return self._now().new_context(**opts)

    def close(self):
        try:
            if self.b is not None:
                self.b.close()
        except Exception:
            pass  # (it was closed already)

    def __getattr__(self, name):
        return getattr(self._now(), name)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as pw:
        b = _Browser(pw)
        yield b
        b.close()


AUTH_STATE = os.environ.get("QA_AUTH_STATE", "")  # saved login of the test account (made by the crawler)
ROLE_STATES = json.loads(os.environ.get("QA_ROLE_STATES") or "{}")  # role -> its saved login (several user roles)

# The website ended the test account's session (it logged everyone out, the session timed out, a test sent a form that
# ends it): every later test only saw the login page, and the login page was reported as the website's failure
# (OrangeHRM: 343 of 347 failures). Like the crawler: sign in again and open the page again. A login another browser
# of this run made is used first (some websites allow one session per account); each browser signs in itself at most
# 3 times. Still logged out: the test is inconclusive - it says nothing about the page.
LOGIN = json.loads(os.environ.get("QA_LOGIN_FORM") or "{}")  # {"page", "at", "user", "password", "submit"}
LOGIN_PATHS = {urlparse(LOGIN.get("at") or LOGIN.get("page") or "").path.rstrip("/")} if LOGIN else set()
LOGGED_OUT = ("Inconclusive: logged out - the website ended the test account's session (its login page came back), "
              "so this test says nothing about the page")
_SESSION = {"loaded": 0.0, "relogins": 0}  # when this browser took the saved login; how often it signed in again


def _visible(page, selector) -> bool:
    try:
        return bool(selector) and page.locator(selector).first.is_visible()
    except Exception:
        return False


def _logged_out(page, asked=None) -> bool:
    """The login form is back: on the login page's address, or the page asked for went to one with the login form."""
    if not LOGIN or not _visible(page, LOGIN["password"]):
        return False
    here = urlparse(page.url).path.rstrip("/")
    if asked is None:
        return here in LOGIN_PATHS
    wanted = urlparse(str(asked)).path.rstrip("/")
    if wanted in LOGIN_PATHS:
        return False  # (the test opened the login page itself)
    return here in LOGIN_PATHS or (here != wanted and _visible(page, LOGIN["user"]))


def _adopt_saved_login(context) -> bool:
    """Another browser of this run signed in again since this one took the saved login: use its cookies."""
    if not AUTH_STATE:
        return False
    sandbox, _SANDBOX["thread"] = _SANDBOX["thread"], None  # (the saved login is closed to test code, not to this file)
    try:
        saved = Path(AUTH_STATE)
        if saved.stat().st_mtime <= _SESSION["loaded"]:
            return False
        _SESSION["loaded"] = saved.stat().st_mtime
        context.add_cookies(json.loads(saved.read_text(encoding="utf-8")).get("cookies") or [])
        return True
    except Exception:
        return False
    finally:
        _SANDBOX["thread"] = sandbox


def _save_login(context) -> None:
    """The new login, for the other browsers of this run (and the re-run of the failed tests)."""
    if not AUTH_STATE:
        return
    sandbox, _SANDBOX["thread"] = _SANDBOX["thread"], None
    try:
        tmp = Path(AUTH_STATE).with_name(f"auth.{os.getpid()}.tmp")
        context.storage_state(path=str(tmp))
        os.replace(tmp, AUTH_STATE)
        _SESSION["loaded"] = Path(AUTH_STATE).stat().st_mtime
    except Exception:
        pass
    finally:
        _SANDBOX["thread"] = sandbox


def _sign_in_again(context) -> bool:
    """Signs the test account in again with the crawler's login form, in a tab of its own (the test's tab keeps its
    listeners and its write guard). Its typing and clicks are no steps of the test."""
    user, password = os.environ.get("TEST_USERNAME", ""), os.environ.get("TEST_PASSWORD", "")
    if not (LOGIN and user and password) or _SESSION["relogins"] >= 3:
        return False
    _SESSION["relogins"] += 1
    item, _CURRENT["item"] = _CURRENT["item"], None
    guard, Locator._qa_guard = getattr(Locator, "_qa_guard", False), False  # (its own login button, never another)
    tab = None
    try:
        tab = context.new_page()
        tab.goto(LOGIN["page"])
        tab.locator(LOGIN["user"]).first.fill(user, timeout=8000)
        tab.locator(LOGIN["password"]).first.fill(password, timeout=5000)
        if _visible(tab, LOGIN.get("submit")):
            tab.locator(LOGIN["submit"]).first.click(timeout=5000)
        else:
            tab.locator(LOGIN["password"]).first.press("Enter")
        tab.locator(LOGIN["password"]).first.wait_for(state="hidden", timeout=15000)
        _settle_quietly(tab, 5000)
    except Exception:
        return False
    finally:
        Locator._qa_guard, _CURRENT["item"] = guard, item
        try:
            if tab is not None:
                tab.close()
        except Exception:
            pass
    _save_login(context)
    return True


def _goto_logged_in(real_goto):
    def goto(self, url, *args, **kwargs):
        resp = real_goto(self, url, *args, **kwargs)
        item = _CURRENT["item"]
        if item is None or getattr(item, "_qa_kind", "") != "user" or not _logged_out(self, url):
            return resp
        for again in (_adopt_saved_login, _sign_in_again):
            if again(self.context):
                resp = real_goto(self, url, *args, **kwargs)
                if not _logged_out(self, url):
                    _step("Signed in again: the website had ended the test account's session", True)
                    return resp
        item._qa_logged_out = True
        pytest.skip(LOGGED_OUT + "; signing in again did not work")
    return goto


if LOGIN and not getattr(Page, "_qa_relogin", False):
    Page._qa_relogin = True  # patch only once (outermost: after the steps, the item lists and the page waits)
    Page.goto = _goto_logged_in(Page.goto)

STATUS_HTML = """<html><body style="margin:0;height:100vh;display:grid;place-items:center;background:#0f172a;
  font-family:system-ui,sans-serif;color:#e2e8f0"><div style="text-align:center;max-width:80vw">
  <div style="font-size:15px;letter-spacing:.12em;text-transform:uppercase;color:#94a3b8">Qpilot &middot; {title}</div>
  <div style="font-size:26px;font-weight:700;margin-top:14px;word-break:break-all">{text}</div>
  <div style="font-size:14px;color:#94a3b8;margin-top:10px">{note}</div></div></body></html>"""


def _status(page, title: str, text: str, note: str = "") -> None:
    """When you watch the tests in Chrome: show what is happening right now, instead of an empty white window
    (between tests, and while links are checked in the background). Does nothing when the browser is hidden."""
    if HEADLESS:
        return
    import html
    try:
        page.set_content(STATUS_HTML.format(title=html.escape(title), text=html.escape(text), note=html.escape(note)))
    except Exception:
        pass  # only a visual aid - never let it break a test


RAISE_FLAGS = 0x0001 | 0x0002 | 0x0010  # SetWindowPos: keep its size and place, never take the keyboard
FIT_FLAGS = 0x0010 | 0x0040  # SetWindowPos: resize/move, show, never take the keyboard


def _to_front(page) -> None:
    """Visible Chrome on Windows: a window opened by a program running in the background opens BEHIND the open windows
    (Nov 3, 2026: "nothing was showing"). Raised above them once, without taking the keyboard. Found by a unique title
    the page gets for a moment. (The same as _to_front in backend/agents/discovery.py.)"""
    if HEADLESS or os.name != "nt":
        return
    import uuid
    from ctypes import wintypes
    mark = f"agentic-qa-{uuid.uuid4().hex[:10]}"
    try:
        old = page.evaluate("t => { const o = document.title; document.title = t; return o; }", mark)
    except Exception:
        return
    try:
        user32, found = ctypes.WinDLL("user32"), []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def each(hwnd, _):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if mark in buf.value:
                    found.append(hwnd)
            return True
        for _ in range(15):  # (the window's title follows the page's within a moment)
            user32.EnumWindows(each, 0)
            if found:
                break
            time.sleep(0.1)
        if found:
            if user32.IsIconic(found[0]):
                user32.ShowWindow(found[0], 4)  # minimized -> shown again, without taking the keyboard
            work = wintypes.RECT()
            user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0)  # usable desktop, excluding taskbar
            w, h = work.right - work.left, work.bottom - work.top
            user32.SetWindowPos(found[0], -1, work.left, work.top, w, h, FIT_FLAGS)
            user32.SetWindowPos(found[0], -2, work.left, work.top, w, h, FIT_FLAGS)
    except Exception:
        pass  # (only how it looks)
    finally:
        try:
            page.evaluate("t => { document.title = t; }", old)
        except Exception:
            pass


@pytest.fixture
def qa_status(page):
    """qa_status(title, text, note='') -> shows a status screen in the visible browser window."""
    return lambda title, text, note="": _status(page, title, text, note)


def pytest_configure(config):
    config.addinivalue_line("markers", "guest: runs as a visitor who is NOT logged in (login / register pages)")
    config.addinivalue_line("markers", "xdist_group(name): tests that change the same data (the cart) - one after "
                                       "another, in one browser")


# The end-to-end journeys run FIRST, the link checks LAST (pytest would run the files alphabetically,
# which put the many link checks first). Same order as RUN_ORDER in backend/excel.py.
RUN_ORDER = (("test_journeys", 0), ("test_checks", 1), ("test_flows", 1), ("test_forms", 1), ("test_site", 2),
             ("_data", 3), ("test_all_links", 4), ("test_cleanup", 9))


def pytest_collection_modifyitems(config, items):
    def rank(item):
        name = Path(str(item.fspath)).name
        return next((r for key, r in RUN_ORDER if key in name), 2)
    # visible Chrome: ONE window - the visitor tests of a group together, then the logged-in ones (each switch
    # closes one window and opens the other). Stable: the tests of one kind keep their order.
    items.sort(key=(lambda i: (rank(i), not i.get_closest_marker("guest"))) if not HEADLESS else rank)


# The browser's own message boxes (alert / confirm / prompt) are how many websites answer ("Product added."): written
# down on every page so the tests can read them (window.__qaDialogs); the box itself still opens and Playwright closes
# it (a confirm is answered "Cancel" - never accepted). 'Print' is written down instead of opening the print dialog.
# (the same script as backend/observe.py DIALOG_INIT_JS)
DIALOG_JS = r"""(() => {
  if (window.__qaDialogs) return;
  const said = window.__qaDialogs = [];
  for (const kind of ['alert', 'confirm', 'prompt']) {
    const real = window[kind];
    if (typeof real !== 'function') continue;
    window[kind] = function (msg) {
      try { said.push(kind + ': ' + String(msg === undefined ? '' : msg).trim().slice(0, 200)); } catch (e) {}
      return real.apply(this, arguments);
    };
  }
  window.print = function () { try { said.push('print: the print dialog opened'); } catch (e) {} };
})();"""


@pytest.fixture(scope="session")
def _shared(browser):
    """ONE browser window per session for the whole test run (it doesn't open/close for every test):
    'guest' = a visitor, 'user' = logged in with the test account (only when the website has a login)."""
    shared = {}

    def make(kind):
        # (downloads are accepted so a download link can be checked: the browser keeps them in its own temporary
        # folder, deleted with the window - a test never saves a file anywhere)
        opts = {"viewport": {"width": 1366, "height": 900}, "ignore_https_errors": True, "accept_downloads": True}
        if BASE_URL:
            opts["base_url"] = BASE_URL
        if kind == "user":
            opts["storage_state"] = AUTH_STATE
            _SESSION["loaded"] = Path(AUTH_STATE).stat().st_mtime
        elif kind.startswith("role:"):  # (another user role: its own saved login - never its password)
            opts["storage_state"] = ROLE_STATES[kind[5:]]
        if VIDEO_DIR:  # (the video is complete when the window closes at the end of the run)
            opts.update(record_video_dir=VIDEO_DIR, record_video_size={"width": 1366, "height": 900})
        context = browser.new_context(**opts)
        context.set_default_timeout(10000)
        context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        _guard(context)
        context.add_init_script(DIALOG_JS)
        if RECORD_TRACES:
            try:
                context.tracing.start(screenshots=True, snapshots=True)
            except Exception:
                pass
        shared[kind] = {"context": context, "page": context.new_page()}
        _to_front(shared[kind]["page"])  # (visible Chrome: its new window in front of the other programs)
        return shared[kind]

    def only(kind):
        """Visible Chrome: the run shows ONE window (Nov 3, 2026: several at once were hard to follow) - the other
        kinds' windows close; their logins stay saved and a later test of that kind opens its window again."""
        if HEADLESS:
            return
        for other in [k for k in shared if k != kind and (k in ("guest", "user") or k.startswith("role:"))]:
            try:
                shared.pop(other)["context"].close()
            except Exception:
                pass  # (its window was closed already)

    shared["make"], shared["only"] = make, only
    yield shared
    for kind in [k for k in shared if k == "guest" or k == "user" or k.startswith("role:")]:
        try:
            shared[kind]["context"].close()
        except Exception:
            pass  # (its window was closed earlier)


def _name(item) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", item.nodeid)[-100:]


def _redact_zip(path: Path) -> None:
    """A trace records what was typed and sent (also the test password): replace it with [REDACTED]."""
    secrets = [s.encode("utf-8") for s in _secrets()]
    if not secrets or not path.exists():
        return
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            for s in secrets:
                data = data.replace(s, REDACTED.encode())
            dst.writestr(info, data)
    tmp.replace(path)


@pytest.fixture
def page(_shared, request):
    """The shared tab, cleaned before each test so every test still starts fresh.
    Logged in with the test account when the website has a login, except for tests marked 'guest'."""
    kind = "user" if AUTH_STATE and Path(AUTH_STATE).exists() and not request.node.get_closest_marker("guest") \
        else "guest"
    _shared["only"](kind)
    tab = _shared.get(kind) or _shared["make"](kind)
    try:
        if tab["page"].is_closed():
            tab["page"] = tab["context"].new_page()
    except Exception:  # (its window / browser was closed by hand, or Chrome stopped): a new one, the login kept
        tab = _shared["make"](kind)
    context = tab["context"]
    p = tab["page"]
    if not _website_answers(context):  # the website stopped answering: this test is not run (no waiting for it)
        request.node._qa_down = True
        _status(p, "Website not answering", request.node.name, f"down since {_DOWN['since']} - this test is not run")
        pytest.skip(NOT_RUN_DOWN.format(why=_DOWN["why"], since=_DOWN["since"]))
    if kind == "guest":
        context.clear_cookies()  # (the logged-in session keeps its login cookies)
    p.goto("about:blank")
    _status(p, "Next test", request.node.name)  # (visible browser: say what comes, instead of an empty window)
    request.node._qa_page = p
    request.node._qa_kind = kind
    Locator._qa_test_name = request.node.name
    Locator._qa_guard = True  # protected clicks are refused in every generated test ...
    Locator._qa_strict = Path(str(request.node.fspath)).name in AI_FILES  # ... and AI code can't approve any
    tracing = False
    if RECORD_TRACES:
        try:
            context.tracing.start_chunk(title=request.node.name)
            tracing = True
        except Exception:
            pass

    cov = _cov_start(p) if JS_COVERAGE else None  # (how much of the website's JavaScript this test runs)

    # remember every listener this test adds (page.on(...)) so it can be removed afterwards
    added, real_on = [], p.on
    def tracked_on(event, handler):
        added.append((event, handler))
        return real_on(event, handler)
    p.on = tracked_on

    yield p

    if cov is not None:
        _cov_save(cov)
    del p.on
    if tracing:  # keep the trace only when the test failed (it shows every step, with snapshots)
        try:
            if getattr(request.node, "_qa_trace", None):
                context.tracing.stop_chunk(path=request.node._qa_trace)
                _redact_zip(Path(request.node._qa_trace))
            else:
                context.tracing.stop_chunk()
        except Exception:
            pass
    if kind == "guest":  # a visitor test may have logged in (login journey): forget it, so the next visitor
        try:             # test is not logged in (cookies are cleared before each test; apps also keep logins here)
            if p.url.startswith("http"):
                p.evaluate("() => { try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} }")
        except Exception:
            pass
    for event, handler in added:
        try:
            p.remove_listener(event, handler)
        except Exception:
            pass
    for extra in context.pages:  # close popups / new tabs the test opened
        if extra is not p:
            extra.close()


# ---- JavaScript coverage (Chromium): the covered byte ranges of every script a test ran (backend/jscov.py merges)
JS_COVERAGE = os.environ.get("QA_JS_COVERAGE") == "1"


def _cov_start(page):
    try:
        cdp = page.context.new_cdp_session(page)
        cdp.send("Profiler.enable")
        cdp.send("Profiler.startPreciseCoverage", {"callCount": True, "detailed": True})
        return cdp
    except Exception:
        return None


def _cov_save(cdp) -> None:
    try:
        res = cdp.send("Profiler.takePreciseCoverage").get("result") or []
        cdp.send("Profiler.stopPreciseCoverage")
        cdp.detach()
    except Exception:
        return
    out = {}
    for script in res:
        url = script.get("url") or ""
        spans = sorted(((r["startOffset"], r["endOffset"], r["count"]) for f in script.get("functions") or []
                        for r in f.get("ranges") or []), key=lambda r: (r[0], -(r[1] - r[0])))
        if not url.startswith("http") or not spans:
            continue
        length = max(e for _s, e, _c in spans)
        marks = bytearray(length)
        for s, e, c in spans:
            marks[s:e] = (b"\x01" if c > 0 else b"\x00") * (e - s)
        covered, pos = [], 0
        while True:
            s = marks.find(1, pos)
            if s < 0:
                break
            e = marks.find(0, s)
            e = length if e < 0 else e
            covered.append([s, e])
            pos = e
        out[url] = {"length": length, "covered": covered}
    if out:
        d = RUN_DIR / "jscov"
        d.mkdir(exist_ok=True)
        worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
        with (d / f"tests_{worker}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(out) + "\n")


@pytest.fixture
def as_role(_shared):
    """as_role('viewer') -> a fresh tab signed in as that role (its saved login). Skipped when the role could not sign
    in while exploring."""
    def open_as(role: str):
        if role not in ROLE_STATES or not Path(ROLE_STATES[role]).exists():
            pytest.skip(f"the role '{role}' has no saved login (it could not sign in while exploring)")
        tab = _shared.get(f"role:{role}") or _shared["make"](f"role:{role}")
        if tab["page"].is_closed():
            tab["page"] = tab["context"].new_page()
        tab["page"].goto("about:blank")
        return tab["page"]
    return open_as


# ---- forms that send data (Steps 4 + 5)
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
# analytics / tracking beacons: dropped silently (they are no answer of the form)
ANALYTICS = re.compile(r"google-analytics|googletagmanager|analytics|doubleclick|facebook\.com/tr|hotjar|segment\.io|"
                       r"mixpanel|clarity\.ms|sentry|newrelic|/collect\b|/beacon\b|/track\b|/log\b", re.I)


@pytest.fixture
def write_guard(page):
    """The page may NOT send data (production / test): every POST / PUT / PATCH / DELETE it tries is stopped and written
    down as {method, path, size}. A form test then knows: a wrong value sent NOTHING (refused), valid values WOULD
    have been sent (accepted) - without anything reaching the website."""
    tried = []

    def handle(route):
        req = route.request
        if req.method in WRITE_METHODS:
            if not ANALYTICS.search(req.url):
                tried.append({"method": req.method, "path": urlparse(req.url).path,
                              "size": len(req.post_data_buffer or b"")})
            try:
                route.abort("blockedbyclient")
            except Exception:
                pass
            return
        try:
            route.fallback()
        except Exception:
            pass
    page.route("**/*", handle)
    yield tried
    try:
        page.unroute("**/*", handle)
    except Exception:
        pass


_TAGS = {"n": 0}


@pytest.fixture
def qa_tag():
    """new_tag() -> 'qa-<run>-<n>': test data a staging run creates carries it, so it can be found and cleaned up."""
    run = re.sub(r"\D", "", os.environ.get("QA_RUN_ID", ""))[-6:] or "run"
    worker = re.sub(r"\D", "", os.environ.get("PYTEST_XDIST_WORKER", "")) or "0"

    def new_tag():
        _TAGS["n"] += 1
        return f"qa-{run}-{worker}{_TAGS['n']}"
    return new_tag


@pytest.fixture
def track_created():
    """record(what, tag, where, status) - everything a staging test created (runs/<run>/created.jsonl): the report
    says what was cleaned up, and what is left for manual cleanup."""
    def record(what: str, tag: str, where: str, status: str = "created"):
        line = json.dumps({"what": what, "tag": tag, "where": where, "status": status, "time": time.time()})
        with (RUN_DIR / "created.jsonl").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    return record


@pytest.fixture
def created_so_far():
    """Everything the run created so far (for the cleanup at the end)."""
    f = RUN_DIR / "created.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


@pytest.fixture
def qa_login():
    """(user name, password) of the TEST account from .env (TEST_USERNAME / TEST_PASSWORD).
    Read when the test runs, so the password is never written into a test file."""
    user, password = os.environ.get("TEST_USERNAME", ""), os.environ.get("TEST_PASSWORD", "")
    if not (user and password):
        pytest.skip("no test account: set TEST_USERNAME and TEST_PASSWORD in .env")
    return user, password


def _why(error: str) -> str:
    """Playwright's long error log -> the reason in plain words (shown in the report)."""
    m = re.search(r"(<[a-z]+[^>]{0,80}>)[^\n]{0,20}intercepts pointer events", error)
    if "intercepts pointer events" in error:
        return ("it is covered by another part of the page" + (f" ({m.group(1)} is on top of it)" if m else "")
                + ", so a person can't click it there")
    if "element is not visible" in error:
        return "it is not visible on the page"
    if "outside of the viewport" in error:
        return "it is outside the visible part of the page"
    if "not enabled" in error:
        return "it is disabled"
    if "Page.goto" in error and "Timeout" in error:
        return "the page took too long to open"
    if "resolved to 0 elements" in error or ("waiting for locator" in error and "Timeout" in error):
        return "it was not found on the page"
    return ""


@pytest.fixture
def run_steps(page, console_errors, request):
    """Runs a large end-to-end test case step by step. Every step runs, even after one fails, and the
    test fails at the end with the list of the steps that failed (so one problem doesn't hide the others)."""
    import inspect

    def run(steps):
        failed, skipped = [], []
        for n, (title, step) in enumerate(steps, start=1):
            args = {"page": page, "console_errors": console_errors}
            try:
                if "qa_login" in inspect.signature(step).parameters:
                    args["qa_login"] = request.getfixturevalue("qa_login")
                step(**{k: v for k, v in args.items() if k in inspect.signature(step).parameters})
            except pytest.skip.Exception as e:
                skipped.append(f"step {n} '{title}': {e}")
            except TestTimeout:
                raise
            except Exception as e:
                msg = str(e).strip().splitlines()[0][:300] if str(e).strip() else type(e).__name__
                why = _why(str(e))
                # keep the element's address in the message (self-healing needs it to repair the step)
                loc = re.search(r"waiting for (locator\((['\"]).+?\2\))", str(e))
                failed.append(f"step {n} '{title}' failed: {type(e).__name__}: {msg}" + (f" - {why}" if why else "")
                              + (f" [{loc.group(1)}]" if loc and loc.group(1) not in msg else ""))
        if failed:
            raise AssertionError(f"{len(failed)} of {len(steps)} steps failed:\n" + "\n".join(failed))
        if skipped and len(skipped) == len(steps):
            pytest.skip("; ".join(skipped))
    return run


# A visitor's page asks the server "who is logged in?" and gets 401: normal for a visitor, not the website's error
VISITOR_401 = re.compile(r"Failed to load resource.*status of 401|\bunauthori[sz]ed\b", re.I)


def _foreign_load_error(m) -> bool:
    """'Failed to load resource' for ANOTHER website's file (a tracker, an ad): no JavaScript error of this website."""
    if not m.text.startswith("Failed to load resource"):
        return False
    try:
        host = urlparse((m.location or {}).get("url") or "").hostname or ""
    except Exception:
        return False
    return bool(host) and bool(ALLOWED_HOSTS) and not _approved(host)


# A style / font / picture asked for over http:// on an https:// page: the browser blocks it (or loads it over https).
# Worth fixing - the crawler reports it once for the site - but it is no JavaScript error and breaks nothing a visitor
# does, so it is a WARNING here, never a failed test (automationexercise.com: Google Fonts over http failed every
# journey and 13 checks). An insecure SCRIPT or data request stays an error: that can break the page.
PASSIVE_MIXED = re.compile(r"Mixed Content:.*\binsecure (stylesheet|font|image|video|audio|favicon|element)\b", re.I)
# the website complains that a tracker did not load - the sandbox stopped it (AD_RX): ours, a warning
# (practicesoftwaretesting.com: "Failed to load Google Analytics script" failed 2 journeys; backend/safety.py)
TRACKER_SAID = re.compile(os.environ.get("QA_TRACKER_SAID_RX") or r"(?!x)x", re.I)


def _ours(text: str) -> bool:
    return bool(PASSIVE_MIXED.search(text) or TRACKER_SAID.search(text))


def _is_error(m, guest: bool) -> bool:
    return (m.type == "error" and "ERR_BLOCKED_BY_CLIENT" not in m.text and not _foreign_load_error(m)
            and not _ours(m.text) and not (guest and VISITOR_401.search(m.text)))


def _last_step() -> str:
    item = _CURRENT["item"]
    steps = getattr(item, "_qa_steps", None) if item is not None else None
    return f" (after: {steps[-1]['text']})" if steps else ""


@pytest.fixture
def console_errors(page, request):
    """The website's errors while the test runs: console errors, uncaught exceptions and its own server's HTTP 5xx
    answers - each with the step that caused it. Console WARNINGS are written down with the result, never failed."""
    errors = []  # (a request the sandbox blocked is not the website's error)
    guest = getattr(request.node, "_qa_kind", "") == "guest"
    warnings = request.node.__dict__.setdefault("_qa_warnings", [])
    page.on("console", lambda m: errors.append(m.text + _last_step()) if _is_error(m, guest) else
            warnings.append(m.text[:200]) if (m.type == "warning" or _ours(m.text))
            and len(warnings) < 20 else None)
    page.on("pageerror", lambda e: (warnings.append(f"JS exception: {e}"[:200]) if len(warnings) < 20 else None)
            if TRACKER_SAID.search(str(e)) else errors.append(f"JS exception: {e}{_last_step()}"))

    def server_error(resp):
        try:
            host = (urlparse(resp.url).hostname or "").lower()
            if resp.status >= 500 and ALLOWED_HOSTS and _approved(host):  # (never another website's tracker)
                errors.append(f"HTTP {resp.status} from the website's server: {resp.request.method} "
                              f"{urlparse(resp.url).path}{_last_step()}")
        except Exception:
            pass
    page.on("response", server_error)
    return errors


def _record(entry):
    entry = {k: _redact(v) for k, v in entry.items()}  # (the test password never reaches the results)
    with RESULTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    # record the test-body result, or a setup/teardown error (and a test not run because the website was down)
    down = rep.when == "setup" and rep.skipped and getattr(item, "_qa_down", False)
    if rep.when == "call" or (rep.when in ("setup", "teardown") and rep.failed) or down:
        entry = {
            "nodeid": item.nodeid,
            "file": Path(str(item.fspath)).name,
            "test": item.name,
            "outcome": rep.outcome if rep.when == "call" or down else "error",
            "duration_s": round(rep.duration, 2),
            "checks": getattr(item, "_qa_checks", 0),
            "error": None,
            "error_type": None,
            "screenshot": None,
            "trace": None,
            "url": None,
        }
        out = (rep.capstdout or "").splitlines() if rep.when == "call" else []
        said = lambda tag: [ln[len(f"[qa-{tag}] "):] for ln in out if ln.startswith(f"[qa-{tag}] ")]  # noqa: E731
        if rep.when == "call" and rep.passed and not entry["checks"]:
            # nothing was checked: a pass would prove nothing
            entry["outcome"] = "inconclusive"
            entry["error"] = "The test ran without failing, but it did not check anything (no assert / expect ran)."
        if rep.passed and said("inconclusive"):  # the test could not establish the expected result: `_inconclusive()`
            entry["outcome"] = "inconclusive"
            entry["error"] = "Inconclusive: " + "; ".join(dict.fromkeys(said("inconclusive")))[:500]
        # steps this website did not allow (e.g. no quantity control in the cart): `_note()` printed them
        notes = said("note")
        if notes:
            entry["note"] = "; ".join(dict.fromkeys(notes))[:400]
        if said("step"):  # the steps of a journey that were verified, in order (`_step_ok()`)
            entry["steps"] = said("step")[:30]
        if getattr(item, "_qa_warnings", None):  # (the browser's console warnings: listed, never a failure)
            entry["warnings"] = list(dict.fromkeys(item._qa_warnings))[:10]
        live = list(getattr(item, "_qa_steps", []))  # every step it did, in order - the failing one marked
        if live:
            if rep.failed and not any(s.get("ok") is False for s in live):
                reason = (call.excinfo.exconly().splitlines()[0] if call.excinfo is not None else "failed")[:120]
                live.append({"text": f"Check failed: {reason}", "ok": False, "t": live[-1].get("t")})
            entry["live_steps"] = live
        if rep.skipped and isinstance(rep.longrepr, tuple):  # why it was skipped (e.g. "Blocked: ...")
            entry["error"] = str(rep.longrepr[2]).removeprefix("Skipped: ")[:500]
        if rep.skipped and getattr(item, "_qa_logged_out", False):  # (could not sign in again: no answer, no skip)
            entry["outcome"] = "inconclusive"
        if rep.failed:  # the start (which check, "element(s) not found") AND the end (call log, page snapshot)
            text = str(rep.longreprtext)
            entry["error"] = text if len(text) <= 2500 else text[:1200] + "\n[...]\n" + text[-1300:]
            if call.excinfo is not None:
                entry["error_type"] = call.excinfo.typename
            p = getattr(item, "_qa_page", None)
            if p is not None and not p.is_closed():
                path = SHOT_DIR / f"{_name(item)}_{int(time.time())}.png"
                try:
                    entry["url"] = p.url
                    p.screenshot(path=str(path), full_page=True)
                    entry["screenshot"] = str(path)
                except Exception:
                    pass
                # the session ended DURING the test: the login page is no failure of the page this test is about
                if rep.when == "call" and getattr(item, "_qa_kind", "") == "user" and _logged_out(p):
                    entry["outcome"] = "inconclusive"
                    entry["error"] = LOGGED_OUT + "\n" + entry["error"]
            if RECORD_TRACES and rep.when == "call":  # saved when the page fixture ends (just after this)
                TRACE_DIR.mkdir(parents=True, exist_ok=True)
                item._qa_trace = str(TRACE_DIR / f"{_name(item)}.zip")
                entry["trace"] = item._qa_trace
        if entry["outcome"] == "inconclusive" and not entry.get("screenshot"):
            p = getattr(item, "_qa_page", None)
            if p is not None and not p.is_closed():
                try:
                    path = SHOT_DIR / f"{_name(item)}_{int(time.time())}.png"
                    p.screenshot(path=str(path), full_page=True)
                    entry.update(screenshot=str(path), url=p.url)
                except Exception:
                    pass  # the unavailable screenshot is not a passing check
        _event(entry.get("error") or "Test finished", entry["outcome"], checks=entry["checks"])
        _record(entry)
    if rep.when == "call":
        _CURRENT["item"] = None


def pytest_collectreport(report):
    # a generated file that can't even be imported
    if report.failed:
        _record({"nodeid": report.nodeid, "file": Path(report.nodeid).name, "test": "(collection)",
                 "outcome": "error", "duration_s": 0, "error": str(report.longreprtext)[-2500:],
                 "error_type": "CollectionError", "screenshot": None, "url": None, "checks": 0, "trace": None})
