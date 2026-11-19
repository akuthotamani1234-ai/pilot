"""GET redirect probe that refuses a checkout document before it is loaded."""
from __future__ import annotations


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
            return current, "", response
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
