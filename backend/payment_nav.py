"""GET redirect probe that refuses a checkout document before it is loaded."""
from __future__ import annotations

import re

_META_TAG = re.compile(r"<meta\b([^>]*)>", re.I)
_HTTP_EQUIV = re.compile(r"""http-equiv\s*=\s*['"]?\s*refresh\b""", re.I)
_CONTENT = re.compile(r"""content\s*=\s*(?:(['"])(.*?)\1|([^\s>]+))""", re.I)
_REFRESH_URL = re.compile(r"""url\s*=\s*['"]?([^'";>\s]+)""", re.I)


def _response_html(response) -> str:
    """A short prefix of the response body, or '' when the probe has no body."""
    text = getattr(response, "text", None)
    try:
        raw = text() if callable(text) else (text or "")
    except Exception:
        return ""
    if isinstance(raw, bytes):
        raw = raw[:8000].decode("utf-8", "replace")
    else:
        raw = str(raw)[:8000]
    return raw


def meta_refresh_url(html: str, base: str) -> str:
    """The immediate meta-refresh address, or '' when the page does not refresh."""
    from urllib.parse import urljoin

    if not html or "refresh" not in html.lower():
        return ""
    for attrs in _META_TAG.findall(html):
        if not _HTTP_EQUIV.search(attrs):
            continue
        found = _CONTENT.search(attrs)
        if not found:
            continue
        value = found.group(2) if found.group(2) is not None else (found.group(3) or "")
        delay = re.match(r"\s*(\d+)", value)
        if delay and int(delay.group(1)) > 1:
            continue
        target = _REFRESH_URL.search(value)
        if not target:
            continue
        return urljoin(base, target.group(1).strip())
    return ""


def _walk(fetch, address: str, *, base: str = "", timeout: int = 10000):
    """Return ``(open_url, blocked_url, response)`` without requesting checkout."""
    from urllib.parse import urljoin

    from .swarm import is_payment_url

    current = (address or "").strip()
    if not current or current.startswith("#") or current.lower().startswith("javascript:"):
        return current, "", None
    if base:
        current = urljoin(base, current)
    if is_payment_url(current):
        return "", current, None
    response = None
    for _hop in range(5):
        response = fetch(current, max_redirects=0, timeout=timeout)
        if getattr(response, "status", None) not in {301, 302, 303, 307, 308}:
            nxt = meta_refresh_url(_response_html(response), current)
            if not nxt or nxt == current:
                return current, "", response
            if is_payment_url(nxt):
                return "", nxt, None
            current = nxt
            continue
        headers = getattr(response, "headers", None) or {}
        location = headers.get("location") or headers.get("Location") or ""
        if not location:
            return "", current, None
        nxt = urljoin(current, location)
        if is_payment_url(nxt):
            return "", nxt, None
        current = nxt
    return "", current, None


def follow_get(fetch, address: str, *, base: str = "", timeout: int = 10000) -> tuple[str, str]:
    """Return ``(open_url, blocked_url)`` for one GET, without loading the document.

    ``blocked_url`` is the checkout address, or the last hop after five
    redirects. ``open_url`` is the last address that is still off checkout.
    A javascript or hash address is left for the caller.
    """
    open_url, blocked, _response = _walk(fetch, address, base=base, timeout=timeout)
    return open_url, blocked


def embedded_payment(url: str, *, top_document: bool, frame_url: str = "") -> str:
    """Return a block reason when checkout is loaded from some other page.

    A top-level document that is itself checkout may be recorded once. Requests
    made by that checkout page are left alone.
    """
    from .swarm import is_payment_url

    if not is_payment_url(url):
        return ""
    if top_document:
        return ""
    if frame_url and is_payment_url(frame_url):
        return ""
    return "checkout, payment and placing an order are never tested"


def read_safe(fetch, address: str, *, base: str = "", timeout: int = 10000):
    """Return the GET response, or None when the chain reaches checkout.

    The checkout address itself is not requested.
    """
    _open, blocked, response = _walk(fetch, address, base=base, timeout=timeout)
    if blocked:
        return None
    return response


def payment_redirect(fetch, address: str, *, base: str = "", timeout: int = 10000) -> str:
    """Return the checkout address a GET would reach, or '' when the click may proceed."""
    _open, blocked = follow_get(fetch, address, base=base, timeout=timeout)
    return blocked


def opens_checkout(fetch, address: str, *, base: str = "", timeout: int = 10000) -> str:
    """The checkout address this GET would open, including an address that already is checkout.

    A probe that cannot reach the host returns '' so a normal page can still be opened.
    """
    from urllib.parse import urljoin

    from .swarm import is_payment_url

    current = (address or "").strip()
    if base and current:
        current = urljoin(base, current)
    if is_payment_url(current):
        return current
    try:
        return payment_redirect(fetch, current, timeout=timeout)
    except Exception:
        return ""
