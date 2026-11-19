"""GET redirect probe that refuses a checkout document before it is loaded."""
from __future__ import annotations


def follow_get(fetch, address: str, *, base: str = "", timeout: int = 10000) -> tuple[str, str]:
    """Return ``(open_url, blocked_url)`` for one GET, without loading the document.

    ``blocked_url`` is the checkout address, or the last hop after five
    redirects. ``open_url`` is the last address that is still off checkout.
    A javascript or hash address is left for the caller.
    """
    from urllib.parse import urljoin

    from .swarm import is_payment_url

    current = (address or "").strip()
    if not current or current.startswith("#") or current.lower().startswith("javascript:"):
        return current, ""
    if base:
        current = urljoin(base, current)
    if is_payment_url(current):
        return "", current
    for _hop in range(5):
        probe = fetch(current, max_redirects=0, timeout=timeout)
        if getattr(probe, "status", None) not in {301, 302, 303, 307, 308}:
            return current, ""
        headers = getattr(probe, "headers", None) or {}
        location = headers.get("location") or headers.get("Location") or ""
        if not location:
            return "", current
        nxt = urljoin(current, location)
        if is_payment_url(nxt):
            return "", nxt
        current = nxt
    return "", current


def payment_redirect(fetch, address: str, *, base: str = "", timeout: int = 10000) -> str:
    """Return the checkout address a GET would reach, or '' when the click may proceed."""
    _open, blocked = follow_get(fetch, address, base=base, timeout=timeout)
    return blocked
