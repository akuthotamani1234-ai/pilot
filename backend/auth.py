"""Login: find the login form, sign in with the test account, and PROVE that it worked.

A click on "Log in" proves nothing. Success needs evidence: the password box is gone AND (the address moved away
from the login page, or a log-out control appeared, or the configured success text / address is shown), and the
login still holds after the page is opened again.

Outcomes (login.json "outcome"):
  success               logged in, with the evidence
  invalid_credentials   the website says the user name or password is wrong
  locked                the account is locked / disabled
  mfa_required          the website asks for a one-time code (2-step verification) - never bypassed. With the test
                        account's authenticator key (TEST_TOTP_SECRET: the setup key of an authenticator app) the code
                        is made like the app makes it (TOTP, RFC 6238) and typed in; codes sent by e-mail / SMS
                        still need a person (a visible browser)
  captcha               a CAPTCHA is shown - never bypassed
  access_denied         HTTP 401 / 403 or "access denied" after signing in
  sso_redirect          the login moves to another website (single sign-on) outside the approved scope
  unsupported           a login is needed but no usable user name / password boxes were found
  failed                the form was sent, but there is no evidence of being logged in
  no_account            a login form, but no test account was given (and creating one was not allowed)
The password is never printed, logged, saved in login.json or put in a screenshot.
"""
import re
import time

from .config import settings

CAPTCHA = re.compile(r"g-recaptcha|recaptcha/api|hcaptcha|cf-turnstile|captcha", re.I)
MFA_HINT = re.compile(r"one[- ]?time|otp\b|verification code|security code|2fa|two[- ]?factor|2-step|authenticator|"
                      r"passcode|enter the code|sms code", re.I)
INVALID = re.compile(r"invalid|incorrect|wrong|not match|doesn'?t match|does not exist|unknown (user|email)|"
                     r"not recogni[sz]ed|try again|failed|unable to (log|sign)", re.I)
LOCKED = re.compile(r"\b(locked|disabled|suspended|deactivated|blocked)\b", re.I)
DENIED = re.compile(r"access denied|not authori[sz]ed|forbidden|permission denied|no permission", re.I)
LOGOUT = re.compile(r"\b(log ?out|sign ?out|log off)\b", re.I)
USER_HINT = re.compile(r"user|e-?mail|login|account|phone|mobile|id\b", re.I)
NEXT_TEXT = re.compile(r"^\s*(next|continue|proceed)\b", re.I)
LOGIN_TEXT = re.compile(r"\b(log ?in|sign ?in|submit|continue|enter)\b", re.I)

NOTES = {
    "success": "Logged in with the test account - the pages behind the login are tested too.",
    "invalid_credentials": "The website rejected the test account (wrong user name or password) - only the public "
                           "pages were tested. Check the account and try again.",
    "locked": "The website says the test account is locked or disabled - only the public pages were tested.",
    "mfa_required": "The website asks for a one-time code (2-step verification). The tester never bypasses this - "
                    "run with 'Watch the tests in a Chrome window' and type the code yourself when asked, use a test "
                    "account without 2-step verification, or a test environment where it is switched off.",
    "captcha": "The login shows a CAPTCHA (made to stop robots). The tester never bypasses it - run with 'Watch the "
               "tests in a Chrome window' and solve it yourself when asked, switch the CAPTCHA off in the test "
               "environment, or allow-list the tester.",
    "access_denied": "Signing in worked, but the website answered 'access denied' (401 / 403) - the test account "
                     "may not have the right role.",
    "sso_redirect": "The login moves to another website (single sign-on). It is outside the approved scope - add "
                    "that host to ALLOWED_HOSTS in .env if it belongs to your app.",
    "unsupported": "A login is needed, but no usable user name / password boxes were found. Set LOGIN_URL and the "
                   "LOGIN_*_SELECTOR settings in .env.",
    "failed": "The login form was sent, but there is no evidence of being logged in (the login form is still "
              "shown). Check the account, or set LOGIN_SUCCESS_TEXT in .env.",
    "no_account": "This website has a login, but no test account was given - only the public pages (login, "
                  "register...) were tested. Give a test account to test everything behind the login.",
}

# a visible box that asks for a one-time code
MFA_JS = r"""() => [...document.querySelectorAll('input')].some(i => {
  const r = i.getBoundingClientRect(); if (!(r.width && r.height)) return false;
  const lbl = (i.labels && i.labels[0] ? i.labels[0].innerText : '') + ' ' + (i.getAttribute('aria-label') || '');
  return i.autocomplete === 'one-time-code' ||
    /one[- ]?time|otp|verification|security code|2fa|two[- ]?factor|authenticator|passcode/i.test(
      `${i.name} ${i.id} ${i.placeholder} ${lbl}`);
})"""
TEXT_JS = "() => (document.body ? document.body.innerText : '').split('\\n').map(s => s.trim()).filter(Boolean)"
LOGOUT_JS = r"""() => [...document.querySelectorAll('a, button, [role=button], [role=menuitem]')].some(e =>
  /\b(log ?out|sign ?out|log off)\b/i.test((e.innerText || e.getAttribute('aria-label') || '') + ' ' + (e.getAttribute('href') || '')))"""


def login_form(p: dict) -> dict | None:
    """The page's login form -> {"user", "password", "submit"} selectors, or None.
    Settings in .env (LOGIN_*_SELECTOR) win. Two password boxes = a sign-up / change-password form, not a login.
    A login without a <form> (common in single-page apps) is found from the page's boxes and buttons."""
    has_password = any(i.get("type") == "password" for i in p.get("inputs", [])) or any(
        x.get("type") == "password" for f in p.get("forms", []) for x in f.get("fields", []))
    if settings.login_user_selector and settings.login_password_selector and has_password:
        return {"user": settings.login_user_selector, "password": settings.login_password_selector,
                "submit": settings.login_submit_selector or ""}
    for f in p.get("forms", []):
        fields = f.get("fields", [])
        pws = [x for x in fields if x.get("type") == "password" and x.get("selector")]
        sub = (f.get("submit") or {}).get("selector")
        if len(pws) != 1 or not sub:
            continue
        user = _user_box(fields)
        if user:
            return {"user": user["selector"], "password": pws[0]["selector"], "submit": sub}
    # no <form>: exactly one password box on the page + a user box + a "log in" button
    inputs = p.get("inputs", [])
    pws = [i for i in inputs if i.get("type") == "password" and i.get("selector")]
    user = _user_box(inputs)
    button = next((b for b in p.get("buttons", []) if b.get("selector") and not b.get("disabled")
                   and LOGIN_TEXT.search(b.get("text") or "")), None)
    if len(pws) == 1 and user and button:
        return {"user": user["selector"], "password": pws[0]["selector"], "submit": button["selector"]}
    # step 1 of a two-step login (email -> Continue -> password, e.g. big shops): a sign-in page with ONE user box,
    # no password box yet, and a Continue / Next / Sign in button
    from .agents.discovery import _auth_link
    on_signin = _auth_link(p.get("final_url") or p.get("url") or "") or any(
        re.search(r"\b(sign ?in|log ?in)\b", h, re.I) for h in p.get("headings") or [])
    boxes = [i for i in inputs if (i.get("type") or "text") in ("text", "email", "tel", "") and i.get("selector")]
    step = next((b for b in p.get("buttons", []) if b.get("selector") and not b.get("disabled")
                 and (NEXT_TEXT.search(b.get("text") or "") or LOGIN_TEXT.search(b.get("text") or ""))), None)
    if on_signin and not pws and len(boxes) == 1 and step and USER_HINT.search(
            f"{boxes[0].get('name')} {boxes[0].get('id')} {boxes[0].get('label')} {boxes[0].get('type')} "
            f"{boxes[0].get('autocomplete')}"):
        return {"user": boxes[0]["selector"], "password": "input[type=password]", "submit": step["selector"],
                "two_step": True}
    return None


def _user_box(fields: list[dict]) -> dict | None:
    """The user name / email box: an email box, a box whose name / label says user / email / login, else the
    first text box."""
    boxes = [x for x in fields if (x.get("type") or "text") in ("text", "email", "tel", "") and x.get("selector")]
    for x in boxes:
        hint = f"{x.get('name')} {x.get('id')} {x.get('label')} {x.get('placeholder')} {x.get('autocomplete')}"
        if x.get("type") == "email" or USER_HINT.search(hint):
            return x
    return boxes[0] if boxes else None


def _visible(page, selector: str) -> bool:
    try:
        return bool(selector) and page.locator(selector).first.is_visible()
    except Exception:
        return False


def _texts(page) -> list[str]:
    try:
        return page.evaluate(TEXT_JS)
    except Exception:
        return []


def _settle(page, ms: int = 6000) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=ms)
    except Exception:
        pass


def _is_auth_address(url: str) -> bool:
    from .agents.discovery import _auth_link
    return _auth_link(url) or bool(settings.login_url and url.split("#")[0].rstrip("/")
                                   == settings.login_url.split("#")[0].rstrip("/"))


def looks_logged_out(page, form: dict | None) -> bool:
    """While crawling logged in: is the login form back? (= the session expired or the page needs a login)."""
    pw = (form or {}).get("password") or "input[type=password]"
    return _visible(page, pw) and (_is_auth_address(page.url) or _visible(page, (form or {}).get("user", "")))


def totp(secret: str, at: float | None = None, digits: int = 6, period: int = 30) -> str:
    """The code an authenticator app shows now for this key (TOTP, RFC 6238: HMAC-SHA1 of the 30-second step).
    The key is the base32 setup key, or the whole otpauth://... address of the QR code."""
    import base64
    import hashlib
    import hmac
    import struct
    from urllib.parse import parse_qs, urlparse
    s = secret.strip()
    if s.lower().startswith("otpauth://"):
        q = parse_qs(urlparse(s).query)
        s, digits, period = q.get("secret", [""])[0], int(q.get("digits", [digits])[0]), int(q.get("period", [period])[0])
    s = s.replace(" ", "").replace("-", "").upper()
    key = base64.b32decode(s + "=" * (-len(s) % 8))
    mac = hmac.new(key, struct.pack(">Q", int((time.time() if at is None else at) // period)), hashlib.sha1).digest()
    o = mac[-1] & 0x0F
    return str((struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** digits).zfill(digits)


CODE_BOXES = ("input[autocomplete=one-time-code]", "input[name*=otp i]", "input[id*=otp i]", "input[name*=code i]",
              "input[id*=code i]", "input[placeholder*=code i]", "input[aria-label*=code i]", "input[name*=token i]",
              "input[inputmode=numeric]")
VERIFY_TEXT = re.compile(r"\b(verify|confirm|continue|submit|sign ?in|log ?in|next|done)\b", re.I)


def enter_code(tab) -> bool:
    """TEST_TOTP_SECRET: type the authenticator code into the code box (or one digit per box) and send it, like a
    person. True = a code was typed and sent (whether the website accepted it is checked by the caller)."""
    if not settings.test_totp_secret:
        return False
    code = totp(settings.test_totp_secret)
    singles = tab.locator("input[maxlength='1']:visible")
    box = None
    if singles.count() >= len(code):  # (one box per digit)
        for i, d in enumerate(code):
            singles.nth(i).fill(d, timeout=5000)
        box = singles.nth(len(code) - 1)
    else:
        box = next((tab.locator(s).first for s in CODE_BOXES if _visible(tab, s)), None)
        if box is None:
            return False
        box.fill(code, timeout=5000)
    btn = tab.get_by_role("button", name=VERIFY_TEXT).first
    if btn.count() and btn.is_visible():
        btn.click(timeout=5000)
    else:
        box.press("Enter")
    tab.wait_for_timeout(1500)
    _settle(tab)
    return True


def wait_for_person(tab, form: dict, seconds: int) -> dict | None:
    """A one-time code / CAPTCHA: a PERSON completes it in the visible browser window - the tester never fills in a
    code or solves a CAPTCHA. Waits up to `seconds` for verified signs of being logged in; returns the success result
    (with its evidence), or None when nobody completed it in time."""
    deadline, start_url = time.time() + seconds, tab.url
    while time.time() < deadline:
        try:
            tab.wait_for_timeout(1500)
            if _visible(tab, form["password"]) or tab.evaluate(MFA_JS) or CAPTCHA.search(tab.content()):
                continue  # (still on the code / CAPTCHA / login step)
            has_logout = bool(tab.evaluate(LOGOUT_JS))
            moved = tab.url != start_url and not _is_auth_address(tab.url)
            if not (has_logout or moved):
                continue
            evidence = ["a person completed the one-time code / CAPTCHA in the browser window", "the password box is gone"]
            evidence += [f"the address changed to {tab.url.split('?')[0]}"] if moved else []
            evidence += ["a log-out control is shown"] if has_logout else []
            tab.goto(tab.url, wait_until="domcontentloaded", timeout=settings.page_timeout_ms)  # the login must hold
            _settle(tab)
            if looks_logged_out(tab, form):
                continue
            evidence.append("still logged in after opening the page again")
            return {"outcome": "success", "logged_in": True, "evidence": evidence, "final_url": tab.url}
        except Exception:
            continue  # (the page is changing right now)
    return None


def log_in(context, url: str, form: dict, user: str, password: str, scope=None) -> tuple[object, dict]:
    """Open the login page in this (logged-in) browser session and sign in. Returns (tab, result).
    result = {"outcome", "logged_in", "evidence": [...], "final_url"} - never the password."""
    tab = context.new_page()
    statuses: list[int] = []

    def on_response(r):
        try:
            if r.request.is_navigation_request() and r.request.frame == tab.main_frame:
                statuses.append(r.status)
        except Exception:
            pass  # (service-worker requests have no frame)
    tab.on("response", on_response)
    result = {"outcome": "failed", "logged_in": False, "evidence": [], "final_url": ""}

    def done(outcome: str, *evidence: str):
        result.update(outcome=outcome, logged_in=outcome == "success", final_url=tab.url)
        result["evidence"] += [e for e in evidence if e]
        return tab, result

    try:
        tab.goto(url, wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
        _settle(tab)
        if CAPTCHA.search(tab.content()):
            if not settings.headless:  # a person will solve it: the account is typed in, the rest is up to them
                for box, value in ((form.get("user"), user), (form.get("password"), password)):
                    if box and _visible(tab, box):
                        tab.locator(box).first.fill(value, timeout=5000)
            return done("captcha", "a CAPTCHA is on the login page")
        if not _visible(tab, form["user"]):
            return done("unsupported", "the user name box was not visible")
        before_url, before_text = tab.url, set(_texts(tab))
        tab.locator(form["user"]).first.fill(user, timeout=5000)
        if not _visible(tab, form["password"]):  # two-step login: user name -> Continue / Next -> password
            nxt = tab.locator(form["submit"]).first if form.get("two_step") else \
                tab.get_by_role("button", name=NEXT_TEXT).first
            if nxt.count():
                nxt.click(timeout=5000)
                form = dict(form, submit="")  # (step 2 has its own button: found below, or Enter)
                tab.wait_for_timeout(500)
                try:
                    tab.locator(form["password"]).first.wait_for(state="visible", timeout=8000)
                except Exception:
                    pass
            if not _visible(tab, form["password"]):
                if tab.evaluate(MFA_JS):
                    return done("mfa_required", "a one-time code box appeared after the user name")
                return done("unsupported", "the password box did not appear")
            before_url, before_text = tab.url, set(_texts(tab))  # (step 2 starts here)
        tab.locator(form["password"]).first.fill(password, timeout=5000)
        final = tab.get_by_role("button", name=LOGIN_TEXT).first
        if form.get("submit") and _visible(tab, form["submit"]):
            tab.locator(form["submit"]).first.click(timeout=5000)
        elif final.count() and final.is_visible():
            final.click(timeout=5000)
        else:
            tab.locator(form["password"]).first.press("Enter")
        # wait for something observable: a new page, the login form going away, or a message
        deadline = time.time() + 12
        while time.time() < deadline:
            tab.wait_for_timeout(500)
            if tab.url != before_url or not _visible(tab, form["password"]):
                break
            if any(INVALID.search(t) or LOCKED.search(t) for t in set(_texts(tab)) - before_text):
                break
        _settle(tab)

        new_text = [t for t in _texts(tab) if t not in before_text]
        if scope is not None and scope.navigation_blocked(tab.url):
            return done("sso_redirect", f"after signing in the browser is on {tab.url.split('?')[0]}")
        if CAPTCHA.search(tab.content()):
            return done("captcha", "a CAPTCHA appeared after signing in")
        try:
            has_logout = bool(tab.evaluate(LOGOUT_JS))
        except Exception:
            has_logout = False
        # a code box, or a "enter the verification code" text on a page without a log-out control
        # (a dashboard that merely mentions "two-factor settings" is not an MFA prompt)
        if tab.evaluate(MFA_JS) or (not has_logout and _visible(tab, "input:not([type=hidden]):not([type=password])")
                                    and any(MFA_HINT.search(t) for t in new_text[:30])):
            if not (enter_code(tab) and not tab.evaluate(MFA_JS)):  # (the authenticator key, when you gave one)
                return done("mfa_required", "the website asks for a one-time code" + (
                    " - the code made from TEST_TOTP_SECRET was not accepted" if settings.test_totp_secret else ""))
            result["evidence"].append("the one-time code was made from the test account's authenticator key "
                                      "(TEST_TOTP_SECRET) and typed in")
            new_text = [t for t in _texts(tab) if t not in before_text]
            try:
                has_logout = bool(tab.evaluate(LOGOUT_JS))
            except Exception:
                has_logout = False
        if statuses and statuses[-1] in (401, 403):
            return done("access_denied", f"the website answered HTTP {statuses[-1]}")
        message = next((t for t in new_text if INVALID.search(t) or LOCKED.search(t) or DENIED.search(t)), "")
        pw_gone = not _visible(tab, form["password"])
        if message and not pw_gone:
            kind = "locked" if LOCKED.search(message) else "access_denied" if DENIED.search(message) \
                else "invalid_credentials"
            return done(kind, f"the website says: \"{message[:120]}\"")

        evidence = []
        if settings.login_success_text or settings.login_success_url:  # your own success condition decides
            ok_text = not settings.login_success_text or any(settings.login_success_text.lower() in t.lower()
                                                              for t in _texts(tab))
            ok_url = not settings.login_success_url or settings.login_success_url in tab.url
            if not (ok_text and ok_url):
                return done("failed", "the success condition from .env (LOGIN_SUCCESS_TEXT / LOGIN_SUCCESS_URL) "
                                      "is not met")
            evidence.append("the success condition from .env is met")
        if not pw_gone:
            return done("failed", "the password box is still shown")
        evidence.append("the password box is gone")
        if tab.url != before_url and not _is_auth_address(tab.url):
            evidence.append(f"the address changed to {tab.url.split('?')[0]}")
        if has_logout:
            evidence.append("a log-out control is shown")
        if len(evidence) < 2:
            return done("failed", *evidence, "no second sign of being logged in (address / log-out control)")
        # the login must hold: open the page again and check the login form does not come back
        landing = tab.url
        tab.goto(landing, wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
        _settle(tab)
        if looks_logged_out(tab, form):
            return done("failed", *evidence, "but the login form came back after opening the page again")
        evidence.append("still logged in after opening the page again")
        return done("success", *evidence)
    except Exception as e:
        print(f"  [login] could not sign in: {str(e).splitlines()[0][:150]}")
        result["evidence"].append(f"browser error: {str(e).splitlines()[0][:150]}")
        return tab, result
