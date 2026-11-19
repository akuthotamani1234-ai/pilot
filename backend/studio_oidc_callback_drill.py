"""Gate I: Studio OIDC callback via loopback auth-code IdP.

Spins the loopback authorization-code issuer, obtains a code, and runs
``studio_oidc_callback.exchange_code``. Hosted IdP still open.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "studio_oidc_callback_drill.json"


def _linked_oidc() -> dict:
    return {
        "gate_i_complete": False,
        "ok": False,
        "drill": "studio_oidc_callback",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_studio_oidc_callback_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / "studio_oidc_callback_drill.json"):
        return _linked_oidc()

    try:
        import jwt  # noqa: F401
    except ImportError:
        evidence = {
            "gate_i_complete": False,
            "drill": "studio_oidc_callback",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "reason": "PyJWT not installed",
        }
        if not _write(evidence, ops_dir):
            return _linked_oidc()
        return evidence

    import secrets
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import jwt as pyjwt

    from .loopback_auth_code_sso_drill import _jwk_from_public, _mint_rsa_material
    from .studio_oidc_callback import exchange_code

    private_pem, public_key = _mint_rsa_material()
    kid = "qpilot-callback-1"
    sub = "studio-callback-user"
    email = "studio-callback@example.test"
    audience = "qpilot-studio"
    client_id = "qpilot-studio-client"
    codes: dict[str, dict] = {}
    probe = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = probe.server_address[1]
    probe.server_close()
    issuer = f"http://127.0.0.1:{port}"
    jwks = {"keys": [_jwk_from_public(public_key, kid)]}
    discovery = {
        "issuer": issuer,
        "jwks_uri": f"{issuer}/.well-known/jwks.json",
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_a):
            return

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path.endswith("openid-configuration"):
                body = json.dumps(discovery).encode()
            elif parsed.path.endswith("jwks.json"):
                body = json.dumps(jwks).encode()
            elif parsed.path == "/authorize":
                qs = urllib.parse.parse_qs(parsed.query)
                redirect = (qs.get("redirect_uri") or ["http://127.0.0.1/studio/callback"])[0]
                state = (qs.get("state") or [""])[0]
                code = secrets.token_urlsafe(12)
                codes[code] = {"sub": sub, "email": email}
                loc = f"{redirect}?code={urllib.parse.quote(code)}&state={urllib.parse.quote(state)}"
                self.send_response(302)
                self.send_header("Location", loc)
                self.end_headers()
                return
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if urllib.parse.urlparse(self.path).path != "/token":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length") or 0)
            form = urllib.parse.parse_qs(self.rfile.read(length).decode() if length else "")
            code = (form.get("code") or [""])[0]
            entry = codes.pop(code, None)
            if not entry:
                body = b'{"error":"invalid_grant"}'
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            now = int(time.time())
            claims = {
                "iss": issuer, "aud": audience, "sub": entry["sub"],
                "email": entry["email"], "exp": now + 600, "iat": now,
            }
            token = pyjwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": kid})
            body = json.dumps({
                "access_token": token, "id_token": token,
                "token_type": "Bearer", "expires_in": 600,
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    prev = {k: os.environ.get(k) for k in (
        "QPILOT_OIDC_ISSUER", "QPILOT_OIDC_AUDIENCE", "QPILOT_OIDC_CLIENT_ID",
        "QPILOT_OIDC_TOKEN_URL", "QPILOT_OIDC_REDIRECT_URI",
    )}
    os.environ["QPILOT_OIDC_ISSUER"] = issuer
    os.environ["QPILOT_OIDC_AUDIENCE"] = audience
    os.environ["QPILOT_OIDC_CLIENT_ID"] = client_id
    os.environ["QPILOT_OIDC_TOKEN_URL"] = f"{issuer}/token"
    os.environ["QPILOT_OIDC_REDIRECT_URI"] = "http://127.0.0.1/studio/callback"
    try:
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(_NoRedirect)
        auth_url = (
            f"{issuer}/authorize?response_type=code&client_id={client_id}"
            f"&redirect_uri={urllib.parse.quote('http://127.0.0.1/studio/callback')}"
            f"&state=studio-1"
        )
        code = ""
        try:
            opener.open(auth_url, timeout=5)
        except urllib.error.HTTPError as exc:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(exc.headers.get("Location") or "").query)
            code = (qs.get("code") or [""])[0]
        result = exchange_code(code=code, client_id=client_id)
        evidence = {
            "gate_i_complete": False,
            "drill": "studio_oidc_callback",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "callback": {
                "ok": bool(result.get("ok")),
                "signature_verified": bool(result.get("signature_verified")),
                "sub": (result.get("claims") or {}).get("sub"),
                "reason": result.get("reason"),
            },
            "ok": bool(result.get("ok")) and bool(result.get("signature_verified")),
            "reason": (
                "Studio OIDC callback exchanged loopback auth-code + verified JWT; "
                "hosted IdP Studio SSO still open"
                if result.get("ok") else
                "Studio OIDC callback drill failed; hosted IdP still open"
            ),
        }
    finally:
        server.shutdown()
        server.server_close()
        for key, val in prev.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
    if not _write(evidence, ops_dir):
        return _linked_oidc()
    return evidence


def _write(evidence: dict, ops_dir: Path | None) -> bool:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "studio_oidc_callback_drill.json"
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return False
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return False
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return True
