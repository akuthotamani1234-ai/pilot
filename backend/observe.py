"""Learn what every control of a page DOES: observe -> act -> verify -> expand.

For each eligible control, ONE action at a time, from a fresh page:
  snapshot (address, visible text lines, values of the boxes, listed items, shown messages, visible controls / links)
  -> act (click / choose another option / tick)  -> wait until the page settles  -> snapshot again
  -> the difference is the EVIDENCE of what the action does:
       effect    navigates | list | message | value | panel | scroll | text | picture | nothing
       message   what the website said (toast / status line / the browser's alert box, 'print: ...' for the print
                 dialog) and its tone: ok | error | login_needed
       scroll    the page moved ('Back to top')
       picture   the pictures shown by the control's own widget changed (an image slider, a product gallery)
       new       addresses and controls that appeared (a panel's buttons, a "Compare (1)" link ...)
Controls that appear only after an action (a help panel's buttons) are added to the page with `revealed_by`, and
learned too (opener first). New addresses go back to the crawler's queue.

Which actions: safe ones; reversible test-account ones (add to cart / favourites / quantity / options) only on a test
or staging environment. Protected actions (pay, order, delete, send, log out ...) are never performed - they are
recorded as blocked, with the reason. Every limit that stops the learning is counted (crawl.json -> "actions").
"""
import hashlib
import json
import re
import time
from collections import Counter
from urllib.parse import urlparse

from . import runctl
from .actions import action_class, action_risk, blocked_reason
from .config import settings
from .page_inventory import capture_after_action

# The browser's own message boxes (alert / confirm / prompt) are what many websites answer with ("Product added.").
# Added to every page before its scripts run: it only WRITES DOWN the message, then lets the box open as usual
# (Playwright closes it: an alert is dismissed, a confirm is answered "Cancel" - never accepted). 'Print' opens the
# browser's print dialog, which would hold the window: it is written down instead ('print: ...') - its effect.
# (the same script is in templates/conftest.py for the generated tests)
DIALOG_INIT_JS = r"""(() => {
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

# What a website remembers in the browser (not its cookies: a login may live there): the keys before the actions of
# a page are learned, and afterwards the ones they added are removed (Explorer.explore)
STORAGE_KEYS_JS = "() => ({origin: location.origin, local: Object.keys(localStorage), session: Object.keys(sessionStorage)})"
FORGET_ADDED_JS = r"""before => { let n = 0;
  for (const [store, keys] of [[localStorage, before.local], [sessionStorage, before.session]])
    for (const k of Object.keys(store)) if (!keys.includes(k)) { store.removeItem(k); n++; }
  return n; }"""

# A cookie / consent banner lies over the page and its buttons ("... intercepts pointer events"): it is closed with
# the LEAST consent it offers - reject / only necessary first, then close / dismiss / got it / OK, accept only when it
# is the only choice. Only a banner about cookies / consent - never another popup (a newsletter, a login form, the
# thing a test is about). (the same script is in templates/conftest.py for the generated tests)
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


def close_consent(page) -> str:
    """Close a cookie / consent banner (see CLOSE_CONSENT_JS). Returns the button that was used ('' = none)."""
    try:
        used = page.evaluate(CLOSE_CONSENT_JS)
        if used:
            page.wait_for_timeout(400)
        return used or ""
    except Exception:
        return ""  # (the page is navigating)


# what a person sees: text lines, box values, listed items, messages, controls and links
SNAPSHOT_JS = r"""(itemSel) => {
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
                     return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const name = e => (e.getAttribute('aria-label') || (e.labels && e.labels[0] ? e.labels[0].innerText : '')
                     || e.innerText || e.value || e.getAttribute('title') || e.getAttribute('placeholder') || '')
                    .trim().split('\n')[0].slice(0, 50);
  // open shadow roots (web components, nested too): their text and boxes are what a person sees as well
  const roots = [];
  const walk = (r, depth) => r.querySelectorAll('*').forEach(e => {
    if (e.shadowRoot && roots.length < 40) { roots.push(e.shadowRoot); if (depth < 5) walk(e.shadowRoot, depth + 1); } });
  walk(document, 0);
  const shadowLines = roots.flatMap(r => [...r.children].filter(e => !['STYLE', 'SCRIPT'].includes(e.tagName))
                                        .map(e => e.innerText || '')).join('\n').split('\n')
                      .map(s => s.trim()).filter(Boolean).map(s => '[shadow] ' + s);
  const lines = (document.body ? document.body.innerText : '').split('\n').map(s => s.trim()).filter(Boolean)
                .concat(shadowLines).slice(0, 800);
  const values = {};
  [document, ...roots].forEach((r, ri) => r.querySelectorAll('input, select, textarea').forEach((i, n) => {
    if (['hidden', 'password', 'file'].includes(i.type)) return;
    const k = (ri ? '[shadow] ' : '') + (i.id || i.name || i.getAttribute('aria-label') || ('#' + n));
    values[k] = (i.type === 'checkbox' || i.type === 'radio') ? String(i.checked) : String(i.value).slice(0, 80); }));
  const MSG = '[role=alert], [role=status], [aria-live], [class*=toast i], [class*=alert i], [class*=snack i], ' +
              '[class*=notif i], [class*=msg i], [class*=message i], [class*=error i], [class*=success i]';
  const messages = [...new Set([...document.querySelectorAll(MSG)].filter(e => vis(e)
                   && !e.closest('.vjs-control, .vjs-control-bar, [role=timer]'))
                   .map(e => (e.innerText || '').trim()).filter(t => t && t.length < 200))];
  const controls = [...document.querySelectorAll('button, [role=button], [role=tab], summary, input, select, textarea, a[href]')]
                   .filter(vis).map(e => e.tagName.toLowerCase() + '|' + name(e) + '|' + (e.getAttribute('href') || '')).slice(0, 500);
  const shown = [...document.querySelectorAll('a[href]')].filter(vis).slice(0, 500);
  const links = shown.map(a => a.href);
  const linkTexts = Object.fromEntries(shown.map(a => [a.href, (a.innerText || '').trim().slice(0, 60)]));
  const items = itemSel ? [...document.querySelectorAll(itemSel)].map(e => (e.innerText || '').trim().split('\n')[0].slice(0, 60)) : [];
  const dialog = !!document.querySelector('dialog[open], [role=dialog]:not([hidden]), [aria-modal=true], .modal.show');
  return { url: location.href, lines, values, messages, controls, links, linkTexts, items: items.slice(0, 60), dialog,
           dialogs: (window.__qaDialogs || []).slice(0, 50), scroll: Math.round(window.scrollY || 0),
           headings: [...document.querySelectorAll('h1, h2, h3')].filter(vis).map(h => h.innerText.trim()).slice(0, 20) };
}"""

def snapshot(page, item_sel=None) -> dict:
    """SNAPSHOT_JS of the page AND of its same-site frames (an iframe's button changes the frame, not the page)."""
    snap = page.evaluate(SNAPSHOT_JS, item_sel)
    host = urlparse(page.url).hostname
    for fr in page.frames[1:20]:
        try:
            if fr.is_detached() or urlparse(fr.url or "").hostname not in (host, None) \
                    or (fr.url or "").startswith("chrome-error:"):
                continue
            s = fr.evaluate(SNAPSHOT_JS, None)
        except Exception:
            continue
        snap["lines"] += [f"[frame] {l}" for l in s["lines"][:300]]
        snap["values"].update({f"[frame] {k}": v for k, v in s["values"].items()})
        snap["messages"] += [m for m in s["messages"] if m not in snap["messages"]]
        snap["controls"] += [f"[frame] {c}" for c in s["controls"][:200]]
        snap["dialogs"] = (snap.get("dialogs") or []) + (s.get("dialogs") or [])
    return snap


# The pictures a control's own WIDGET shows (an image slider's arrow, a gallery's thumbnail): the nearest box around
# the control that holds pictures (not the whole page). REGION_JS marks that box and returns which pictures are
# shown in it (hidden slides and slides moved out of their frame do not count); PICTURES_JS reads them again later.
# None = the control has no widget of its own.
PICTURES_FN = r"""const shownPictures = box => {
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
                     return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0'; };
  const framed = e => { const r = e.getBoundingClientRect();  // still inside every frame that cuts off overflow?
    for (let a = e.parentElement, n = 0; a && n < 12; a = a.parentElement, n++) {
      const s = getComputedStyle(a);
      if (s.opacity === '0' || s.display === 'none') return false;  // (a slide faded out / hidden)
      if (s.overflow !== 'visible' || s.overflowX !== 'visible') {
        const q = a.getBoundingClientRect();
        if (r.right <= q.left + 1 || r.left >= q.right - 1 || r.bottom <= q.top + 1 || r.top >= q.bottom - 1) return false;
      }
      if (a === box) break;
    }
    return true; };
  const pics = [...box.querySelectorAll('img, [style*="background-image"]')].filter(e => vis(e) && framed(e))
    .map(e => e.tagName === 'IMG' ? (e.currentSrc || e.src || '').slice(-120) : e.style.backgroundImage.slice(-120));
  return pics.slice(0, 40).join(' | ');
};"""
REGION_JS = "(el) => {" + PICTURES_FN + r"""
  for (let a = el.parentElement, n = 0; a && n < 8 && !/^(BODY|HTML|MAIN)$/.test(a.tagName); a = a.parentElement, n++) {
    const own = [...a.querySelectorAll('img, [style*="background-image"]')].filter(i => !el.contains(i));
    if (!own.length) continue;
    if (own.length > 40 || a.matches('[role=main], #main, #content, form')) return null;  // that is the page, not a widget
    document.querySelectorAll('[data-qa-region]').forEach(x => x.removeAttribute('data-qa-region'));
    a.setAttribute('data-qa-region', '1');
    return shownPictures(a);
  }
  return null;
}"""
PICTURES_JS = "() => {" + PICTURES_FN + r"""
  const box = document.querySelector('[data-qa-region]');
  return box ? shownPictures(box) : null;
}"""

LOGIN_NEEDED = re.compile(r"\b(log ?in|sign ?in|signed in|logged in|un ?authori[sz]ed|not authori[sz]ed|"
                          r"session (has )?expired|please (log|sign)|create an account)\b", re.I)
# (a whole word - not part of a name joined by a hyphen: 'Server-Sent Events feed' says nothing was sent, 'error-free'
# is no error)
ERROR = re.compile(r"(?<![\w-])(error|failed|failure|could ?n[o']t|can ?not|can't|unable|invalid|not allowed|forbidden|"
                   r"denied|out of stock|unavailable|went wrong|problem|too many)(?![\w-])", re.I)
OK = re.compile(r"(?<![\w-])(added|saved|success(fully)?|updated|removed|thank(s| you)?|done|copied|subscribed|sent|"
                r"created|applied|we will|we'll|confirmed)(?![\w-])", re.I)


def tone(message: str | None) -> str:
    """'ok' | 'error' | 'login_needed' | '' (a neutral text) - how the website's message sounds."""
    if not message:
        return ""
    if LOGIN_NEEDED.search(message):
        return "login_needed"
    if ERROR.search(message):
        return "error"
    return "ok" if OK.search(message) else ""


def _place(url: str) -> tuple:
    """(host, path, single-page-app route) - query / plain #anchors don't make another page."""
    p = urlparse(url or "")
    route = p.fragment if p.fragment.startswith(("/", "!/")) else ""
    return p.hostname, p.path.rstrip("/") or "/", route


def fingerprint(snap: dict) -> str:
    """The page STATE: same address + same headings / controls / listed items = the same state."""
    key = json.dumps([_place(snap["url"]), snap["headings"], sorted(set(snap["controls"]))[:200], snap["items"][:20]])
    return hashlib.sha1(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


SCROLLED = 150  # pixels: the page moved this far = the control scrolls it
# a control that stays in place while the page scrolls (position: fixed / sticky - a 'Back to top' button)
FLOATING_JS = """e => { for (let a = e; a && a !== document.body; a = a.parentElement) {
  const p = getComputedStyle(a).position; if (p === 'fixed' || p === 'sticky') return true; } return false; }"""


def diff(before: dict, after: dict, pictures_changed: bool = False) -> dict:
    """What changed between two snapshots -> the evidence of one action. `pictures_changed`: the control's own
    widget shows other pictures now (an image slider moved on)."""
    old_lines = set(before["lines"])
    added = [l for l in after["lines"] if l not in old_lines]
    removed = [l for l in before["lines"] if l not in set(after["lines"])]
    said_before, said = before.get("dialogs") or [], after.get("dialogs") or []
    # the browser's message boxes first: the most direct answer (another page = its own list of boxes)
    new_boxes = said[len(said_before):] if said[:len(said_before)] == said_before else said
    msgs = [m for m in new_boxes if m] + [m for m in after["messages"] if m not in before["messages"]]
    # (a box whose value changed - not a box that appeared: sorting a table shows other rows' tick boxes)
    values = {k: [before["values"][k], v] for k, v in after["values"].items()
              if k in before["values"] and before["values"][k] != v}
    new_controls = [c for c in after["controls"] if c not in set(before["controls"])]
    new_links = [h for h in after["links"] if h not in set(before["links"])]
    # links whose text changed ("Cart (0)" -> "Cart (1)"): the page behind them changed too
    changed_links = [h for h, t in after["linkTexts"].items() if h in before["linkTexts"] and before["linkTexts"][h] != t]
    moved = _place(after["url"]) != _place(before["url"])
    same_page_new_query = not moved and after["url"].split("#")[0] != before["url"].split("#")[0]
    list_changed = bool(after["items"] or before["items"]) and after["items"] != before["items"]
    # (a line inside a web component - '[shadow] Subscribed' - is its text, not a message the website showed: the
    # tests read messages from the page's message boxes, which a component's text is not)
    message = msgs[0] if msgs else next((l for l in added if tone(l) and not l.startswith("[shadow] ")), "")
    if moved:
        effect = "navigates"
    elif list_changed or same_page_new_query:
        effect = "list"
    elif message:
        effect = "message"
    elif values:
        effect = "value"
    elif new_controls or (after["dialog"] and not before["dialog"]):
        effect = "panel"
    elif abs((after.get("scroll") or 0) - (before.get("scroll") or 0)) >= SCROLLED:
        effect = "scroll"  # 'Back to top', a link to a part of the page: the page moved
    elif added or removed:
        effect = "text"
    elif pictures_changed:
        effect = "picture"
    else:
        effect = "nothing"
    return {"effect": effect, "message": message[:200], "tone": tone(message), "to": after["url"] if moved else "",
            "values": dict(list(values.items())[:6]), "list_changed": list_changed,
            "new_controls": new_controls[:20], "new_links": new_links[:20], "changed_links": changed_links[:10],
            "added": added[:8], "removed": removed[:8], "state": fingerprint(after)}


AUTOSCROLL_JS = "() => { window.scrollTo(0, document.body ? document.body.scrollHeight : 0); return document.body ? document.body.scrollHeight : 0; }"


def autoscroll(page, steps: int = 12) -> bool:
    """Scroll down until the page stops growing (content that loads while you scroll), then back to the top.
    True = more content appeared."""
    try:
        start = last = page.evaluate("() => document.body ? document.body.scrollHeight : 0")
        for _ in range(steps):
            page.evaluate(AUTOSCROLL_JS)
            page.wait_for_timeout(350)
            h = page.evaluate("() => document.body ? document.body.scrollHeight : 0")
            if h == last:
                break
            last = h
        page.evaluate("() => window.scrollTo(0, 0)")
        return last > start
    except Exception:
        return False  # (a page that navigated away meanwhile)


STORAGE_JS = """() => [JSON.stringify(Object.entries(localStorage)), JSON.stringify(Object.entries(sessionStorage))]"""
RESTORE_JS = """([l, s]) => { localStorage.clear(); sessionStorage.clear();
  for (const [k, v] of JSON.parse(l)) localStorage.setItem(k, v); for (const [k, v] of JSON.parse(s)) sessionStorage.setItem(k, v); }"""

# at most this many controls of one kind per page (22 category boxes, 7 page buttons ... a few show what they do).
# Prefer page content over global chrome / table-row toggles when the budget is tight (see _explore sort).
KIND_CAP = {"next": 2, "slide": 2, "tab": 4, "tick": 3, "select": 3, "repeated": 2}
# a form's button that only reads (lists, filters) - it may be clicked while exploring even when the page's script
# sends its form; any other button of such a form ('In', 'Save', 'Add') sends data: only the form tests do that
READING_SUBMIT = re.compile(r"^\s*(search|filter|find|apply( filters?)?|show|view|go|look ?up|refresh)\b", re.I)


# what the AI saw in a page's picture that the page's controls don't stand for: tried too (up to SEEN_MAX per page).
# Boxes, lists and tables are left to the form / data / table tests; the menu and plain content are not controls.
SEEN_MAX = 3
SEEN_MAX_THOROUGH = 8
SEEN_SKIP = {"navigation", "content", "media", "list", "table", "search", "form", "filter", "sort"}
# Deterministic search words to expand catalog/list URLs (never submitted as pay/checkout).
SEARCH_SEED_WORDS = ("admin", "employee", "leave", "report", "settings", "user", "pim", "job")
# what a control found by its words really is: its clickable element, its form, its icon, its address
SEEN_CONTROL_JS = """e => {
  const c = e.closest('button, a[href], [role=button], [role=tab], [role=link], [role=menuitem], input, summary, label')
            || e;
  const f = c.closest('form'), i = c.querySelector ? c.querySelector('i, svg, img, [class*=icon]') : null;
  const type = (c.getAttribute('type') || (c.tagName === 'BUTTON' && f ? 'submit' : '')).toLowerCase();
  return { type, in_form: !!f, tag: (c.tagName || '').toLowerCase(),
           role: c.getAttribute('role') || ({A:'link', BUTTON:'button'})[c.tagName] || '',
           form_method: f ? (f.getAttribute('method') || (f.getAttribute('action') ? 'get' : 'script')).toLowerCase() : '',
           text: (c.innerText || c.value || c.getAttribute('aria-label') || '').trim().split('\\n')[0].slice(0, 80),
           icon: i ? `${i.getAttribute('class') || ''} ${i.getAttribute('aria-label') || ''}`.trim() : '',
           href: c.getAttribute('href') || '' }; }"""


# forms filled while exploring (Explorer.fill_forms): per page at most this many; what each box of a form shows
FILL_MAX_FORMS = 10
BOX_STATE_JS = """f => [...f.querySelectorAll('input, select, textarea')]
  .filter(i => !['hidden', 'submit', 'button', 'image', 'reset'].includes(i.type)).map(i => {
    const r = i.getBoundingClientRect(), s = getComputedStyle(i);
    const lab = (i.labels && i.labels[0] ? i.labels[0].innerText : '') || i.getAttribute('aria-label') || i.placeholder
                || i.name || i.id || i.type;
    return { name: lab.trim().split('\\n')[0].slice(0, 60), shown: r.width > 0 && r.height > 0
             && s.visibility !== 'hidden' && s.display !== 'none', enabled: !i.disabled && !i.readOnly }; })"""


def _same_page(a: str, b: str) -> bool:
    """The same address (without its #part and a trailing slash)."""
    return (a or "").split("#")[0].rstrip("/") == (b or "").split("#")[0].rstrip("/")


def _box_changes(before: list[dict], after: list[dict]) -> dict:
    """What filling / choosing changed in a form: boxes that appeared, disappeared, turned on, turned off."""
    was = {b["name"]: b for b in before}
    now = {b["name"]: b for b in after}
    return {"appeared": [n for n, b in now.items() if b["shown"] and not (was.get(n) or {}).get("shown")][:8],
            "disappeared": [n for n, b in was.items() if b["shown"] and not (now.get(n) or {}).get("shown")][:8],
            "turned_on": [n for n, b in now.items() if b["enabled"] and n in was and not was[n]["enabled"]][:8],
            "turned_off": [n for n, b in now.items() if not b["enabled"] and n in was and was[n]["enabled"]][:8]}


def sends_form(b: dict) -> bool:
    """Does clicking this button send its form? A submit button of a POST form, or of a form the page's own script
    sends (no method, no action: form_method 'script') - unless its words say it only reads (Search, Filter)."""
    if (b.get("type") or "").lower() != "submit" or not b.get("in_form"):
        return False
    method = b.get("form_method")
    if method == "get":  # (a GET form only reads: sent)
        return False
    return not (method == "script" and READING_SUBMIT.match(b.get("accname") or b.get("text") or ""))


class Explorer:
    """Learns what controls do over the whole crawl. A control shared by many pages (header, footer, the same product
    template) is learned once. `explore()` returns the new addresses found by acting."""

    def __init__(self, extract_js: str, settle, deadline: float, before_goto=None, tag_base: str = "run",
                 on_created=None):
        self.extract_js, self.settle, self.deadline = extract_js, settle, deadline
        self._last_replay_count = 0
        self._replay_allowance = settings.max_interactions_per_page
        self.before_goto = before_goto  # (the crawl's polite speed: every page load counts)
        # forms filled while exploring: their values carry qa-<run>-f<n>; on_created(what, tag, where) writes down what
        # a SENT form created (staging), for the cleanup and the report
        self.tag_base, self.on_created, self._tags = tag_base, on_created, 0
        self._untouched = None  # the address whose page is still as a new visitor sees it (no reload needed)
        self.decided: dict[tuple, dict] = {}   # (name, selector) -> what was learned / why it was not tried
        self.states: set[str] = set()
        self.counts = Counter()
        self.blocked: list[dict] = []
        self.skipped: list[dict] = []

    # ---------------------------------------------------------------- which controls, which action
    def _targets(self, entry: dict) -> list[dict]:
        in_form = {x.get("selector") for f in entry.get("forms", []) for x in f.get("fields", [])}
        out, per_kind = [], Counter()
        for b in entry.get("buttons", []):
            if not b.get("selector"):
                continue
            kind = "repeated" if (b.get("count") or 1) > 1 else (b.get("kind") or "")
            out.append({"name": (b.get("accname") or b.get("text") or "control").split("\n")[0].strip()[:60],
                        "text": b.get("text") or "", "selector": b["selector"], "action": "click", "kind": kind,
                        "role": b.get("role") or "", "tag": b.get("tag") or "",
                        "disabled": b.get("disabled"), "submit": sends_form(b), "revealed_by": b.get("revealed_by"),
                        "chrome": bool(b.get("chrome")), "in_table": bool(b.get("in_table"))})
        for i in entry.get("inputs", []):
            s = i.get("selector")
            if not s or i.get("disabled") or i.get("readonly"):
                continue
            name = (i.get("label") or i.get("name") or i.get("placeholder") or "box").split("\n")[0].strip()[:60]
            if i.get("tag") == "select" and len(i.get("options") or []) >= 2:
                out.append({"name": name, "text": name, "selector": s, "action": "select", "kind": "select",
                            "value": i["options"][-1]["value"], "revealed_by": i.get("revealed_by"),
                            "chrome": bool(i.get("chrome")), "in_table": bool(i.get("in_table"))})
            elif (i.get("type") or "") == "checkbox" and s not in in_form:
                out.append({"name": name, "text": name, "selector": s, "action": "tick", "kind": "tick",
                            "revealed_by": i.get("revealed_by"),
                            "chrome": bool(i.get("chrome")), "in_table": bool(i.get("in_table"))})
        known_actions = {(t["selector"], t["action"]) for t in out}
        for item in entry.get("hovers", []):
            if item.get("selector") and (item["selector"], "hover") not in known_actions:
                out.append({"name": item.get("name") or item.get("text") or "Hover menu", "text": item.get("text") or "",
                            "selector": item["selector"], "action": "hover", "kind": "hover", "revealed_by": item.get("revealed_by")})
        for t in out:  # a few of each kind per page
            cap = KIND_CAP.get(t["kind"])
            per_kind[t["kind"]] += 1
            if cap and not settings.explore_repeated_controls and per_kind[t["kind"]] > cap:
                t["capped"] = f"one of many alike ({t['kind']}): the first {cap} are learned"
        return out

    def _eligible(self, t: dict) -> tuple[str, str]:
        """(risk, why not) - why not = '' when the action may be performed."""
        cls = action_class(t["text"] or t["name"], t["selector"],
                           role=t.get("role"), kind=t.get("kind"), tag=t.get("tag"))
        risk = action_risk(t["text"] or t["name"], t["selector"],
                           role=t.get("role"), kind=t.get("kind"), tag=t.get("tag"))
        if t.get("disabled"):
            return risk, "disabled on the page"
        if settings.discovery_only and risk == "test_account":
            return risk, "discovery only: no test-account changes"
        if risk == "protected":
            return risk, blocked_reason(cls)
        if risk == "write":  # (staging: allowed - but only the tests made for it do it, with tagged test data)
            return risk, "changes data: only the form / create-edit-delete tests do it (tagged test data, cleaned up)"
        if t.get("submit"):
            return risk, "sends a form - the form tests check it"
        if risk == "test_account" and settings.environment not in ("test", "staging"):
            return risk, f"test-account action: only on a test / staging environment (this run: {settings.environment})"
        return risk, ""

    # ---------------------------------------------------------------- one action from a fresh page
    def _fresh(self, page, url: str, lazy: bool) -> None:
        """The page as a new visitor sees it - not loaded again when it still is (the crawl just opened it, or the
        last action changed nothing): every reload of a slow website costs seconds."""
        if self._untouched == url and _same_page(page.url, url):
            self._untouched = None  # (once: the action about to happen may change it)
            return
        self._untouched = None
        if self.before_goto:
            self.before_goto()
        page.goto(url, wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
        self.settle(page)
        close_consent(page)
        if lazy:
            autoscroll(page)

    def _act(self, page, t: dict) -> None:
        loc = page.locator(t["selector"])
        if loc.count() != 1:
            raise ValueError("Automation target must resolve uniquely before discovery interaction")
        if t['action'] != 'tick':
            loc.scroll_into_view_if_needed(timeout=3000)
        if t["action"] == "hover":
            loc.hover(timeout=4000)
        elif t["action"] == "select":
            loc.select_option(t["value"], timeout=4000)
        elif t["action"] == "tick":
            from .form_targets import set_user_checked
            set_user_checked(loc, True)
        else:
            loc.click(timeout=4000)

    def _from_below(self, page, t: dict, item_sel) -> dict | None:
        """A floating control ('Back to top' fixed in a corner) does nothing at the top of the page - what it does
        (scrolling) can only be seen further down: tried once more from the bottom of the page."""
        page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
        page.wait_for_timeout(400)
        below = snapshot(page, item_sel)
        if (below.get("scroll") or 0) < SCROLLED:
            return None  # (the page is too short to move)
        self._act(page, t)
        page.wait_for_timeout(700)
        self.settle(page, 4000)
        ev = diff(below, snapshot(page, item_sel))
        return ev if ev["effect"] == "scroll" else None

    def _try(self, page, url: str, entry: dict, t: dict, opener: dict | None, risk: str, guard=None) -> dict:
        """guard(page, t) -> why not ('' = go on): checked on the fresh page, just before the action."""
        item_sel = (entry.get("itemLinks") or {}).get("selector")
        try:
            self._fresh(page, url, bool(entry.get("lazy")))
            if opener and not page.locator(t["selector"]).first.is_visible():
                chain, visited, current = [], set(), opener
                while current:
                    if current["selector"] in visited or len(chain) >= 8:
                        return {"error": "Nested opener chain exceeded its depth/cycle bound"}
                    visited.add(current["selector"])
                    chain.append(current)
                    current = self.decided.get(("__opener__", current.get("revealed_by")))
                for ancestor in reversed(chain):
                    if self._last_replay_count >= self._replay_allowance:
                        return {"error": "The interaction budget cannot replay this nested path"}
                    if time.time() > self.deadline or runctl.stopping():
                        return {"error": "Nested menu replay stopped before the action"}
                    _risk, why = self._eligible(ancestor)
                    why = why or self._seen_guard(page, ancestor)
                    if why:
                        return {"blocked": "Cannot replay opener: " + why}
                    self._act(page, ancestor)
                    self._last_replay_count += 1
                    self.counts["opener_replays"] += 1
                    page.wait_for_timeout(250)
            if not page.locator(t["selector"]).first.is_visible():
                return {"error": "not visible on the page (hidden until something else is done)"}
            why_not = guard(page, t) if guard else ""
            if why_not:
                return {"blocked": why_not}
            saved = page.evaluate(STORAGE_JS) if risk == "safe" else None
            # look from where the control is: what loads while scrolling to it is not its effect
            page.locator(t["selector"]).first.scroll_into_view_if_needed(timeout=3000)
            page.wait_for_timeout(300)
            before = snapshot(page, item_sel)
            try:
                pics = page.locator(t["selector"]).first.evaluate(REGION_JS)
            except Exception:
                pics = None
            self._act(page, t)
            page.wait_for_timeout(700)
            self.settle(page, 4000)
            after = snapshot(page, item_sel)
            if _same_page(page.url, url):
                capture_after_action(page, entry, t)
            try:
                pics_after = page.evaluate(PICTURES_JS) if pics is not None else None
            except Exception:
                pics_after = None  # (it opened another page)
            ev = diff(before, after, pics is not None and pics_after is not None and pics_after != pics)
            if ev["effect"] == "nothing" and (before.get("scroll") or 0) < SCROLLED \
                    and page.locator(t["selector"]).first.evaluate(FLOATING_JS):
                ev = self._from_below(page, t, item_sel) or ev
            if ev["new_controls"] and ev["effect"] in ("panel", "message", "value", "text"):
                ev["revealed"] = self._revealed(page, entry, t)
            if saved:  # a safe action must not leave settings behind (e.g. another language for the next pages)
                try:
                    page.evaluate(RESTORE_JS, saved)
                except Exception:
                    pass
            if ev["effect"] == "nothing" and not opener and _same_page(page.url, url) and len(page.context.pages) == 1:
                self._untouched = url  # (nothing changed: the next control is tried without loading the page again)
            return ev
        except Exception as e:
            return {"error": str(e).strip().split("\n")[0][:160]}
        finally:
            for extra in page.context.pages:  # a control that opened a new tab
                if extra is not page:
                    try:
                        extra.close()
                    except Exception:
                        pass

    def _revealed(self, page, entry: dict, opener: dict) -> list[dict]:
        """Controls that became visible after the action: added to the page, with the control that reveals them."""
        try:
            data = page.evaluate(self.extract_js)
        except Exception:
            return []
        known = {x.get("selector") for x in entry.get("buttons", []) + entry.get("inputs", []) + entry.get("hovers", [])}
        new = []
        for group in ("buttons", "inputs", "hovers"):
            for x in data.get(group, []):
                if x.get("selector") in known or not x.get("selector") or x.get("selector") == opener["selector"]:
                    continue
                x = dict(x, revealed_by=opener["selector"], revealed_by_name=opener["name"])
                entry.setdefault(group, []).append(x)
                new.append({"group": group, **x})
        for form in data.get("forms", []):
            if not form.get("fields") or not form.get("selector"):
                continue
            existing = next((f for f in entry.get("forms", []) if f.get("selector") == form["selector"]), None)
            if existing is None:
                entry.setdefault("forms", []).append(dict(form, index=len(entry.get("forms", [])),
                    revealed_by=opener["selector"], revealed_by_name=opener["name"]))
            else:
                known_fields = {f.get("selector") for f in existing.get("fields", [])}
                if not known_fields:
                    existing.update(revealed_by=opener["selector"], revealed_by_name=opener["name"])
                existing.setdefault("fields", []).extend(f for f in form["fields"] if f.get("selector") not in known_fields)
                if not existing.get("submit") and form.get("submit"):
                    existing["submit"] = form["submit"]
        return new[:12]

    # ---------------------------------------------------------------- the whole page
    def explore(self, page, url: str, entry: dict) -> tuple[list[str], list[str]]:
        """Learn what each eligible control of this page does. Returns (new same-site addresses that appeared,
        addresses whose link text an action changed - 'Cart (0)' -> 'Cart (1)': that page is worth reading again).
        What the actions made the website remember in the browser (localStorage / sessionStorage keys they ADDED) is
        forgotten afterwards: the next pages are read as a new visitor - and the tests - see them. (practicesoftware
        testing.com: 'Testing Guide' stored testing-split-screen-active, and its panel then lay over every later page;
        its products picked for comparison filled /comparison.) Keys that were there before (a login) stay."""
        try:
            before = page.evaluate(STORAGE_KEYS_JS)
        except Exception:
            before = None
        try:
            return self._explore(page, url, entry)
        finally:
            try:
                if before and page.evaluate("() => location.origin") == before["origin"]:
                    page.evaluate(FORGET_ADDED_JS, before)
            except Exception:
                pass

    def _seen_targets(self, entry: dict, targets: list[dict]) -> list[dict]:
        """What the AI saw in the page's screenshot (page["seen"], backend/vision.py) that no control of the page
        stands for - a person would use it, so it is tried too: found by its visible words."""
        known = [x for t in targets for x in (t["name"], t["text"])] + [
            x.get(k) or "" for x in entry.get("inputs", []) + entry.get("links", [])
            for k in ("label", "placeholder", "name", "text")]
        known = [k.lower().strip() for k in known if k and len(k.strip()) >= 2]
        out = []
        for f in (entry.get("seen") or {}).get("features", []):
            name = re.sub(r"\s+", " ", f.get("name") or "").strip()
            low = name.lower()
            if f.get("kind") in SEEN_SKIP or not 2 <= len(name) <= 60 or ">>" in name:
                continue
            if any(low == k or (len(low) >= 4 and low in k) or (len(k) >= 4 and k in low) for k in known):
                continue  # (the page's own control: learned the usual way)
            out.append({"name": name, "text": name, "selector": f"internal:text={json.dumps(name)}i >> visible=true",
                        "action": "click", "kind": "seen", "seen": True, "revealed_by": None})
        return out[:SEEN_MAX]

    def _seen_guard(self, page, t: dict) -> str:
        """A control only the AI's picture named: what it really is decides (a form's button, a trash icon, a
        'log out' link) - '' = it may be clicked."""
        info = page.locator(t["selector"]).first.evaluate(SEEN_CONTROL_JS, timeout=3000)
        if sends_form({"type": info["type"], "in_form": info["in_form"], "form_method": info["form_method"],
                       "text": info["text"]}):
            return "sends a form - the form tests check it"
        label = f"{info['text']} {info['icon']}".replace("-", " ").strip() or t["name"]
        cls = action_class(label, info["href"], role=info.get("role"), tag=info.get("tag"), href=info.get("href"))
        risk = action_risk(label, info["href"], role=info.get("role"), tag=info.get("tag"), href=info.get("href"))
        if risk in ("protected", "write"):
            return blocked_reason(cls if risk == "protected" else "write")
        return ""

    def _explore(self, page, url: str, entry: dict) -> tuple[list[str], list[str]]:
        host, budget, new_urls, changed = urlparse(url).hostname, settings.max_interactions_per_page, [], []
        seen_cap = SEEN_MAX_THOROUGH if settings.explore_repeated_controls else SEEN_MAX
        seen_left = seen_cap  # (what the AI saw has its own small budget: it never pushes the page's controls out)
        self._untouched = url if _same_page(page.url, url) else None  # (the crawl has just opened it)
        behaviour = entry.setdefault("behaviour", [])
        queue = self._targets(entry)
        queue += self._seen_targets(entry, queue)
        tried = entry.setdefault("seen_tried", [])
        while queue:
            # Discover routes and root controls before spending the budget on revealed widgets,
            # global chrome, or repeated table-row toggles (KIND_CAP / explore_repeated already bound samples).
            # Menu/chrome navigation first under budget so sections are reached before widgets burn the quota.
            # Repeated table-row toggles stay last; pay/checkout remain skipped via _eligible protected risk.
            queue.sort(key=lambda target: (
                0 if target.get("kind") in {"menu", "hover", "tab"} and not target.get("in_table") else
                1 if target.get("kind") in {"next", "filter", "select"} else
                3 if target.get("in_table") or target.get("kind") == "repeated" else
                2 if target.get("revealed_by") else
                4 if target.get("chrome") and target.get("kind") not in {"menu", "hover", "tab"} else 2
            ))
            t = queue.pop(0)
            key = (t["name"], t["selector"])
            if key in self.decided:
                continue  # (learned on an earlier page: header / footer / the same template)
            risk, why = self._eligible(t)
            why = why or t.get("capped", "")
            if why:
                self.decided[key] = {"why": why}
                bucket = "blocked" if why.startswith(("protected", "test-account")) else "skipped"
                self.counts[bucket] += 1
                getattr(self, bucket).append({"control": t["name"], "page": url, "why": why})
                continue
            left = seen_left if t.get("seen") else budget
            # Soft run reserve: stop starting heavy interactions so analysis/report can still finish.
            if left <= 0 or time.time() > self.deadline or runctl.should_stop_heavy_work():
                self.counts["not_tried_limit"] += 1
                self.skipped.append({"control": t["name"], "page": url, "why":
                                     f"limit: MAX_INTERACTIONS_PER_PAGE={settings.max_interactions_per_page}"
                                     if left <= 0 else "the run was stopped" if runctl.stopping()
                                     else "run time reserve (ANALYSIS_RESERVE_S / REPORT_RESERVE_S)"
                                     if runctl.should_stop_heavy_work() and time.time() <= self.deadline
                                     else "limit: CRAWL_TIME_LIMIT_MIN"})
                if t.get("seen"):
                    tried.append({"name": t["name"], "status": "not tried", "why": self.skipped[-1]["why"]})
                continue
            if t.get("seen"):
                seen_left -= 1
            else:
                budget -= 1
            self.counts["attempted"] += 1
            self._last_replay_count = 0
            self._replay_allowance = max(0, budget)
            opener = self.decided.get(("__opener__", t.get("revealed_by")))
            ev = self._try(page, url, entry, t, opener, risk, guard=self._seen_guard if t.get("seen") else None)
            budget -= self._last_replay_count
            self.decided[key] = ev
            if ev.get("blocked"):  # (what the control really is decided: never clicked)
                self.counts["blocked"] += 1
                self.blocked.append({"control": t["name"], "page": url, "why": ev["blocked"]})
                tried.append({"name": t["name"], "status": "blocked", "why": ev["blocked"]})
                continue
            if ev.get("error"):
                self.counts["failed"] += 1
                if t.get("seen"):  # (named by the AI's picture, but not found by its words: listed, no test)
                    tried.append({"name": t["name"], "status": "not found", "why": ev["error"]})
                    continue
                behaviour.append({"control": t["name"], "selector": t["selector"], "action": t["action"],
                                  "risk": risk, "effect": "error", "error": ev["error"],
                                  "revealed_by": t.get("revealed_by")})
                continue
            if t.get("seen"):
                tried.append({"name": t["name"], "status": "learned", "why": ev["effect"]})
            self.counts["no_effect" if ev["effect"] == "nothing" else "learned"] += 1
            for revealed in ev.pop("revealed", []):  # learn the revealed controls too (their opener first)
                self.decided[("__opener__", t["selector"])] = t
                if revealed["group"] == "inputs" and not (
                        (revealed.get("tag") == "select" and len(revealed.get("options") or []) >= 2)
                        or (revealed.get("type") or "") == "checkbox"):
                    continue  # a box to type in: clicking it shows nothing - the form tests fill it
                queue.insert(0, {"name": (revealed.get("accname") or revealed.get("label") or revealed.get("text")
                                          or "control").split("\n")[0].strip()[:60],
                                 "text": revealed.get("text") or "", "selector": revealed["selector"],
                                 "action": "hover" if revealed["group"] == "hovers" else "select" if revealed.get("tag") == "select" and revealed.get("options")
                                 else "tick" if (revealed.get("type") or "") == "checkbox" else "click",
                                 "value": (revealed.get("options") or [{}])[-1].get("value"),
                                 "kind": revealed.get("kind") or "", "revealed_by": t["selector"],
                                 "submit": (revealed.get("type") or "").lower() == "submit" and revealed.get("in_form")})
            # Full exploration must queue product links revealed by pagination and filters.
            # The explicit sampled mode retains its bounded list behavior.
            found = ([ev["to"]] if ev["effect"] == "navigates" else
                     ev["new_links"] if ev["effect"] != "list" or settings.explore_repeated_controls else [])
            for h in found:
                if h and urlparse(h).hostname == host and h not in new_urls:
                    new_urls.append(h)
            if risk == "test_account":
                changed += [h for h in ev["changed_links"] if urlparse(h).hostname == host and h not in changed]
            new_state = ev["state"] not in self.states
            self.states.add(ev["state"])
            behaviour.append({"control": t["name"], "selector": t["selector"], "action": t["action"], "risk": risk,
                              "value": t.get("value"), "kind": t.get("kind") or "", "effect": ev["effect"],
                              "message": ev["message"],
                              "tone": ev["tone"], "to": ev["to"], "values": ev["values"],
                              "list_changed": ev["list_changed"], "new_state": new_state,
                              "revealed": [c.split("|")[1] for c in ev["new_controls"] if c.split("|")[1]][:8],
                              "revealed_by": t.get("revealed_by"), "added": ev["added"][:4]})
        return new_urls, changed

    # ---------------------------------------------------------------- forms, filled like a person fills them
    def fill_forms(self, page, url: str, entry: dict) -> list[str]:
        """Every form of the page is filled like a person fills it: a valid value in each box, in order (names carry
        the run's tag), then each other choice of its radio buttons is tried. What appears, disappears or turns on /
        off while filling is recorded (entry["form_fills"]): a 'One way' that switches the return date off, a box that
        only appears after another one, a message under a box. Boxes that appear are added to the form, so its
        tests fill them too. The form is SENT only where writes are allowed (staging): then the page it leads to is
        returned (the next step of a multi-step form) and the record it created is written down for the cleanup.
        Never: a login form, a form that pays or deletes, a search / filter form (its own tests)."""
        if settings.discovery_only:
            return []
        from .actions import DELETE, action_class
        from .forms import SEARCHY, is_login_form, keep_form_field
        fills, new_urls = entry.setdefault("form_fills", []), []
        forms_considered = 0
        for f in entry.get("forms", []):
            said = ((f.get("submit") or {}).get("text") or "").strip()
            fields = [x for x in f.get("fields", []) if keep_form_field(x)]
            submit_sel = ((f.get("submit") or {}).get("selector") or "")
            submit_cls = action_class(said, submit_sel, role="button", kind="button", tag="button")
            if not fields or is_login_form(f) or submit_cls in ("pay", "delete") or DELETE.search(said) \
                    or READING_SUBMIT.match(said) \
                    or any((x.get("type") or "") == "search" or SEARCHY.search(f"{x.get('name')} {x.get('label')}")
                           for x in fields):
                continue
            key = ("__form__", tuple(sorted(x["selector"] for x in fields)), (f.get("submit") or {}).get("selector"))
            if key in self.decided:
                continue  # (the same form on another page - the footer's newsletter box: filled once)
            if time.time() > self.deadline or runctl.should_stop_heavy_work():
                break
            if forms_considered >= FILL_MAX_FORMS:
                fills.append({"form": f["selector"], "not_sent": "Form inspection limit reached; not filled"})
                continue
            forms_considered += 1
            send = False  # discovery has no outcome oracle; authorized writes belong to planned, run-owned tests
            try:
                rec = self._fill_one(page, url, entry, f, fields, send)
            except Exception as e:
                rec = {"form": f.get("selector"), "name": said or "the form", "error": str(e).split("\n")[0][:160]}
            self.decided[key] = rec
            if rec.get("filled"):
                self.counts["forms_filled"] += 1
            fills.append(rec)
            if rec.get("next_url") and urlparse(rec["next_url"]).hostname == urlparse(url).hostname:
                new_urls.append(rec["next_url"])
        return new_urls

    def _fill_box(self, page, x: dict, box: dict, tag: str, scope=None):
        """A valid value in one box, the way a person gives it - None when the box is left as it is (hidden, greyed
        out, already filled in: an existing record's form keeps its values, nothing is sent from it).

        Resolution is scoped to the form/dialog/section container and refuses ambiguous matches (no silent .first).
        """
        from .forms import (
            FormTargetProblem,
            keep_form_field,
            reresolve_field,
            select_option_user,
            set_choice,
            unique_field,
        )
        from .testdata import valid_value
        metadata = dict(box, **x)
        if not keep_form_field(dict(box, **x)):
            return None
        root = scope or page.locator("body")
        try:
            el = unique_field(page, root, dict(box, **x))
        except FormTargetProblem as e:
            if e.kind == "ambiguous":
                raise
            if x.get("required") or box.get("required"):
                raise ValueError(f"required field missing/invisible inside the form: {e}") from e
            return None
        if not el.is_enabled():
            return None
        t, tag_name = (box.get("type") or x.get("type") or "").lower(), box.get("tag") or ""
        fallbacks: list = []
        if t == "checkbox":
            if box.get("required") or x.get("required"):
                set_choice(el, checked=True, log=fallbacks)
                el = reresolve_field(page, root, dict(box, **x))
                if not el.is_checked():
                    raise ValueError("The checkbox did not retain the checked state")
                self._last_control_fallbacks = fallbacks
                return "ticked"
            return None
        if t == "radio":
            name = el.get_attribute("name") or ""
            if name and not root.locator(f'input[type=radio][name="{name}"]:checked').count():
                set_choice(el, checked=True, log=fallbacks)
                el = reresolve_field(page, root, dict(box, **x))
                if not el.is_checked():
                    raise ValueError("The radio did not retain the selected state")
                self._last_control_fallbacks = fallbacks
                return "chosen"
            return None
        if tag_name == "select" or t.startswith("select"):
            options = el.evaluate("e => [...e.options].filter(o => !o.disabled && o.value).map(o => o.value)")
            if options and not el.input_value():
                select_option_user(el, options[0], log=fallbacks)
                el = reresolve_field(page, root, dict(box, **x))
                if el.input_value() != options[0]:
                    raise ValueError("The select did not retain the chosen option")
                self._last_control_fallbacks = fallbacks
                return options[0]
            return None
        if t in ("file", "image", "range", "color", "hidden") or el.input_value():
            return None
        value = valid_value(dict(box, **x), tag) or (f"QA test {tag}" if t in ("", "text", "textarea") else "")
        if re.search(r"\bdate\b|\bbirth|\bdob\b", str(metadata.get("label") or ""), re.I) or t in ("date", "datetime-local", "time", "month"):
            from .agents.test_design import _value_for
            value = _value_for(metadata)
        if not value:
            if metadata.get("required"):
                raise ValueError("Required field has no grounded input value")
            return None
        el.fill(value, timeout=3000)
        el.evaluate("e => e.blur && e.blur()")
        el = reresolve_field(page, root, dict(box, **x))
        if el.input_value(timeout=3000) != value:
            raise ValueError("The input did not retain the intended test value")
        self._last_control_fallbacks = []
        return value

    def _fill_one(self, page, url: str, entry: dict, f: dict, fields: list[dict], send: bool) -> dict:
        self._tags += 1
        tag = f"qa-{self.tag_base}-f{self._tags}"
        known = {i.get("selector"): i for i in entry.get("inputs", []) if i.get("selector")}
        self._fresh(page, url, bool(entry.get("lazy")))
        from .forms import FormTargetProblem, form_scope, keep_form_field
        from .navigation import open_path, opener_path
        fields = [x for x in fields if keep_form_field(dict(known.get(x.get("selector"), {}), **x))]
        if not fields:
            return {"form": f.get("selector"), "name": ((f.get("submit") or {}).get("text") or "the form").strip()[:60],
                    "page": url, "tag": tag, "filled": [], "not_sent": "no in-form fill targets after chrome/table filter"}
        open_path(page, opener_path(entry, f["selector"], f.get("revealed_by")), fields[0]["selector"])
        try:
            form = form_scope(page, {"form": f["selector"]})
        except FormTargetProblem:
            raise
        start = snapshot(page)
        boxes0 = form.evaluate(BOX_STATE_JS)
        filled, control_fallbacks = [], []
        for x in fields:
            self._last_control_fallbacks = []
            v = self._fill_box(page, x, known.get(x["selector"], {}), tag, scope=form)
            if v is not None:
                row = {"box": (x.get("label") or x.get("placeholder") or x.get("name") or "box")[:60],
                       "value": "[redacted]" if (x.get("type") or "").lower() == "password" else v}
                if self._last_control_fallbacks:
                    # Fallback force/DOM paths are recorded and never prove normal user actionability.
                    row["control_fallback"] = self._last_control_fallbacks
                    control_fallbacks.extend(self._last_control_fallbacks)
                filled.append(row)
                page.wait_for_timeout(200)
        page.wait_for_timeout(500)
        # boxes that only appeared while filling: added to the page and the form (its tests fill them), then filled
        # (the whole page is read again only when a box did appear - on a big app that reading is slow)
        seen_sel, now = {x["selector"] for x in fields}, []
        if _box_changes(boxes0, form.evaluate(BOX_STATE_JS))["appeared"]:
            try:
                now = [i for i in page.evaluate(self.extract_js).get("inputs", [])
                       if i.get("selector") and i["selector"] not in seen_sel and i["selector"] not in known]
            except Exception:
                now = []
        for i in now[:8]:
            i = dict(i, revealed_by=f["selector"], revealed_by_name="filling the form")
            if not keep_form_field(i):
                continue
            entry.setdefault("inputs", []).append(i)
            f["fields"].append({k: i.get(k) for k in ("name", "id", "type", "selector", "required", "label",
                                                      "placeholder", "autocomplete", "accname", "role", "chrome",
                                                      "in_table")})
            v = self._fill_box(page, i, i, tag, scope=form)
            if v is not None:
                filled.append({"box": (i.get("label") or i.get("placeholder") or "box")[:60], "value": v})
        changes = _box_changes(boxes0, form.evaluate(BOX_STATE_JS))
        ev = diff(start, snapshot(page))
        rec = {"form": f["selector"], "name": ((f.get("submit") or {}).get("text") or "the form").strip()[:60],
               "page": url, "tag": tag, "filled": filled, **changes,
               "said": [a for a in ev["added"] if len(a) < 160][:6], "choices": self._other_choices(page, form),
               "sent": False}
        if control_fallbacks:
            rec["control_fallbacks"] = control_fallbacks
            rec["proves_user_actionability"] = False
        if not send:
            rec["not_sent"] = "Discovery input check only; forms are never sent here. Authorized submissions require a planned outcome check."
            return rec
        if not any(tag in str(x["value"]) for x in filled):  # (an existing record's form - its boxes were filled in
            rec["not_sent"] = "nothing of this run's own was typed in (an existing record's form): not sent"
            return rec  # already: sending it would only save that record again - its own tests check it)
        from .forms import _visible_matches
        btn_hits = _visible_matches(form.locator(f["submit"]["selector"]))
        if not btn_hits:
            btn_hits = _visible_matches(page.locator(f["submit"]["selector"]))
        if len(btn_hits) != 1:
            from .forms import form_target_problem
            raise form_target_problem(
                "ambiguous" if len(btn_hits) > 1 else "missing_required",
                f"form submit matched {len(btn_hits)} visible controls - not clicking",
            )
        btn = btn_hits[0]
        before = snapshot(page)
        btn.click(timeout=5000)
        page.wait_for_timeout(1200)
        self.settle(page, 6000)
        after = diff(before, snapshot(page))
        rec.update(sent=True, result={"effect": after["effect"], "message": after["message"], "tone": after["tone"],
                                      "to": after["to"]}, next_url=after["to"] or "")
        if self.on_created and after["tone"] != "error":
            self.on_created("form", tag, url)
        return rec

    def _other_choices(self, page, form) -> list[dict]:
        """Each other choice of the form's radio buttons (up to 2 per group): what it switches on / off / shows."""
        out = []
        try:
            groups = form.evaluate("f => { const g = {}; for (const r of f.querySelectorAll('input[type=radio]')) "
                                   "(g[r.name] = g[r.name] || []).push(r.id || r.value); return g; }")
        except Exception:
            return out
        for name, opts in list(groups.items())[:3]:
            first = form.locator(f'input[type=radio][name="{name}"]:checked')
            keep = first.first.get_attribute("value") if first.count() else None
            for value in [o for o in opts if o and '"' not in o][:3]:
                radio = form.locator(f'input[type=radio][name="{name}"][id="{value}"], '
                                     f'input[type=radio][name="{name}"][value="{value}"]')
                if not radio.count() or radio.first.is_checked():
                    continue
                before = form.evaluate(BOX_STATE_JS)
                try:
                    radio.first.check(timeout=3000)
                except Exception:
                    continue
                page.wait_for_timeout(300)
                changes = _box_changes(before, form.evaluate(BOX_STATE_JS))
                if any(changes.values()):
                    out.append({"choice": f"{name} = {value}", **changes})
                if len(out) >= 4:
                    break
            if keep:  # (back to the first choice, like the form was)
                try:
                    form.locator(f'input[type=radio][name="{name}"][value="{keep}"]').first.check(timeout=3000)
                except Exception:
                    pass
        return out

    def summary(self) -> dict:
        c = self.counts
        return {"attempted": c["attempted"], "learned": c["learned"], "no_effect": c["no_effect"],
                "failed": c["failed"], "blocked": c["blocked"], "skipped": c["skipped"],
                "forms_filled": c["forms_filled"], "opener_replays": c["opener_replays"],
                "not_tried_limit": c["not_tried_limit"], "limit_per_page": settings.max_interactions_per_page,
                "states": len(self.states), "blocked_list": self.blocked[:40], "skipped_list": self.skipped[:60]}
