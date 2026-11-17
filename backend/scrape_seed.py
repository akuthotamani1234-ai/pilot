"""Non-MCP HTTP scrape seeder: same-host URL harvest for the discovery frontier.

GET-only. Never POSTs. Drops real checkout/payment paths so those stay blocked by design.
Feeds `found_by=scrape` into discovery — complementary to the built-in Playwright observe loop.
"""
from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urldefrag, urljoin, urlparse

from .swarm import is_payment_url

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


def harvest_json_paths(text: str, base_url: str, *, embedded_only: bool = False) -> list[str]:
    """Pull path-like strings from JSON. Default: full text. embedded_only: __NEXT_DATA__ only
    (avoids treating history.pushState('/spa-route') strings as scrape seeds)."""
    out = []
    if not embedded_only:
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


_API_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")


def _openapi_documents(fetcher, start_url: str) -> list[dict]:
    """The OpenAPI or Swagger documents harvest_openapi_paths already downloads."""
    base = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
    found: list[dict] = []
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
            found.append(data)
    return found


def harvest_openapi_paths(fetcher, start_url: str) -> list[str]:
    base = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
    host = urlparse(start_url).hostname or ""
    out = []
    for data in _openapi_documents(fetcher, start_url):
        for path in data.get("paths") or {}:
            if isinstance(path, str) and path.startswith("/"):
                u = _normalize(path, base)
                if u and _same_host(u, host):
                    out.append(u)
    return out


def _skip_api_path(path: str) -> bool:
    """Checkout and payment operations are not part of the spec the crawl keeps."""
    full = path if "://" in path else f"https://api.local{path if path.startswith('/') else '/' + path}"
    return is_pay_checkout_url(full) or is_payment_url(full)


def _resolve_ref(ref: str, doc: dict) -> dict:
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return {}
    node: object = doc
    for part in ref[2:].split("/"):
        if not isinstance(node, dict):
            return {}
        node = node.get(part)
    return node if isinstance(node, dict) else {}


def _schema_fields(schema: object, doc: dict, seen: set[str] | None = None) -> list[str]:
    """Response property names, in the order the document lists them."""
    if not isinstance(schema, dict):
        return []
    seen = seen or set()
    ref = schema.get("$ref")
    if isinstance(ref, str):
        if ref in seen:
            return []
        seen.add(ref)
        return _schema_fields(_resolve_ref(ref, doc), doc, seen)
    fields: list[str] = []
    props = schema.get("properties")
    if isinstance(props, dict):
        fields.extend(str(name) for name in props)
    for key in ("allOf", "oneOf", "anyOf"):
        for part in schema.get(key) or []:
            for name in _schema_fields(part, doc, seen):
                if name not in fields:
                    fields.append(name)
    if not fields and isinstance(schema.get("items"), dict):
        for name in _schema_fields(schema["items"], doc, seen):
            if name not in fields:
                fields.append(name)
    return fields


def _response_schema(response: dict) -> dict | None:
    if isinstance(response.get("schema"), dict):  # Swagger 2
        return response["schema"]
    content = response.get("content")
    if not isinstance(content, dict):
        return None
    preferred = content.get("application/json")
    if isinstance(preferred, dict) and isinstance(preferred.get("schema"), dict):
        return preferred["schema"]
    for body in content.values():
        if isinstance(body, dict) and isinstance(body.get("schema"), dict):
            return body["schema"]
    return None


def _success_schema(operation: dict) -> dict | None:
    responses = operation.get("responses")
    if not isinstance(responses, dict) or not responses:
        return None
    codes = [str(code) for code in responses if str(code).startswith("2")]
    chosen = sorted(codes, key=lambda code: (code != "200", code))[0] if codes else "default"
    body = responses.get(chosen)
    if not isinstance(body, dict) and chosen.isdigit():
        body = responses.get(int(chosen))
    if not isinstance(body, dict):
        return None
    return _response_schema(body)


def _workflow(operation: dict, path: str) -> str:
    tags = operation.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            text = str(tag).strip()
            if text:
                return text
    name = str(operation.get("operationId") or "").strip()
    if name:
        return name
    parts = [part for part in path.split("/") if part and not part.startswith("{")]
    return parts[-1] if parts else path


def _operations_from_doc(data: dict) -> list[dict]:
    paths = data.get("paths") if isinstance(data.get("paths"), dict) else {}
    found: list[dict] = []
    for path, item in paths.items():
        if not isinstance(path, str) or not isinstance(item, dict) or _skip_api_path(path):
            continue
        for method in _API_METHODS:
            operation = item.get(method)
            if not isinstance(operation, dict):
                continue
            schema = _success_schema(operation)
            found.append({
                "method": method.upper(),
                "path": path,
                "fields": _schema_fields(schema, data) if schema else [],
                "workflow": _workflow(operation, path),
            })
    return found


def harvest_openapi_operations(fetcher, start_url: str) -> list[dict] | None:
    """Operations from the same OpenAPI documents, without payment or checkout paths.

    None means no document was found, so the caller does not invent a spec.
    A document whose every path is payment or checkout returns an empty list.
    """
    docs = _openapi_documents(fetcher, start_url)
    if not docs:
        return None
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for data in docs:
        for operation in _operations_from_doc(data):
            key = (operation["method"], operation["path"])
            if key in seen:
                continue
            seen.add(key)
            found.append(operation)
    return found


def seed_entries(fetcher, start_url: str, *, html: str | None = None, limit: int = 50000) -> list[tuple[str, str]]:
    """Same-host seeds with provenance: sitemap vs scrape (HTML/openapi). No pay/checkout."""
    host = urlparse(start_url).hostname or ""
    tagged: list[tuple[str, str]] = []
    for u in harvest_sitemaps(fetcher, start_url, limit=limit):
        tagged.append((u, "sitemap"))
    if html:
        # Real <a href> plus __NEXT_DATA__ only — not every quoted path in inline scripts (SPA history).
        for u in harvest_html_links(html, start_url) + harvest_json_paths(html, start_url, embedded_only=True):
            tagged.append((u, "scrape"))
    for u in harvest_openapi_paths(fetcher, start_url):
        tagged.append((u, "scrape"))
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for u, how in tagged:
        if u in seen or not _same_host(u, host) or is_pay_checkout_url(u):
            continue
        seen.add(u)
        out.append((u, how))
        if len(out) >= limit:
            break
    return out


def seed_urls(fetcher, start_url: str, *, html: str | None = None, limit: int = 50000) -> list[str]:
    """Union of sitemap + HTML + openapi hints; same-host; no pay/checkout."""
    return [u for u, _how in seed_entries(fetcher, start_url, html=html, limit=limit)]
