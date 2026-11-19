"""Authorization-code grant checks for the loopback IdP.

A code is bound to the client and redirect URI that minted it, and it expires.
Hosted IdP Studio SSO stays open — this module does not set ``gate_i_complete``.
"""
from __future__ import annotations

CODE_MAX_AGE_S = 120


def authorization_code_grant_error(
    entry: dict | None,
    *,
    grant: str,
    client_id: str,
    redirect_uri: str,
    now: float,
    verifier_ok: bool = True,
    max_age_s: float = CODE_MAX_AGE_S,
) -> str:
    """Return ``invalid_grant`` when the token request must be refused, else ``""``."""
    if (grant or "") != "authorization_code" or not entry:
        return "invalid_grant"
    if (client_id or "") != (entry.get("client_id") or ""):
        return "invalid_grant"
    if (redirect_uri or "") != (entry.get("redirect_uri") or ""):
        return "invalid_grant"
    issued = entry.get("issued_at")
    if isinstance(issued, bool) or not isinstance(issued, (int, float)):
        return "invalid_grant"
    if float(now) - float(issued) > max_age_s:
        return "invalid_grant"
    if not verifier_ok:
        return "invalid_grant"
    return ""
