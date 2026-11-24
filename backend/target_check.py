"""Can the website under test be opened? One GET before a run, classified so a person knows what to fix.

  ok              the site answered (2xx/3xx, or 401/403 for a site that needs a login: reachable)
  invalid         not an http(s) address, a user name / password in it, or a cloud metadata address (safety.check_target)
  dns             the name does not resolve
  tls             the certificate or TLS handshake failed
  timeout         no answer in time
  connection      refused / reset / unreachable
  unavailable     the site answered 5xx (an availability problem, never a functional test failure)
  not_found       404 on the address given
Redirects are followed only on the same host (at most 5). Nothing is sent but a plain GET; no credentials.
"""
from __future__ import annotations

import socket
from urllib.parse import urljoin, urlparse

import requests

from .safety import UrlError, check_target

HINTS = {"dns": "The website name could not be found. Check the address for typos.",
         "tls": "The site's security certificate was refused. Check the address (https) or the site's certificate.",
         "timeout": "The site did not answer in time. Try again, or check that it is running.",
         "connection": "The connection was refused or dropped. Check that the site is running and reachable.",
         "unavailable": "The site answered with a server error. It is an availability problem, not a test result.",
         "not_found": "The site answered 'not found' for this address. Check the path.",
         "invalid": "This is not a website address Qpilot can test."}


def check(url: str, timeout: float = 10.0, session: requests.Session | None = None) -> dict:
    try:
        url = check_target(url)
    except UrlError as error:
        return {"ok": False, "kind": "invalid", "message": str(error), "url": url}
    s = session or requests.Session()
    host = urlparse(url).hostname
    current = url
    for _ in range(6):
        try:
            r = s.get(current, timeout=timeout, allow_redirects=False, stream=True,
                      headers={"User-Agent": "Qpilot-TargetCheck/1"})
            r.close()
        except requests.exceptions.SSLError:
            return _bad("tls", url)
        except requests.exceptions.Timeout:
            return _bad("timeout", url)
        except requests.exceptions.ConnectionError as error:
            text = str(error)
            if isinstance(getattr(error, "__context__", None), socket.gaierror) or "Name or service not known" in text \
                    or "nodename nor servname" in text or "getaddrinfo failed" in text or "NameResolution" in text:
                return _bad("dns", url)
            return _bad("connection", url)
        except requests.RequestException:
            return _bad("connection", url)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            nxt = urljoin(current, r.headers["Location"])
            if urlparse(nxt).hostname != host:
                return {"ok": True, "kind": "ok", "status": r.status_code, "url": url,
                        "message": f"The site answered and redirects to another host ({urlparse(nxt).hostname})."}
            current = nxt
            continue
        if r.status_code >= 500:
            return _bad("unavailable", url, r.status_code)
        if r.status_code == 404:
            return _bad("not_found", url, 404)
        return {"ok": True, "kind": "ok", "status": r.status_code, "url": url,
                "message": "The site answered" + (" (it asks for a login)" if r.status_code in (401, 403) else "") + "."}
    return {"ok": True, "kind": "ok", "url": url, "message": "The site answered (many redirects)."}


def _bad(kind: str, url: str, status: int | None = None) -> dict:
    return {"ok": False, "kind": kind, "status": status, "url": url, "message": HINTS[kind]}
