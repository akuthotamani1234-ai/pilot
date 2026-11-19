"""Gate I: loopback OIDC issuer + signed JWT validation drill.

Spins a local JWKS/OIDC discovery HTTP server, mints an RS256 JWT, and runs
``oidc_jwt.validate_bearer`` with signature verification. Hosted IdP / Studio
login still open — ``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "loopback_sso_drill.json"


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


@contextmanager
def loopback_oidc_session(
    *,
    sub: str = "loopback-user-1",
    email: str = "loopback@example.test",
    audience: str = "qpilot-loopback",
    extra_claims: dict | None = None,
    exp_offset_seconds: int = 600,
):
    """Yield ``{token, issuer, audience, claims, validate}`` while JWKS is live.

    ``exp_offset_seconds`` is added to ``iat`` for ``exp`` (use a negative value
    to mint an already-expired token).
    """
    import jwt

    private_pem, public_key = _mint_rsa_material()
    kid = "qpilot-loopback-1"
    probe = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = probe.server_address[1]
    probe.server_close()
    issuer = f"http://127.0.0.1:{port}"
    jwks = {"keys": [_jwk_from_public(public_key, kid)]}
    discovery = {
        "issuer": issuer,
        "jwks_uri": f"{issuer}/.well-known/jwks.json",
        "response_types_supported": ["id_token"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }
    body_disc = json.dumps(discovery).encode()
    body_jwks = json.dumps(jwks).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_GET(self):
            if self.path.endswith("/.well-known/openid-configuration"):
                payload = body_disc
            elif self.path.endswith("/.well-known/jwks.json"):
                payload = body_jwks
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    prev = {
        "QPILOT_OIDC_ISSUER": os.environ.get("QPILOT_OIDC_ISSUER"),
        "QPILOT_OIDC_AUDIENCE": os.environ.get("QPILOT_OIDC_AUDIENCE"),
        "QPILOT_OIDC_CLIENT_ID": os.environ.get("QPILOT_OIDC_CLIENT_ID"),
    }
    os.environ["QPILOT_OIDC_ISSUER"] = issuer
    os.environ["QPILOT_OIDC_AUDIENCE"] = audience
    os.environ["QPILOT_OIDC_CLIENT_ID"] = "qpilot-loopback-client"
    try:
        now = int(time.time())
        claims = {
            "iss": issuer,
            "aud": audience,
            "sub": sub,
            "email": email,
            "exp": now + int(exp_offset_seconds),
            "iat": now,
        }
        if extra_claims:
            claims.update(extra_claims)
        token = jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": kid})
        from .oidc_jwt import validate_bearer

        result = validate_bearer(token, verify_signature=True)
        yield {
            "token": token,
            "issuer": issuer,
            "audience": audience,
            "claims": claims,
            "validate": result,
        }
    finally:
        server.shutdown()
        thread.join(timeout=2)
        for key, val in prev.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


def run_loopback_sso_drill(*, ops_dir: Path | None = None) -> dict:
    try:
        import jwt  # noqa: F401
    except ImportError:
        evidence = {
            "gate_i_complete": False,
            "drill": "loopback_oidc_jwt",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "reason": "PyJWT not installed — cannot mint/verify loopback SSO JWT",
        }
    else:
        with loopback_oidc_session() as session:
            result = session["validate"]
            evidence = {
                "gate_i_complete": False,
                "drill": "loopback_oidc_jwt",
                "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "issuer": session["issuer"],
                "audience": session["audience"],
                "signature_verified": bool(result.get("signature_verified")),
                "validate": {
                    "ok": bool(result.get("ok")),
                    "reason": result.get("reason"),
                    "claims": result.get("claims") or {},
                },
                "ok": bool(result.get("ok")) and bool(result.get("signature_verified")),
                "reason": (
                    "Loopback OIDC JWKS + RS256 JWT signature verified; "
                    "hosted IdP / Studio SSO login still open"
                    if result.get("signature_verified")
                    else (
                        f"Loopback OIDC exercised but signature incomplete: "
                        f"{result.get('reason')}; hosted IdP SSO still open"
                    )
                ),
            }

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "loopback_sso_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "loopback_sso_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
