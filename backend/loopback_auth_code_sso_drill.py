"""Gate I: loopback OIDC authorization-code → Studio bearer drill.

Local IdP serves discovery/JWKS plus ``/authorize`` (issues a one-time code)
and ``/token`` (exchanges code for RS256 JWT). Client completes the code flow,
validates the JWT, and authorizes dashboard ``oidc`` mode. Hosted IdP Studio
SSO login still open — ``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .oidc_auth_code_grant import authorization_code_grant_error

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "loopback_auth_code_sso_drill.json"


def _mint_rsa_material():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return private_pem, key.public_key()


def _jwk_from_public(public_key, kid: str) -> dict:
    import jwt

    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(public_key)
    data = json.loads(jwk) if isinstance(jwk, str) else dict(jwk)
    data["kid"] = kid
    data["use"] = "sig"
    data["alg"] = "RS256"
    return data


def run_loopback_auth_code_sso_drill(*, ops_dir: Path | None = None) -> dict:
    try:
        import jwt
    except ImportError:
        evidence = {
            "gate_i_complete": False,
            "drill": "loopback_auth_code_sso",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "reason": "PyJWT not installed — cannot run auth-code SSO drill",
        }
        _write(evidence, ops_dir)
        return evidence

    from .dashboard_auth import authorize
    from .oidc_jwt import validate_bearer

    private_pem, public_key = _mint_rsa_material()
    kid = "qpilot-authcode-1"
    sub = "authcode-user-1"
    email = "authcode@example.test"
    audience = "qpilot-authcode"
    client_id = "qpilot-authcode-client"
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
        "response_types_supported": ["code", "id_token"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "grant_types_supported": ["authorization_code"],
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path.endswith("/.well-known/openid-configuration"):
                body = json.dumps(discovery).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path.endswith("/.well-known/jwks.json"):
                body = json.dumps(jwks).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/authorize":
                qs = urllib.parse.parse_qs(parsed.query)
                redirect = (qs.get("redirect_uri") or ["http://127.0.0.1/callback"])[0]
                state = (qs.get("state") or [""])[0]
                if (qs.get("client_id") or [""])[0] != client_id:
                    self.send_response(400)
                    self.end_headers()
                    return
                code = secrets.token_urlsafe(16)
                codes[code] = {
                    "sub": sub,
                    "email": email,
                    "client_id": client_id,
                    "redirect_uri": redirect,
                    "issued_at": time.time(),
                }
                loc = f"{redirect}?code={urllib.parse.quote(code)}&state={urllib.parse.quote(state)}"
                self.send_response(302)
                self.send_header("Location", loc)
                self.end_headers()
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/token":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            form = urllib.parse.parse_qs(raw.decode("utf-8"))
            code = (form.get("code") or [""])[0]
            grant = (form.get("grant_type") or [""])[0]
            redirect_uri = (form.get("redirect_uri") or [""])[0]
            posted_client = (form.get("client_id") or [""])[0]
            entry = codes.pop(code, None)
            error = authorization_code_grant_error(
                entry,
                grant=grant,
                client_id=posted_client,
                redirect_uri=redirect_uri,
                now=time.time(),
            )
            if error:
                body = json.dumps({"error": error}).encode()
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            now = int(time.time())
            claims = {
                "iss": issuer,
                "aud": audience,
                "sub": entry["sub"],
                "email": entry["email"],
                "exp": now + 600,
                "iat": now,
            }
            token = jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": kid})
            body = json.dumps({
                "access_token": token,
                "id_token": token,
                "token_type": "Bearer",
                "expires_in": 600,
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    prev = {
        "QPILOT_OIDC_ISSUER": os.environ.get("QPILOT_OIDC_ISSUER"),
        "QPILOT_OIDC_AUDIENCE": os.environ.get("QPILOT_OIDC_AUDIENCE"),
        "QPILOT_OIDC_CLIENT_ID": os.environ.get("QPILOT_OIDC_CLIENT_ID"),
        "QPILOT_DASHBOARD_AUTH": os.environ.get("QPILOT_DASHBOARD_AUTH"),
    }
    os.environ["QPILOT_OIDC_ISSUER"] = issuer
    os.environ["QPILOT_OIDC_AUDIENCE"] = audience
    os.environ["QPILOT_OIDC_CLIENT_ID"] = client_id
    os.environ["QPILOT_DASHBOARD_AUTH"] = "oidc"
    steps: list[dict] = []
    try:
        # 1) discovery (loopback issuer only)
        with urllib.request.urlopen(  # noqa: S310
            f"{issuer}/.well-known/openid-configuration", timeout=5
        ) as resp:
            disc = json.loads(resp.read().decode())
        steps.append({"step": "discovery", "ok": disc.get("issuer") == issuer})

        # 2) authorize → capture redirect Location code (do not follow 302)
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        auth_url = (
            f"{issuer}/authorize?response_type=code&client_id={client_id}"
            f"&redirect_uri={urllib.parse.quote('http://127.0.0.1/studio/callback')}"
            f"&state=studio-sso-1&scope=openid%20email"
        )
        opener = urllib.request.build_opener(_NoRedirect)
        code = ""
        try:
            opener.open(auth_url, timeout=5)
            steps.append({"step": "authorize", "ok": False, "detail": "expected 302"})
        except urllib.error.HTTPError as exc:
            loc = exc.headers.get("Location") or ""
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
            code = (qs.get("code") or [""])[0]
            steps.append({
                "step": "authorize",
                "ok": exc.code in {302, 303, 307} and bool(code),
                "http_status": exc.code,
            })

        # 3) a different redirect_uri must not redeem the code
        mismatch_code = ""
        try:
            opener.open(auth_url, timeout=5)
        except urllib.error.HTTPError as exc:
            loc = exc.headers.get("Location") or ""
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
            mismatch_code = (qs.get("code") or [""])[0]
        bad_form = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": mismatch_code,
            "client_id": client_id,
            "redirect_uri": "http://127.0.0.1/evil/callback",
        }).encode()
        bad_req = urllib.request.Request(  # noqa: S310
            f"{issuer}/token",
            data=bad_form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            urllib.request.urlopen(bad_req, timeout=5)  # noqa: S310
            steps.append({"step": "reject_redirect_mismatch", "ok": False})
        except urllib.error.HTTPError as exc:
            steps.append({
                "step": "reject_redirect_mismatch",
                "ok": exc.code == 400 and bool(mismatch_code),
            })

        client_code = ""
        try:
            opener.open(auth_url, timeout=5)
        except urllib.error.HTTPError as exc:
            loc = exc.headers.get("Location") or ""
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
            client_code = (qs.get("code") or [""])[0]
        client_form = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": client_code,
            "client_id": "not-the-studio-client",
            "redirect_uri": "http://127.0.0.1/studio/callback",
        }).encode()
        client_req = urllib.request.Request(  # noqa: S310
            f"{issuer}/token",
            data=client_form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            urllib.request.urlopen(client_req, timeout=5)  # noqa: S310
            steps.append({"step": "reject_client_mismatch", "ok": False})
        except urllib.error.HTTPError as exc:
            steps.append({
                "step": "reject_client_mismatch",
                "ok": exc.code == 400 and bool(client_code),
            })

        # 4) token exchange
        form = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": "http://127.0.0.1/studio/callback",
        }).encode()
        token_req = urllib.request.Request(  # noqa: S310
            f"{issuer}/token",
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(token_req, timeout=5) as resp:  # noqa: S310
            token_body = json.loads(resp.read().decode())
        access = token_body.get("access_token") or ""
        steps.append({"step": "token", "ok": bool(access)})

        # 5) validate + dashboard authorize
        validated = validate_bearer(access, verify_signature=True)
        authz = authorize(f"Bearer {access}", action="review.write")
        steps.append({
            "step": "validate_authorize",
            "ok": bool(validated.get("ok")) and bool(authz.get("ok")),
            "signature_verified": bool(
                validated.get("signature_verified") or authz.get("signature_verified")
            ),
        })
        ok = all(s.get("ok") for s in steps)
        evidence = {
            "gate_i_complete": False,
            "drill": "loopback_auth_code_sso",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "issuer": issuer,
            "client_id": client_id,
            "sub": sub,
            "steps": steps,
            "ok": ok,
            "reason": (
                "Loopback OIDC authorization-code → JWT → dashboard oidc ok; "
                "hosted IdP Studio SSO login still open"
                if ok else
                "Loopback auth-code SSO drill failed; hosted IdP still open"
            ),
        }
    except Exception as exc:
        evidence = {
            "gate_i_complete": False,
            "drill": "loopback_auth_code_sso",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "steps": steps,
            "reason": f"Auth-code SSO drill failed: {exc}; hosted IdP still open",
        }
    finally:
        server.shutdown()
        server.server_close()
        for key, val in prev.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val

    _write(evidence, ops_dir)
    return evidence


def _write(evidence: dict, ops_dir: Path | None) -> None:
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "loopback_auth_code_sso_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "loopback_auth_code_sso_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
