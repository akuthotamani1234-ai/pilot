"""Loopback authorization-code grant checks."""
from backend.oidc_auth_code_grant import authorization_code_grant_error


def _entry(**extra):
    row = {
        "client_id": "qpilot-studio",
        "redirect_uri": "http://127.0.0.1/studio/callback",
        "issued_at": 1_000.0,
    }
    row.update(extra)
    return row


def test_matching_grant_is_allowed():
    assert authorization_code_grant_error(
        _entry(),
        grant="authorization_code",
        client_id="qpilot-studio",
        redirect_uri="http://127.0.0.1/studio/callback",
        now=1_010.0,
    ) == ""


def test_wrong_client_redirect_and_expiry_are_refused():
    base = {
        "grant": "authorization_code",
        "client_id": "qpilot-studio",
        "redirect_uri": "http://127.0.0.1/studio/callback",
        "now": 1_010.0,
    }
    assert authorization_code_grant_error(_entry(), **{**base, "client_id": "other"})
    assert authorization_code_grant_error(
        _entry(), **{**base, "redirect_uri": "http://127.0.0.1/evil/callback"},
    )
    assert authorization_code_grant_error(_entry(), **{**base, "now": 1_000.0 + 121})
    assert authorization_code_grant_error(_entry(issued_at=None), **base)
    assert authorization_code_grant_error(None, **base)
    assert authorization_code_grant_error(_entry(), **base, verifier_ok=False)
