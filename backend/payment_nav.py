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


def _refresh_target(value: str, base: str, *, payment_any_delay: bool = False) -> str:
    """The address in a refresh delay, or '' when it is missing or not immediate.

    A refresh into checkout is returned even when the delay is longer than a second.
    A slow refresh to any other page stays ignored.
    """
    from urllib.parse import urljoin

    delay = re.match(r"\s*(\d+)", value or "")
    slow = bool(delay and int(delay.group(1)) > 1)
    target = _REFRESH_URL.search(value or "")
    if not target:
        return ""
    found = urljoin(base, target.group(1).strip())
    if slow:
        if not payment_any_delay:
            return ""
        from .swarm import is_payment_url
        if not is_payment_url(found):
            return ""
    return found


def header_refresh_url(response, base: str, *, payment_any_delay: bool = False) -> str:
    """The address in a Refresh response header, or '' when the header is absent."""
    headers = getattr(response, "headers", None) or {}
    raw = headers.get("refresh") or headers.get("Refresh") or ""
    return _refresh_target(str(raw), base, payment_any_delay=payment_any_delay)


def meta_refresh_url(html: str, base: str, *, payment_any_delay: bool = False) -> str:
    """The immediate meta-refresh address, or a later one when it enters checkout."""
    if not html or "refresh" not in html.lower():
        return ""
    for attrs in _META_TAG.findall(html):
        if not _HTTP_EQUIV.search(attrs):
            continue
        found = _CONTENT.search(attrs)
        if not found:
            continue
        value = found.group(2) if found.group(2) is not None else (found.group(3) or "")
        target = _refresh_target(value, base, payment_any_delay=payment_any_delay)
        if target:
            return target
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
            nxt = header_refresh_url(response, current, payment_any_delay=True) or meta_refresh_url(
                _response_html(response), current, payment_any_delay=True)
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


_REDIRECTS = {301, 302, 303, 307, 308}
_DROP_HEADERS = {"content-encoding", "content-length", "transfer-encoding"}


def _fulfill(route, response, body: bytes | None = None) -> None:
    """Pass a fetched response to the browser. A modified body drops encoding headers."""
    if body is None:
        route.fulfill(response=response)
        return
    headers = {k: v for k, v in dict(response.headers).items() if k.lower() not in _DROP_HEADERS}
    route.fulfill(status=response.status, headers=headers, body=body)


def navigate_for_crawl(page, url: str, *, timeout: int, wait_until: str = "domcontentloaded"):
    """Open one page in the browser. Return ``(response, blocked_url)``.

    The browser's own navigation is the request that can be cancelled, so an
    HTTP 204 still reaches Chrome and the crawl can try the page once more.
    A redirect or a refresh into checkout is aborted before that
    document is requested. A URL that is already checkout is opened as-is.
    """
    from urllib.parse import urljoin

    from .swarm import is_payment_url

    if is_payment_url(url):
        return page.goto(url, wait_until=wait_until, timeout=timeout), ""

    blocked = {"url": ""}
    hops = {"n": 0}

    def handle(route):
        req = route.request
        try:
            top = (req.resource_type == "document" and req.is_navigation_request()
                   and req.frame.parent_frame is None)
        except Exception:
            top = False
        if not top or blocked["url"]:
            route.continue_()
            return
        if is_payment_url(req.url):
            blocked["url"] = req.url
            try:
                route.abort("blockedbyclient")
            except Exception:
                pass
            return
        hops["n"] += 1
        if hops["n"] > 5:
            blocked["url"] = req.url
            try:
                route.abort("blockedbyclient")
            except Exception:
                pass
            return
        try:
            response = route.fetch(max_redirects=0, timeout=timeout)
        except Exception:
            route.continue_()
            return
        status = getattr(response, "status", None)
        headers = getattr(response, "headers", None) or {}
        if status in _REDIRECTS:
            location = headers.get("location") or headers.get("Location") or ""
            nxt = urljoin(req.url, location) if location else ""
            if not nxt or is_payment_url(nxt):
                blocked["url"] = nxt or req.url
                try:
                    route.abort("blockedbyclient")
                except Exception:
                    pass
                return
            _fulfill(route, response)
            return
        nxt = header_refresh_url(response, req.url, payment_any_delay=True)
        if status in (204, 205):
            if nxt and nxt != req.url and is_payment_url(nxt):
                blocked["url"] = nxt
                try:
                    route.abort("blockedbyclient")
                except Exception:
                    pass
                return
            _fulfill(route, response)
            return
        try:
            body = response.body()
        except Exception:
            body = b""
        html = body[:8000].decode("utf-8", "replace")
        nxt = nxt or meta_refresh_url(html, req.url, payment_any_delay=True)
        if nxt and nxt != req.url and is_payment_url(nxt):
            blocked["url"] = nxt
            try:
                route.abort("blockedbyclient")
            except Exception:
                pass
            return
        _fulfill(route, response, body)

    page.route("**/*", handle)
    try:
        try:
            response = page.goto(url, wait_until=wait_until, timeout=timeout)
        except Exception:
            if blocked["url"]:
                return None, blocked["url"]
            raise
        return response, blocked["url"]
    finally:
        try:
            page.unroute("**/*", handle)
        except Exception:
            pass


_CANCELLED = re.compile(r"net::ERR_ABORTED|NS_BINDING_ABORTED|interrupted by another navigation")


def open_refusing_checkout(page, url: str, *, timeout: int, wait_until: str = "domcontentloaded") -> str:
    """Open ``url`` unless that would enter checkout. Return the checkout URL or ''.

    A navigation the browser cancels is tried once more. A probe that cannot
    reach the host still lets the browser open the page. An address that is
    already checkout is not opened.
    """
    def once() -> str:
        try:
            blocked = opens_checkout(page.request.get, url, timeout=timeout)
        except Exception:
            from .swarm import is_payment_url
            if is_payment_url(url):
                return url
            _response, landed = navigate_for_crawl(
                page, url, timeout=timeout, wait_until=wait_until)
            return landed or ""
        if blocked:
            return blocked
        page.goto(url, wait_until=wait_until, timeout=timeout)
        return ""

    try:
        return once()
    except Exception as exc:
        if not _CANCELLED.search(str(exc)):
            raise
        return once()


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
