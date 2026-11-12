"""Safety rules shared by every part of the tester.

1. WHERE the tester may go (the "approved scope"):
   - the host of the website you gave (http and https), plus the hosts in ALLOWED_HOSTS (.env)
   - cloud metadata addresses (169.254.169.254 ...) are ALWAYS blocked
   - when the website is public, your own PC and private networks (localhost, 10.x, 192.168.x ...) are blocked too,
     so a website can't make the tester reach them. Testing your own localhost app is allowed: then it is the target.
2. WHAT must never be shown: passwords, API keys and tokens are replaced by [REDACTED] in logs, reports,
   results and AI requests (redact()).
"""
import binascii
import ipaddress
import json
import os
import re
import socket
from functools import lru_cache
from urllib.parse import urlparse, urlunparse

METADATA_HOSTS = {"169.254.169.254", "169.254.170.2", "100.100.100.200", "fd00:ec2::254",
                  "metadata.google.internal", "metadata.goog", "metadata"}
REDACTED = "[REDACTED]"
# environment variables whose values are secrets (never printed, never given to generated tests or started apps)
SECRET_ENV = ("TEST_PASSWORD", "OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN",
              "SLACK_WEBHOOK_URL", "JIRA_API_TOKEN", "WEBHOOK_TOKEN", "TEST_TOTP_SECRET")
API_KEY_ENV = ("OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "SLACK_WEBHOOK_URL",
               "JIRA_API_TOKEN", "WEBHOOK_TOKEN", "TEST_TOTP_SECRET")


class UrlError(ValueError):
    """The address can't be tested (the message says why, in plain English)."""


def _ip(host: str):
    try:
        return ipaddress.ip_address(host.strip("[]").split("%")[0])
    except ValueError:
        return None


def _is_private_ip(ip) -> bool:
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified \
        or ip.is_multicast


@lru_cache(maxsize=512)
def _resolve(host: str) -> tuple:
    try:
        return tuple({a[4][0] for a in socket.getaddrinfo(host, None)})
    except (OSError, UnicodeError):
        return ()


def _is_metadata_address(host: str) -> bool:
    """Literal metadata name/IP, including IPv4-mapped forms (:ffff:169.254.169.254)."""
    if host in METADATA_HOSTS:
        return True
    ip = _ip(host)
    if ip is None:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return str(ip) in METADATA_HOSTS


def is_metadata_host(host: str | None, resolve: bool = False) -> bool:
    h = (host or "").lower().strip("[]").rstrip(".")
    if not h:
        return False
    if _is_metadata_address(h):
        return True
    return resolve and any(_is_metadata_address(a) for a in _resolve(h))


def is_private_host(host: str | None, resolve: bool = False) -> bool:
    """localhost / 127.x / 10.x / 192.168.x / ::1 ... (and names that resolve there, when resolve=True)."""
    h = (host or "").lower().strip("[]").rstrip(".")
    if not h:
        return False
    if h == "localhost" or h.endswith(".localhost") or h.endswith(".local"):
        return True
    ip = _ip(h)
    if ip is not None:
        return _is_private_ip(ip)
    if resolve:
        return any(_is_private_ip(_ip(a)) for a in _resolve(h) if _ip(a) is not None)
    return False


TEST_HOST = re.compile(r"(staging|stage|stg|test|testing|qa|dev|develop|development|uat|preview|sandbox)\d*", re.I)


def looks_like_test_host(host: str | None) -> bool:
    """Does the address say it is a test copy (staging.shop.com, qa-portal, localhost ...)? Then a staging run may change
    data after the usual "I own it" confirmation; any other host needs a second confirmation. A WHOLE part of the name
    counts ('shop-test.example.com'), never a word that only contains it ('automationteststore.com'), nor the ending
    ('site.dev')."""
    if is_private_host(host):  # (localhost, 127.0.0.1, 192.168.x ...: the user's own machine / network)
        return True
    words = [w for label in (host or "").lower().strip(".").split(".")[:-1] for w in label.split("-")]
    return any(TEST_HOST.fullmatch(w) for w in words)


def check_target(url: str, resolve: bool = True) -> str:
    """The website address the user gave -> the same address, or UrlError with the reason."""
    p = urlparse((url or "").strip())
    if p.scheme not in ("http", "https"):
        raise UrlError("Only http:// and https:// websites can be tested.")
    if not p.hostname:
        raise UrlError("This address has no website name in it.")
    if p.username or p.password:
        raise UrlError("Don't put a user name or password in the address. Give the test account in the login "
                       "fields instead (it is then never shown or saved).")
    if is_metadata_host(p.hostname, resolve=resolve):
        raise UrlError("This is a cloud metadata address. It is never tested (it can expose server secrets).")
    return url.strip()


def unwrap_link(source: str) -> str:
    """A link copied from search results (Bing / Google / DuckDuckGo / Yahoo) only redirects to the real website:
    return the real address hidden inside it, so the website is tested and not the search engine's redirect page."""
    import base64
    from urllib.parse import parse_qs, unquote

    s = (source or "").strip()
    p = urlparse(s if "://" in s else "https://" + s)
    host, q = (p.hostname or "").lower(), parse_qs(p.query)
    try:
        if host.endswith("bing.com") and p.path.startswith("/ck/") and q.get("u"):
            u = q["u"][0]
            u = u[2:] if u.startswith("a1") else u  # Bing: "a1" + the address in base64
            real = base64.urlsafe_b64decode(u + "=" * (-len(u) % 4)).decode("utf-8")
            return real if real.startswith("http") else s
        if re.match(r"(www\.)?google\.", host) and p.path == "/url":
            real = (q.get("q") or q.get("url") or [""])[0]
            return real if real.startswith("http") else s
        if host.endswith("duckduckgo.com") and p.path.startswith("/l/") and q.get("uddg"):
            return unquote(q["uddg"][0])
        if host.endswith("search.yahoo.com") and "/RU=" in p.path:
            real = unquote(p.path.split("/RU=", 1)[1].split("/", 1)[0])
            return real if real.startswith("http") else s
    except (ValueError, UnicodeDecodeError, binascii.Error):
        pass
    return s


def search_redirect(url: str) -> bool:
    """Still a search engine's click-tracking redirect (one that could not be unwrapped), not a website."""
    p = urlparse((url or "").strip())
    host = (p.hostname or "").lower()
    return bool(host.endswith("bing.com") and p.path.startswith("/ck/")
                or re.match(r"(www\.)?google\.", host) and p.path == "/url"
                or host.endswith("duckduckgo.com") and p.path.startswith("/l/")
                or host.endswith("search.yahoo.com") and "/RU=" in p.path)


def _host_matches(host: str, pattern: str) -> bool:
    pattern = pattern.lower().strip()
    return host == pattern or (pattern.startswith("*.") and host.endswith(pattern[1:]))


class Scope:
    """The approved scope of one run: which hosts the browser may navigate to, which requests are blocked."""

    def __init__(self, start_url: str, extra_hosts: list[str] | tuple = ()):
        p = urlparse(start_url)
        self.host = (p.hostname or "").lower()
        self.port = p.port
        self.extra = [h.strip().lower() for h in extra_hosts if h and h.strip()]
        # your own PC / office network is the target -> other private addresses may be used too (local APIs)
        self.local = is_private_host(self.host, resolve=True)

    def in_scope(self, url: str) -> bool:
        """May the browser navigate to (and the crawler test) this page?"""
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        h = p.hostname.lower()
        if h == self.host:
            return True
        return any(_host_matches(h, x) for x in self.extra)

    def blocked(self, url: str) -> str | None:
        """Why a request to this address must be stopped (None = allowed). Pages, pictures, scripts, APIs."""
        p = urlparse(url)
        if p.scheme not in ("http", "https", "ws", "wss"):
            return None  # data:, blob:, about: ... stay inside the browser
        h = (p.hostname or "").lower()
        # resolve=True: a DNS name that points at metadata must not slip through when the target is local
        # (local targets may reach other private addresses, but never cloud metadata).
        if is_metadata_host(h, resolve=True):
            return "cloud metadata address (always blocked; it can expose server secrets)"
        if not self.local and is_private_host(h) and not self.in_scope(url):
            return "private network / this PC (blocked because the website under test is public)"
        return None

    def navigation_blocked(self, url: str) -> str | None:
        """Why the browser may not open this as the main page (None = allowed)."""
        why = self.blocked(url)
        if why:
            return why
        p = urlparse(url)
        if p.scheme in ("http", "https") and not self.in_scope(url):
            return (f"outside the approved scope ({p.hostname} is not {self.host}; "
                    f"add it to ALLOWED_HOSTS to allow it)")
        return None


# Ad and tracker networks: never part of the website under test, and the slowest part of many pages (a page full of
# ads never goes quiet, so every page load waited its full time). Stopped silently while exploring and testing.
AD_HOSTS = re.compile(r"(^|\.)(doubleclick\.net|googlesyndication\.com|googleadservices\.com|adservice\.google\.[a-z.]+|"
                      r"google-analytics\.com|googletagmanager\.com|googletagservices\.com|adnxs\.com|"
                      r"amazon-adsystem\.com|criteo\.(com|net)|taboola\.com|outbrain\.com|scorecardresearch\.com|"
                      r"hotjar\.com|facebook\.net|connect\.facebook\.net|ads\.linkedin\.com|quantserve\.com|"
                      r"pubmatic\.com|rubiconproject\.com|openx\.net|casalemedia\.com|moatads\.com|"
                      r"fundingchoicesmessages\.google\.com|clarity\.ms)$", re.I)


def is_ad(url: str) -> bool:
    """Is this request for an ad / tracker network (never the website under test)?"""
    return bool(AD_HOSTS.search((urlparse(url).hostname or "").lower()))


# The website complains that a tracker did not load - because WE stopped it (AD_HOSTS): practicesoftwaretesting.com
# wrote "Failed to load Google Analytics script" on every page and 2 journeys failed on our own blocking (Nov 3, 2026).
# Such an error is a warning, never the website's error.
TRACKER_SAID = re.compile(r"\b(google[ -]?analytics|gtag|googletagmanager|google tag manager|gtm\.js|analytics\.js|"
                          r"adsbygoogle|doubleclick|googlesyndication|fbq|facebook pixel|hotjar|clarity\.ms|"
                          r"ga is not defined|dataLayer is not defined)\b", re.I)


def blocked_tracker_said(text: str) -> bool:
    """Is this console error / exception about a tracker the run blocked (not the website's own error)?"""
    return bool(TRACKER_SAID.search(text or ""))


def guard_context(context, scope: Scope, blocked: list) -> None:
    """Make a Playwright browser context obey the scope: requests to blocked addresses are aborted, and so are
    main-page navigations that leave the approved hosts. Every blocked address is added to `blocked`. Ads and
    trackers are stopped silently (is_ad). (A server-side redirect is only seen after the browser followed it: callers
    check page.url afterwards.)"""
    def handle(route):
        req = route.request
        if is_ad(req.url) and not scope.in_scope(req.url):
            try:
                route.abort("blockedbyclient")
            except Exception:
                pass
            return
        why = scope.blocked(req.url)
        if not why:
            try:
                top = req.is_navigation_request() and req.frame.parent_frame is None
            except Exception:
                top = False
            if top:
                why = scope.navigation_blocked(req.url)
        if why:
            if len(blocked) < 200:
                blocked.append({"url": req.url[:200], "reason": why})
            try:
                route.abort("blockedbyclient")
            except Exception:
                pass
            return
        try:
            route.continue_()
        except Exception:
            pass  # the page was closed meanwhile
    context.route("**/*", handle)


# ------------------------------------------------------------------ secrets

def secret_values(include_username: bool = False) -> list[str]:
    """The secret values known to this process (from the environment), longest first."""
    names = SECRET_ENV + (("TEST_USERNAME",) if include_username else ())
    names += tuple(k for k in os.environ if k.startswith("BLOWAI_SECRET_"))
    vals = {os.environ.get(n, "") for n in names}
    try:
        worker_inputs = json.loads(os.environ.get("ANDROID_CONTRACT_INPUTS", "{}"))
        vals.update(value for value in worker_inputs.get("secrets", {}).values() if isinstance(value, str))
    except (ValueError, AttributeError, TypeError):
        pass
    for a in os.environ.get("TEST_ACCOUNTS", "").split(","):  # (several roles: every password, and their user names)
        parts = a.split(":", 2)
        if len(parts) == 3:
            vals.add(parts[2])
            if include_username:
                vals.add(parts[1].strip())
    return sorted((v for v in vals if len(v) >= 4), key=len, reverse=True)


URL_USERINFO = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@", re.I)


def redact(text, values: list[str] | None = None, include_username: bool = False):
    """Replace every secret value in a text with [REDACTED] (also user:password@ inside addresses)."""
    if not isinstance(text, str) or not text:
        return text
    for v in (values if values is not None else secret_values(include_username)):
        if v and v in text:
            text = text.replace(v, REDACTED)
    return URL_USERINFO.sub(r"\1" + REDACTED + "@", text)


# App package ids often contain a short test username (com.blowai.demo + username "demo").
# Machine-readable Android artifacts still need a valid package for reset/activate/terminate.
ANDROID_PACKAGE_KEYS = frozenset({"package_name", "appPackage", "app_package", "package"})
_ANDROID_PACKAGE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")


def android_package_identifiers(data) -> list[str]:
    """Collect dotted Android package ids from known keys (longest first)."""
    found: set[str] = set()

    def walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in ANDROID_PACKAGE_KEYS and isinstance(value, str) and _ANDROID_PACKAGE_ID.fullmatch(value):
                    found.add(value)
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    return sorted(found, key=len, reverse=True)


def redact_json(data, values: list[str] | None = None, include_username: bool = False) -> str:
    """JSON dump with secrets removed, but valid Android package identifiers left intact."""
    text = json.dumps(data, indent=2, ensure_ascii=False)
    packages = android_package_identifiers(data)
    if values is None:
        values = secret_values(include_username)
    out = redact(text, values=values, include_username=include_username)
    for package in packages:
        corrupted = redact(package, values=values, include_username=include_username)
        if corrupted != package and corrupted in out:
            out = out.replace(corrupted, package)
    return out


def clean_env(env: dict, keep_test_account: bool = False) -> dict:
    """A copy of the environment without API keys / tokens (and without the test account unless needed).
    Used for the generated tests and for apps started from a GitHub repo or folder."""
    out = {k: v for k, v in env.items() if k not in API_KEY_ENV and not k.startswith(("BLOWAI_SECRET_", "BLOWAI_DB_"))}
    out.pop("ANDROID_CONTRACT_INPUTS", None)
    out.pop("TEST_ACCOUNTS", None)  # (the role tests use the saved logins of the roles - never their passwords)
    if not keep_test_account:
        out.pop("TEST_USERNAME", None)
        out.pop("TEST_PASSWORD", None)
    return out


def safe_url_for_display(url: str) -> str:
    """An address without user:password@ in it."""
    p = urlparse(url or "")
    if p.username or p.password:
        netloc = p.hostname + (f":{p.port}" if p.port else "")
        return urlunparse(p._replace(netloc=netloc))
    return url
