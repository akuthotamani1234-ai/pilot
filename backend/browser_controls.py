"""What the test browser does with a run's environment controls and dependency fault.

Discovery writes qx_environment.json before pytest. Execution writes qx_dependency.json.
This module only reads those files. A missing or unreadable file leaves every control off
and injects no fault. Production stays off even when a file says a control is enabled.
Payment, delete, and logout are never opened by a control or a fault.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from .data_lifecycle import production_environment
from .env_controls import CONTROLS, action_still_blocked, enable_control

# A fixed instant, not "now": the page must not ask the network what time it is.
FIXED_CLOCK_ISO = "2020-01-01T00:00:00.000Z"
_APPROVED = frozenset({"test", "staging"})
# Whole tokens only, so "payload" and "buying-guide" are not payments.
_PAY_URL = re.compile(
    r"(?:^|[^a-z0-9])(?:check-?out|purchase|buy(?:-now)?|payments?|pay)(?=$|[^a-z0-9])",
    re.I,
)
# Admin screens and an OpenCart cart route (index.php?rt=checkout/cart) are not the payment.
_PAY_NOT_CHECKOUT = re.compile(
    r"pay[-_]grades?|payment[-_]methods?|pay[-_]periods?|pay[-_]scales?|checkout[/_.-](?:cart|basket|bag)",
    re.I,
)
_DELETE_URL = re.compile(r"(?:^|[^a-z0-9])(?:delete|unsubscribe|deactivate)(?=$|[^a-z0-9])", re.I)
_LOGOUT_URL = re.compile(r"(?:^|[^a-z0-9])(?:log-?out|sign-?out)(?=$|[^a-z0-9])", re.I)
# Taking a line out of the test's own cart is not an account delete (the click guard's rule).
_CART_LINE = re.compile(r"cart|basket|trolley", re.I)
_CLOCK_JS = f"""(() => {{
  const fixed = Date.parse("{FIXED_CLOCK_ISO}");
  const Native = Date;
  function Frozen(...args) {{
    const made = new Native(...(args.length ? args : [fixed]));
    return this instanceof Frozen ? made : made.toISOString();
  }}
  Frozen.now = () => fixed;
  Frozen.parse = Native.parse.bind(Native);
  Frozen.UTC = Native.UTC.bind(Native);
  Frozen.prototype = Native.prototype;
  window.Date = Frozen;
}})();"""


def _read(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _approved(environment: str) -> bool:
    """Controls and faults run only on test or staging, never on production."""
    if production_environment(environment):
        return False
    return environment.strip().lower() in _APPROVED


def _flag(raw: object) -> bool:
    if isinstance(raw, dict):
        return raw.get("enabled") is True
    return raw is True


def _control_on(environment: str, name: str, raw: object) -> bool:
    """A file that says enabled is still off when this environment may not use the control."""
    allowed, _reason = enable_control(environment, name)
    return allowed and _flag(raw)


def load_controls(run_dir: str | Path) -> dict:
    """Which controls are on, and which dependency was made unavailable.

    Missing files, broken JSON, and a production environment all mean every control is
    off and no fault is injected. ``enabled`` is honored only on test or staging.
    """
    folder = Path(run_dir)
    environment_file = _read(folder / "qx_environment.json") or {}
    dependency_file = _read(folder / "qx_dependency.json") or {}
    environment = str(environment_file.get("environment") or "").strip()
    raw_controls = environment_file.get("controls") if isinstance(environment_file.get("controls"), dict) else {}
    service = ""
    injected = False
    if _approved(environment) and dependency_file.get("injected") is True:
        service = str(dependency_file.get("service") or "").strip()
        injected = bool(service)
    enabled = {name: _control_on(environment, name, raw_controls.get(name)) for name in sorted(CONTROLS)}
    return {
        "environment": environment,
        **enabled,
        "injected": injected,
        "service": service if injected else "",
    }


def clock_script(controls: dict | None = None) -> str:
    """JavaScript that freezes Date at one instant, or '' when the fixed clock is off.

    The snippet does not load anything. It is added to the browser only when this returns text.
    """
    if not isinstance(controls, dict) or controls.get("fixed_clock") is not True:
        return ""
    return _CLOCK_JS


def _haystack(url: str) -> str:
    parsed = urlparse(str(url or ""))
    return f"{parsed.path}?{parsed.query}"


def _payment_url(hay: str) -> bool:
    if not _PAY_URL.search(hay):
        return False
    if _PAY_NOT_CHECKOUT.search(hay) and not _PAY_URL.search(_PAY_NOT_CHECKOUT.sub(" ", hay)):
        return False
    return action_still_blocked("pay")[0]


def _protected_url(url: str) -> bool:
    """Payment, delete, and logout stay blocked. A control must not turn that into an allow."""
    hay = _haystack(url)
    if _LOGOUT_URL.search(hay) and action_still_blocked("logout")[0]:
        return True
    if _DELETE_URL.search(hay) and not _CART_LINE.search(hay) and action_still_blocked("delete")[0]:
        return True
    return _payment_url(hay)


def _same_document(url: str, start: str) -> bool:
    """The start page itself, ignoring a trailing slash, a fragment, and the default port."""
    here, home = urlparse(str(url or "")), urlparse(str(start or ""))
    if here.scheme not in {"http", "https"} or home.scheme not in {"http", "https"}:
        return False
    if (here.hostname or "").lower() != (home.hostname or "").lower():
        return False
    default = {"http": 80, "https": 443}
    here_port = here.port or default.get(here.scheme)
    home_port = home.port or default.get(home.scheme)
    if here_port != home_port:
        return False
    return here.path.rstrip("/") == home.path.rstrip("/")


def _host_has_service(url: str, service: str) -> bool:
    name = service.strip().lower()
    # One letter would match almost every host. The fault names a real service.
    if len(name) < 2 or any(mark in name for mark in "/\\?#@"):
        return False
    host = (urlparse(str(url or "")).hostname or "").lower().rstrip(".")
    return bool(host) and name in host


def request_blocked(url: str, controls: dict | None) -> bool:
    """True when this request must not be sent.

    A network fault fails http(s) and websocket calls except the top-level document
    navigation to ``controls['start_url']`` (``controls['navigation']`` is True only
    for that document). A dependency fault fails a host that contains the service
    name. Payment, delete, and logout stay blocked even when no fault was injected,
    including when that address is the start page.
    """
    chosen = controls if isinstance(controls, dict) else {}
    if _protected_url(url):
        return True
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https", "ws", "wss"}:
        return False
    if chosen.get("navigation") is True and _same_document(url, str(chosen.get("start_url") or "")):
        return False
    if chosen.get("network_fault") is True:
        return True
    if chosen.get("injected") is True and _host_has_service(url, str(chosen.get("service") or "")):
        return True
    return False
