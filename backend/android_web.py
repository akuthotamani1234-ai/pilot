"""DOM discovery for real Android Chrome sessions in the shared Appium pipeline.

Also the website-only parts of test mode: recognising a bot check (and waiting for it, asking a person, or stopping -
never solving, hiding from or tricking it), the website's own browser messages (JavaScript alerts), a fresh visit
(this website's cookies and storage removed) and scrolling a page to its end like a user."""
import hashlib
import json
import re
import time
from urllib.parse import urlsplit

from .android import RISKY_ACTION, SAFE_NAVIGATION, AndroidEnvironmentError
from .qa_contracts import never_in_test_mode, origin

DOM_SCRIPT = r"""
return (() => {
 const opts = (typeof arguments !== 'undefined' && arguments[0]) || {};
 // Ids and classes made of long numbers or random hex change between visits (a cart line, a session): never used.
 const unstable = /\d{3,}|^[0-9a-f]{8,}$|^(ember|react|ng|mui|radix|headlessui|rc|yui|ext-gen|uid|id)[-_]?\d/i;
 const stateClass = /^(active|open|opened|show|shown|in|collapse|collapsed|collapsing|selected|current|focus|focused|hover|disabled|hidden|visible|fade|is-.*|has-.*|js-.*|ng-.*|slick-.*|swiper-.*|owl-.*|aos-.*)$/i;
 const count = s => { try { return document.querySelectorAll(s).length; } catch (_) { return 0; } };
 const quote = v => '"' + String(v).replace(/["\\]/g, '\\$&') + '"';
 const cache = new Map();
 const stableId = n => n.id && !unstable.test(n.id) && count('#' + CSS.escape(n.id)) === 1;
 const path = e => {
   if (cache.has(e)) return cache.get(e);
   let found = '';
   if (stableId(e)) found = '#' + CSS.escape(e.id);
   const tag = e.localName;
   if (!found && opts.test_mode) {
     const name = e.getAttribute('name');
     if (name && !unstable.test(name) && count(tag + '[name=' + quote(name) + ']') === 1) found = tag + '[name=' + quote(name) + ']';
     const href = e.getAttribute('href');
     if (!found && tag === 'a' && href && href.length < 200 && !/^#?$/.test(href) && !/^javascript:/i.test(href)
         && !unstable.test(href) && count('a[href=' + quote(href) + ']') === 1) found = 'a[href=' + quote(href) + ']';
     const classes = [...e.classList].filter(c => !stateClass.test(c) && !unstable.test(c) && c.length < 60).slice(0, 3);
     if (!found && classes.length && count(tag + classes.map(c => '.' + CSS.escape(c)).join('')) === 1)
       found = tag + classes.map(c => '.' + CSS.escape(c)).join('');
   }
   if (!found) found = pos(e);
   cache.set(e, found);
   return found;
 };
 // The place on the page (tag:nth-of-type steps up to an element with a stable id): it stays the same when the content
 // there changes - the first product after sorting, the subtotal after a quantity update.
 const posCache = new Map();
 function pos(e) {
   if (posCache.has(e)) return posCache.get(e);
   const parts = [];
   let node = e;
   while (node && node.nodeType === 1) {
     if (stableId(node)) { parts.unshift('#' + CSS.escape(node.id)); break; }
     let part = node.localName;
     const siblings = node.parentElement ? [...node.parentElement.children].filter(s => s.localName === node.localName) : [];
     if (siblings.length > 1) part += ':nth-of-type(' + (siblings.indexOf(node) + 1) + ')';
     parts.unshift(part);
     node = node.parentElement;
   }
   const found = parts.join(' > ');
   posCache.set(e, found);
   return found;
 }
 const region = e => {
   if (e.closest('[role=dialog],[aria-modal=true],dialog[open],.modal.show,.modal.in,.modal[style*="display: block"]')) return 'dialog';
   if (e.closest('footer,[role=contentinfo],.footer,#footer')) return 'footer';
   if (e.closest('nav,[role=navigation],.navbar,.top-menu,.header-menu,.mobile-menu,#menu,.menu,.navigation')) return 'nav';
   if (e.closest('header,[role=banner],.header,#header')) return 'header';
   if (e.closest('aside,[role=complementary],.sidebar,.side-2')) return 'aside';
   return 'main';
 };
 const group = e => {
   const g = e.closest('form,[role=dialog],dialog,.modal');
   if (g) return path(g);
   if (!opts.test_mode) return '';
   // Boxes and their button outside a <form> (a newsletter box sent by script): the nearest block holding both.
   let n = e.parentElement;
   for (let i = 0; n && n !== document.body && i < 4; i++, n = n.parentElement) {
     if (n.querySelector('form')) break;
     if (n.querySelector('input:not([type=hidden]),textarea,select')
         && n.querySelector('button,input[type=submit],input[type=button],[role=button]')) return path(n);
   }
   return '';
 };
 const shown = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
 const base = 'a,button,input,textarea,select,summary,h1,h2,h3,[role],[id]';
 // Test mode also reads the menu toggles and click-to-open controls a phone layout uses.
 const extra = ',h4,[aria-expanded],[aria-controls],[data-toggle],[data-bs-toggle],[onclick],[class*=toggle],[class*=burger],[class*=hamburger]';
 // A menu word alone is not a toggle: Bootstrap's nav-link, nav-item, navbar-brand and navbar-nav are the menu's
 // LINKS and containers. Run android_20261110_113902_88059d (demoblaze): every navbar link was taken for a toggle,
 // so "Log in", "Sign up" and "Contact" were never opened as entries and their dialog forms were never filled.
 const toggleWords = /(^|[-_ ])(menu|nav|navbar|navigation|hamburger|burger|sidebar|drawer|sublist|submenu|dropdown)[-_ ]?(toggle|toggler|trigger|button|btn|icon|open|opener)($|[-_ ])|toggle/i;
 const dialogOpener = '[data-toggle=modal],[data-bs-toggle=modal],[aria-haspopup=dialog]';
 const togglerAttrs = '[aria-expanded],[aria-controls],[data-toggle],[data-bs-toggle]';
 // A collapsed list of links (a phone footer's sections, a sub-menu): the visible control just before it opens it.
 const sections = new Set();
 if (opts.test_mode) {
   for (const list of document.querySelectorAll('ul,ol')) {
     if (sections.size >= 60) break;
     if (shown(list) || !list.querySelector('a[href]')) continue;
     const before = list.previousElementSibling;
     if (before && shown(before) && !before.matches('a[href],input,select,textarea')) sections.add(before);
   }
 }
 let all = [...document.querySelectorAll(base + (opts.test_mode ? extra : ''))];
 if (sections.size) {
   all = [...new Set([...all, ...sections])];
   all.sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1);
 }
 const elements = all.filter(shown).slice(0, 1500).map(e => {
   const buttonInput = opts.test_mode && e.matches('input[type=submit],input[type=button],input[type=image],input[type=reset]');
   const input = e.matches('input,textarea,select,[contenteditable=true]') && !buttonInput;
   const rendered = (e.innerText || e.textContent || '').trim();
   const r = e.getBoundingClientRect();
   const focus_only = /^skip\b/i.test(rendered) && (r.bottom <= 0 || r.right <= 0 || r.left >= innerWidth);
   const labelled = input && e.labels && e.labels.length ? (e.labels[0].innerText || '').trim().slice(0, 100) : '';
   const label = e.getAttribute('aria-label') || e.getAttribute('placeholder') || (opts.test_mode ? (labelled || e.getAttribute('title') || (buttonInput ? e.value : '')) : '') || '';
   const node = {selector: path(e), tag: e.localName, role: e.getAttribute('role') || '',
     text: input ? '' : (e.innerText || e.textContent || '').trim().slice(0, 160),
     text_comparable: !input && e.children.length === 0 && rendered.length <= 160,
     focus_only, label, dom_id: e.id || '', input, enabled: !e.disabled, href: e.localName === 'a' ? e.href : '',
     expands: e.hasAttribute('aria-expanded') || e.hasAttribute('aria-controls') || e.getAttribute('aria-haspopup') === 'true',
     submission: !!e.form && e.matches('button,input') && e.type === 'submit', download: e.hasAttribute('download'),
     clickable: e.matches('a[href],button,summary,[role=button],[role=tab],[role=menuitem]') || buttonInput,
     options: e.localName === 'select' ? [...e.options].map(o => ({text: o.text, label: o.label, disabled: o.disabled,
       ...(opts.test_mode ? {value: o.value, selected: o.selected} : {})})) : []};
   if (opts.test_mode) {
     const attrs = (e.className && typeof e.className === 'string' ? e.className : '') + ' ' + (e.id || '');
     const hrefAttr = e.getAttribute('href') || '';
     // What opens a dialog ("Log in", "Sign up") or another page ("Cart") is a menu ENTRY: tapping it is the test.
     const opensDialog = e.matches(dialogOpener);
     const pageLink = e.localName === 'a' && hrefAttr && !/^#?$/.test(hrefAttr) && !/^javascript:/i.test(hrefAttr) && !e.matches(togglerAttrs);
     const toggle = !input && !opensDialog && !pageLink && (e.matches('[data-toggle=collapse],[data-bs-toggle=collapse],[data-toggle=dropdown],[data-bs-toggle=dropdown],[class*=burger],[class*=hamburger]')
       || (toggleWords.test(attrs) && !e.matches('input,select,textarea'))
       || /^(menu|open menu|main menu|navigation|toggle navigation|categories|☰|≡)$/i.test((e.getAttribute('aria-label') || rendered).trim())
       || sections.has(e));
     // An icon button without words (a cart line's remove "x"): its class names say what it does.
     const ownClass = typeof e.className === 'string' ? e.className : '';
     const parentClass = e.parentElement && typeof e.parentElement.className === 'string' ? e.parentElement.className : '';
     const icon = !rendered && !label ? (ownClass + ' ' + parentClass).split(/\s+/).filter(c => c && !stateClass.test(c)
       && !unstable.test(c)).join(' ').replace(/[-_]+/g, ' ').slice(0, 80) : '';
     Object.assign(node, {
       pos: pos(e), icon,
       clickable: node.clickable || toggle || e.hasAttribute('onclick') || e.matches('[data-toggle],[data-bs-toggle]'),
       toggle, opens_dialog: opensDialog,
       expanded: e.getAttribute('aria-expanded') || '', name: e.getAttribute('name') || '',
       input_type: (e.getAttribute('type') || (e.localName === 'textarea' ? 'textarea' : e.localName === 'select' ? 'select' : '')).toLowerCase(),
       checked: !!e.checked, required: !!e.required, autocomplete: e.getAttribute('autocomplete') || '',
       href_raw: (e.getAttribute('href') || '').slice(0, 300), region: region(e), group: group(e),
       page_y: Math.round(r.top + scrollY), height: Math.round(r.height)});
   }
   return node;
 });
 const out = {url: location.href, title: document.title, ready: document.readyState, elements,
   busy: (window.jQuery && window.jQuery.active) || 0,
   total: document.querySelectorAll(base).length,
   viewport: {height: innerHeight, width: innerWidth, scroll_y: Math.round(scrollY),
              page_height: document.documentElement.scrollHeight}};
 // Signs of a bot check or CAPTCHA: only read to recognise one and hand it to a person - never to solve it.
 const frames = [...document.querySelectorAll('iframe')].map(f => f.src || '').filter(s => /challenges\.cloudflare\.com|recaptcha|hcaptcha|turnstile|captcha/i.test(s));
 const markers = ['#challenge-form', '#challenge-running', '#challenge-stage', '#cf-challenge-running', '#cf-wrapper',
   '.cf-browser-verification', '.cf-turnstile', '.g-recaptcha', '.h-captcha', '#px-captcha', '[data-sitekey]'];
 const captchaGroups = [...document.querySelectorAll('.g-recaptcha,.h-captcha,.cf-turnstile,[data-sitekey],iframe[src*=recaptcha],iframe[src*=hcaptcha],iframe[src*=turnstile]')]
   .map(group).filter(Boolean);
 out.challenge = {frames: frames.map(s => { try { const u = new URL(s); return u.hostname; } catch (_) { return ''; } }).slice(0, 10),
   markers: markers.filter(s => count(s)), groups: [...new Set(captchaGroups)].slice(0, 20),
   text: (document.body ? document.body.innerText : '').slice(0, 600)};
 if (opts.texts) {
   // Short visible texts (messages, counters, cart lines): what a user reads after an action. Never input values.
   const texts = [];
   for (const e of document.querySelectorAll('p,span,li,td,th,dd,dt,label,strong,b,em,small,div,h4,h5,h6,a,button')) {
     if (texts.length >= 600) break;
     if (!shown(e) || e.closest('script,style,noscript,select,option,[contenteditable]') || e.querySelector('input,textarea,select')) continue;
     const own = [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
     const text = (e.innerText || '').trim();
     if (!own || !text || text.length > 160) continue;
     const r = e.getBoundingClientRect();
     texts.push({selector: path(e), pos: pos(e), text, region: region(e), page_y: Math.round(r.top + scrollY),
                 message: !!e.closest('[role=alert],[role=status],[class*=notification],[class*=alert],[class*=message],[class*=toast],[class*=validation],[class*=error],[class*=success]')});
   }
   out.texts = texts;
 }
 return out;
})();
"""

CLEAR_STORAGE = """
try { localStorage.clear(); } catch (e) {}
try { sessionStorage.clear(); } catch (e) {}
try { if (indexedDB.databases) indexedDB.databases().then(list => list.forEach(d => d.name && indexedDB.deleteDatabase(d.name))); } catch (e) {}
try { if (window.caches) caches.keys().then(keys => keys.forEach(k => caches.delete(k))); } catch (e) {}
return true;
"""
SCROLL_STEP = ("window.scrollBy(0, Math.max(200, Math.floor(innerHeight * 0.8)));"
               "return [Math.round(scrollY), innerHeight, document.documentElement.scrollHeight];")
# The pass a bot check gives a browser AFTER it was passed. A visitor's browser keeps it; deleting it would only show
# the same check again before every test. It is the website's own cookie - nothing is forged, hidden or changed.
BOT_PASS_COOKIES = re.compile(r"^(cf_clearance|__cf_bm|_cfuvid|__cflb)$")

BOT_TITLE = re.compile(r"^\s*(just a moment|attention required|checking your browser|one more step|ddos-guard|"
                       r"security check|human verification|bot verification|verify(?:ing)? (?:you are|you're) "
                       r"(?:a )?human|are you a robot)", re.I)
BOT_TEXT = re.compile(r"performing security verification|checking (?:if the site connection is secure|your browser)|"
                      r"verify(?:ing)? (?:that )?(?:you are|you're) (?:a )?human|enable javascript and cookies to "
                      r"continue|needs to review the security of your connection|press (?:&|and) hold|"
                      r"uses a security service to protect against malicious bots|please complete the security check|"
                      r"ddos protection by|are you a robot", re.I)


class BotCheckBlocked(AndroidEnvironmentError):
    """The bot check did not finish by itself and nobody completed it: the run stops testing this website."""


# ------------------------------------------------------------------ browser messages (JavaScript alerts)

def _note_alert(driver, text) -> None:
    try:
        alerts = driver.__dict__.setdefault("_blowai_alerts", [])
    except (AttributeError, TypeError):
        return
    alerts.append(str(text or "")[:300])


def _close_open_alert(driver):
    """Read the open message and close it like a user: OK, or Cancel when it would confirm checkout / payment /
    deleting an account ("Are you sure you want to place this order?"). None when no message is open."""
    from selenium.common.exceptions import NoAlertPresentException, WebDriverException

    try:
        alert = driver.switch_to.alert
        text = alert.text or ""
    except (NoAlertPresentException, WebDriverException, AttributeError):
        return None
    try:
        if never_in_test_mode(text):
            alert.dismiss()
        else:
            alert.accept()
    except WebDriverException:
        pass
    return text


def alert_safe(driver, call, tries: int = 4):
    """Run one WebDriver call; a message the website showed meanwhile is remembered and closed, then the call is
    tried again. Chrome's default answer to a message nobody expected is 'dismiss and notify'."""
    from selenium.common.exceptions import UnexpectedAlertPresentException

    for attempt in range(tries):
        try:
            return call()
        except UnexpectedAlertPresentException as error:
            opened = _close_open_alert(driver)
            _note_alert(driver, getattr(error, "alert_text", None) or opened or "")
            if attempt == tries - 1:
                raise
    return None


def take_alert(driver, wait_s: float = 0.0):
    """The oldest browser message since the last check (already closed by Chrome, or open now and closed with OK);
    None when no message came within `wait_s` seconds."""
    deadline = time.monotonic() + wait_s
    while True:
        alerts = getattr(driver, "__dict__", {}).get("_blowai_alerts") or []
        if alerts:
            return alerts.pop(0)
        text = _close_open_alert(driver)
        if text is not None:
            return text
        if time.monotonic() >= deadline:
            return None
        time.sleep(.25)


def drain_alerts(driver) -> list[str]:
    """Every message seen since the last call (they belong to the action that was just done)."""
    alerts = getattr(driver, "__dict__", {}).get("_blowai_alerts") or []
    taken = list(alerts)
    alerts.clear()
    return taken


def collect_alerts(driver, wait_s: float = 0.0) -> list[str]:
    """Every browser message the last action caused: those already seen, and one that opens within `wait_s` seconds
    (a shop's "Product added." comes after its request returns)."""
    taken = drain_alerts(driver)
    if not taken:
        first = take_alert(driver, wait_s)
        taken = [first] if first is not None else []
    return taken + drain_alerts(driver)


def current_url(driver) -> str:
    return alert_safe(driver, lambda: driver.current_url)


# ------------------------------------------------------------------ bot checks

def bot_check(data: dict) -> str:
    """A plain name for the bot check / CAPTCHA page this is ('' for a normal page). A CAPTCHA box inside one of
    the website's own forms is not a bot-check PAGE: that form is reported as protected by a CAPTCHA instead."""
    challenge = data.get("challenge") or {}
    text = challenge.get("text") or ""
    title = data.get("title") or ""
    interactive = sum(1 for e in data.get("elements", []) if e.get("clickable") or e.get("input"))
    signals = bool(challenge.get("frames")) or bool(set(challenge.get("markers", [])) - {"[data-sitekey]",
                                                                                            ".g-recaptcha", ".h-captcha"})
    page = (BOT_TITLE.search(title) and interactive <= 40) or (BOT_TEXT.search(text) and interactive <= 25) \
        or (signals and interactive <= 12 and (BOT_TEXT.search(text) or BOT_TITLE.search(title)
                                               or "cloudflare" in text.casefold()))
    if not page:
        return ""
    words = " ".join([title, text, *challenge.get("frames", []), *challenge.get("markers", [])]).casefold()
    phrase = next((m.group(0) for m in (BOT_TEXT.search(text), BOT_TITLE.search(title)) if m), "a bot check")
    vendor = ("Cloudflare" if "cloudflare" in words or "cf-" in words or "ray id" in words else
              "hCaptcha" if "hcaptcha" in words else "reCAPTCHA" if "recaptcha" in words else
              "Turnstile" if "turnstile" in words else "")
    return (vendor + ": " if vendor else "") + phrase.strip()[:80]


class BotCheckGate:
    """What a normal visitor does at a bot check: wait for it to finish. If it does not, a person may complete it on
    the device (the existing ::human:: help, as for a login CAPTCHA); otherwise testing this website stops with a
    plain message. Never solves, hides from or tricks the check, and never tests the check page itself."""

    def __init__(self, config: dict, stop_path=None, ask_person: bool = True):
        self.wait_s = int(config.get("bot_check_wait_s", 30))
        self.human_s = int(config.get("human_wait_s", 180)) if ask_person else 0
        self.stop_path = stop_path
        self.blocked = ""
        self.events: list[dict] = []
        self.on_ask = None  # called when a person is asked (the offline tests stand in for that person)

    def __call__(self, driver, kind: str, read):
        if self.blocked:
            raise BotCheckBlocked(self.blocked)
        started = time.monotonic()
        print(f"[android] The website shows a bot check ({kind}) instead of its page. Waiting up to {self.wait_s} s "
              "for it to finish by itself, as it does for a normal visitor.", flush=True)
        data = self._wait(read, self.wait_s)
        if data is not None:
            self.events.append({"kind": kind, "outcome": "finished by itself",
                                "waited_s": round(time.monotonic() - started)})
            print("[android] The bot check finished by itself; the real website is shown.", flush=True)
            return data
        if self.human_s:
            print("::human::" + json.dumps({"what": "bot_check", "kind": kind, "wait_s": self.human_s}), flush=True)
            print(f"[android] Please complete the security check yourself on the Android device (the emulator "
                  f"window). Qpilot never solves or bypasses these checks. Waiting up to {self.human_s} s.", flush=True)
            if self.on_ask:
                self.on_ask()
            data = self._wait(read, self.human_s)
            print("::human::" + json.dumps({"what": "bot_check", "done": True, "ok": data is not None}), flush=True)
            if data is not None:
                self.events.append({"kind": kind, "outcome": "completed by a person",
                                    "waited_s": round(time.monotonic() - started)})
                print("[android] Thank you - the security check was completed; testing continues.", flush=True)
                return data
        waited = round(time.monotonic() - started)
        self.blocked = (f"The website blocks automated visitors: it showed a bot check ({kind}) instead of its pages. "
                        f"It did not finish by itself within {self.wait_s} s"
                        + (f" and nobody completed it on the device within {self.human_s} s" if self.human_s else "")
                        + ". Nothing behind it was tested, and no test was made from the check page. To test this "
                        "website: start again and complete the check on the emulator when Qpilot asks, ask the site "
                        "owner to allow the test device, or use a copy of the site without bot protection.")
        self.events.append({"kind": kind, "outcome": "blocked", "waited_s": waited})
        print("[android] " + self.blocked, flush=True)
        raise BotCheckBlocked(self.blocked)

    def _wait(self, read, seconds: float):
        deadline = time.monotonic() + seconds
        while True:
            if self.stop_path is not None and self.stop_path.exists():
                raise BotCheckBlocked("Stop requested while the website's bot check was shown.")
            data = read()
            if not bot_check(data):
                return data
            if time.monotonic() >= deadline:
                return None
            time.sleep(min(2.0, max(0.2, deadline - time.monotonic())))


# ------------------------------------------------------------------ reading a page

def guard_url(url, config):
    """Check origin before reading page content or following an extracted link."""
    from .safety import check_target
    check_target(url, resolve=False)
    allowed = {origin(config['start_url']),
               *[origin(u) for u in config.get('qa_contract', {}).get('allowed_origins', [])]}
    if origin(url) not in allowed:
        raise AndroidEnvironmentError("Android Chrome left the approved website origins; content was not inspected.")


def web_test_mode(config) -> bool:
    from .android import interaction_blocker
    return config.get("app_mode") == "web" and not interaction_blocker(config)


def _read(driver, config):
    """The page's inventory, after an origin check. A page still being replaced (a link was just tapped) is read again
    for a few seconds instead of failing the check."""
    from selenium.common.exceptions import WebDriverException

    guard_url(current_url(driver), config)
    args = [{"test_mode": True, "texts": True}] if web_test_mode(config) else []
    deadline = time.monotonic() + 10
    while True:
        try:
            data = alert_safe(driver, lambda: driver.execute_script(DOM_SCRIPT, *args))
            if not isinstance(data, dict) or "elements" not in data:
                raise WebDriverException("The page did not answer the inventory script")
            break
        except WebDriverException:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.3)
            guard_url(current_url(driver), config)
    guard_url(data['url'], config)
    return data


def inspect_web(driver, config):
    data = _read(driver, config)
    kind = bot_check(data)
    if kind:
        gate = getattr(driver, "__dict__", {}).get("_blowai_bot_gate")
        if gate is None:
            # Without a person to ask (the test-execution worker): wait like a visitor, then report the check.
            gate = BotCheckGate(config, ask_person=False)
            try:
                driver._blowai_bot_gate = gate
            except AttributeError:
                pass
        data = gate(driver, kind, lambda: _read(driver, config))
    in_test_mode = web_test_mode(config)
    elements = []
    for node in data['elements']:
        label = ' '.join([node['text'], node['label'], node['dom_id'], urlsplit(node['href']).path])
        safe = False
        if (node['clickable'] and not node['input'] and not node['submission'] and not node['download'] and not node['focus_only']
                and not RISKY_ACTION.search(label)):
            if node['href']:
                try:
                    guard_url(node['href'], config)
                    # Downloads and executable/non-web links are never crawler actions.
                    safe = urlsplit(node['href']).scheme in ('http', 'https')
                except ValueError:
                    pass
                except AndroidEnvironmentError:
                    pass
            else:
                safe = bool(SAFE_NAVIGATION.search(label) or node['tag'] == 'summary'
                            or node['role'] in ('tab', 'menuitem') or node['expands'])
        element = {
            'class_name': node['tag'], 'type': 'input' if node['input'] else 'button' if node['clickable'] else 'text',
            'text': node['text'], 'accessibility_id': node['label'], 'resource_id': node['dom_id'],
            'visible': not node['focus_only'], 'enabled': node['enabled'], 'clickable': node['clickable'],
            'focus_only': node['focus_only'],
            'input_capable': node['input'], 'locators': [{'strategy': 'css', 'value': node['selector']}],
            'locator_unique': True, 'safe_web_navigation': safe, 'options': node['options'], 'href': node['href'],
            'text_comparable': node['text_comparable'],
        }
        if in_test_mode:
            element.update({key: node.get(key) for key in (
                'toggle', 'opens_dialog', 'expanded', 'name', 'input_type', 'checked', 'required', 'autocomplete',
                'href_raw', 'region', 'group', 'page_y', 'height', 'pos')})
            element['password'] = node.get('input_type') == 'password'
            # A box's label, or the class words of an icon button without words (so "remove btn" can be found)
            element['hint'] = node['label'] if node['input'] else node.get('icon') or ''
        elements.append(element)
    # The fingerprint leaves out positions: lazy images moving a page by a few pixels are not a new screen.
    fingerprint = hashlib.sha256(json.dumps([data['url'], [{k: v for k, v in e.items() if k not in ('page_y', 'height')}
                                                           for e in elements]], sort_keys=True).encode()).hexdigest()[:20]
    # Site-wide titles (e.g. "The Internet") must not collapse different routes
    # into the same human-readable screen name. Omit query/fragment values.
    route = urlsplit(data['url']).path or '/'
    title = data['title'].strip()
    screen_name = f"{title} — {route}" if title else route
    screen = {'platform': 'android', 'package_name': 'com.android.chrome', 'device_id': config['device_id'],
              'activity': data['url'], 'web_url': data['url'], 'screen_name': screen_name,
              'fingerprint': fingerprint, 'elements': elements,
              'inventory_truncated': data['total'] > 1500,
              'android_version': (getattr(driver, 'capabilities', None) or {}).get('platformVersion')}
    if in_test_mode:
        screen.update(title=title, texts=data.get('texts', []), viewport=data.get('viewport', {}),
                      # A page still loading, or still waiting for its own requests (jQuery), is not read as settled
                      loading=data.get('ready') == 'loading' or bool(data.get('busy')),
                      captcha_groups=(data.get('challenge') or {}).get('groups', []))
    return screen


# ------------------------------------------------------------------ test mode: a fresh visit, scrolling

def reset_site_data(driver, config) -> None:
    """A first-time visit: this website's cookies (except the pass its own bot check issued) and its local / session
    storage are removed, then the start page is loaded. Other websites' data in Chrome is never touched."""
    start = config["start_url"]
    guard_url(start, config)
    try:
        guard_url(current_url(driver), config)
    except (AndroidEnvironmentError, ValueError):
        alert_safe(driver, lambda: driver.get(start))  # read and clear only while this website is open
    drain_alerts(driver)
    for cookie in alert_safe(driver, driver.get_cookies) or []:
        name = cookie.get("name") or ""
        if name and not BOT_PASS_COOKIES.match(name):
            try:
                driver.delete_cookie(name)
            except Exception:
                pass
    try:
        alert_safe(driver, lambda: driver.execute_script(CLEAR_STORAGE))
    except Exception:
        pass
    alert_safe(driver, lambda: driver.get(start))
    drain_alerts(driver)


def scroll_to_end(driver, limit: int = 25) -> int:
    """Scroll down like a user until the page ends (content that loads while scrolling appears), then back to the
    top. Returns the number of scroll steps."""
    steps, last = 0, None
    for _ in range(limit):
        position, height, total = alert_safe(driver, lambda: driver.execute_script(SCROLL_STEP))
        steps += 1
        if position == last or position + height >= total - 2:
            break
        last = position
        time.sleep(.3)
    alert_safe(driver, lambda: driver.execute_script("window.scrollTo(0, 0); return true;"))
    return steps


def how_to_reach(element: dict, viewport: dict) -> str:
    """Plain words for where a control is: on the first screen, or how far down."""
    height = int((viewport or {}).get("height") or 0)
    top = element.get("page_y")
    if not height or top is None or top < height:
        return "on the first screen"
    screens = max(1, round(top / height))
    return f"scroll down about {screens} screen{'s' if screens > 1 else ''}"
