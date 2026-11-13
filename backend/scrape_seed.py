"""Non-MCP HTTP scrape seeder: same-host URL harvest for the discovery frontier.

GET-only. Never POSTs. Drops real checkout/payment paths so those stay blocked by design.
Feeds `found_by=scrape` into discovery — complementary to the built-in Playwright observe loop.
"""
from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urljoin, urlparse, urldefrag

# Payment/checkout paths we never seed (exploration still must not queue these as must-complete work).
PAY_CHECKOUT_PATH = re.compile(
    r"(^|/)(checkout|check-out|payment|payments|billing|pay-now|place-order|cart/checkout)(/|\?|$)|"
    r"[?&](checkout|payment)=",
    re.I,
)
SITEMAP_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
HREF = re.compile(r"""(?:href|src)\s*=\s*["']([^"'#]+)["']""", re.I)
JSON_PATHISH = re.compile(r"""["'](https?://[^"'\\]+|/[\w./\-?=&%]+)["']""")
OPENAPI_HINTS = (
    "/openapi.json", "/swagger.json", "/v2/api-docs", "/v3/api-docs", "/api-docs",
)


def is_pay_checkout_url(url: str) -> bool:
    """True when the URL looks like a checkout/payment destination (never seed)."""
    try:
        p = urlparse(url)
    except Exception:
        return True
    blob = f"{p.path}?{p.query}".rstrip("?")
    return bool(PAY_CHECKOUT_PATH.search(blob))


def _same_host(url: str, host: str) -> bool:
    try:
        h = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return bool(h) and h == host.lower()


def _normalize(url: str, base: str) -> str | None:
    if not url or url.startswith(("mailto:", "tel:", "javascript:", "data:")):
        return None
    abs_u = urljoin(base, unescape(url.strip()))
    abs_u, _ = urldefrag(abs_u)
    if abs_u.startswith("//"):
        abs_u = f"{urlparse(base).scheme}:{abs_u}"
    if not abs_u.startswith(("http://", "https://")):
        return None
    return abs_u


def _get_text(fetcher, url: str, timeout_ms: int = 15000) -> str:
    """fetcher: callable(url) -> text, or Playwright APIRequestContext-like with .get."""
    if callable(fetcher) and not hasattr(fetcher, "get"):
        return fetcher(url) or ""
    r = fetcher.get(url, timeout=timeout_ms)
    ok = getattr(r, "ok", None)
    if ok is False:
        return ""
    status = getattr(r, "status", 200)
    if callable(status):
        status = status()
    if int(status or 0) >= 400:
        return ""
    text = getattr(r, "text", None)
    return text() if callable(text) else (text or "")


def harvest_sitemaps(fetcher, start_url: str, *, limit: int = 50000, max_sitemaps: int = 40) -> list[str]:
    """robots.txt Sitemap: lines + /sitemap.xml indexes (more than the old 10-file cap)."""
    base = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
    host = urlparse(start_url).hostname or ""
    todo, done, out = [f"{base}/sitemap.xml"], set(), []
    try:
        robots = _get_text(fetcher, f"{base}/robots.txt", timeout_ms=10000)
        for line in robots.splitlines():
            if line.lower().startswith("sitemap:"):
                todo.insert(0, line.split(":", 1)[1].strip())
    except Exception:
        pass
    while todo and len(done) < max_sitemaps and len(out) < limit:
        sm = todo.pop(0)
        if sm in done or not _same_host(sm, host):
            continue
        done.add(sm)
        try:
            body = _get_text(fetcher, sm, timeout_ms=15000)
        except Exception:
            continue
        if not body:
            continue
        for encoded in SITEMAP_LOC.findall(body):
            loc = unescape(encoded)
            if loc.lower().endswith((".xml", ".xml.gz")) and "<sitemapindex" in body.lower():
                todo.append(loc)
            else:
                out.append(loc)
    return list(dict.fromkeys(out))[:limit]


def harvest_html_links(html: str, base_url: str) -> list[str]:
    out = []
    for raw in HREF.findall(html or ""):
        u = _normalize(raw, base_url)
        if u:
            out.append(u)
    return out


def harvest_json_paths(text: str, base_url: str) -> list[str]:
    out = []
    for raw in JSON_PATHISH.findall(text or ""):
        u = _normalize(raw, base_url)
        if u:
            out.append(u)
    for m in re.finditer(r"__NEXT_DATA__\s*=\s*(\{.*?\})\s*;?\s*</script>", text or "", re.I | re.S):
        try:
            blob = json.dumps(json.loads(m.group(1)))
        except Exception:
            blob = m.group(1)
        for raw in JSON_PATHISH.findall(blob):
            u = _normalize(raw, base_url)
            if u:
                out.append(u)
    return out


def harvest_openapi_paths(fetcher, start_url: str) -> list[str]:
    base = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
    host = urlparse(start_url).hostname or ""
    out = []
    for hint in OPENAPI_HINTS:
        try:
            body = _get_text(fetcher, urljoin(base, hint), timeout_ms=10000)
        except Exception:
            continue
        if not body or body.lstrip()[:1] not in ("{", "["):
            continue
        try:
            data = json.loads(body)
        except Exception:
            continue
        paths = data.get("paths") if isinstance(data, dict) else None
        if isinstance(paths, dict):
            for path in paths:
                if isinstance(path, str) and path.startswith("/"):
                    u = _normalize(path, base)
                    if u and _same_host(u, host):
                        out.append(u)
    return out


def seed_urls(fetcher, start_url: str, *, html: str | None = None, limit: int = 50000) -> list[str]:
    """Union of sitemap + optional start HTML + openapi hints; same-host; no pay/checkout."""
    host = urlparse(start_url).hostname or ""
    found: list[str] = []
    found.extend(harvest_sitemaps(fetcher, start_url, limit=limit))
    if html:
        found.extend(harvest_html_links(html, start_url))
        found.extend(harvest_json_paths(html, start_url))
    found.extend(harvest_openapi_paths(fetcher, start_url))
    out = []
    seen = set()
    for u in found:
        if u in seen or not _same_host(u, host) or is_pay_checkout_url(u):
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= limit:
            break
    return out
