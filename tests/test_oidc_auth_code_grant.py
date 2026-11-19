"""Loopback authorization-code grant checks."""
from backend.oidc_auth_code_grant import (
    authorization_code_grant_error,
    redirect_uri_registered,
)


def _entry(**extra):
    row = {
        "client_id": "qpilot-studio",
        "redirect_uri": "http://127.0.0.1/studio/callback",
        "issued_at": 1_000.0,
    }
    row.update(extra)
    return row


def test_authorize_redirect_must_be_registered():
    assert redirect_uri_registered("http://127.0.0.1/studio/callback") is True
    assert redirect_uri_registered("http://127.0.0.1/evil/callback") is False
    assert redirect_uri_registered("") is False


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


def test_a_code_minted_with_state_is_refused_when_the_token_state_differs():
    base = {
        "grant": "authorization_code",
        "client_id": "qpilot-studio",
        "redirect_uri": "http://127.0.0.1/studio/callback",
        "now": 1_010.0,
    }
    bound = _entry(state="studio-sso-1")
    assert authorization_code_grant_error(bound, **base, state="studio-sso-1") == ""
    assert authorization_code_grant_error(bound, **base, state="other-browser") == "invalid_grant"
    assert authorization_code_grant_error(bound, **base) == "invalid_grant"


def test_an_id_token_copies_the_login_nonce_and_omits_it_when_none_was_sent():
    from backend.oidc_auth_code_grant import login_nonce_claim

    assert login_nonce_claim({"nonce": "studio-nonce-1"}) == {"nonce": "studio-nonce-1"}
    assert login_nonce_claim({"nonce": ""}) == {}
    assert login_nonce_claim(None) == {}
