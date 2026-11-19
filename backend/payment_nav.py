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
