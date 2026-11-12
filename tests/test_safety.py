"""Safety rules: approved scope, private network / metadata blocking, redaction, encrypted account storage."""
import json
import sys

import pytest

from backend.safety import REDACTED, Scope, UrlError, check_target, clean_env, is_metadata_host, redact


def test_only_http_websites_can_be_tested():
    assert check_target("https://shop.test/login", resolve=False) == "https://shop.test/login"
    for bad in ("ftp://shop.test", "file:///C:/Windows", "javascript:alert(1)", "shop.test"):
        with pytest.raises(UrlError):
            check_target(bad, resolve=False)


def test_credentials_in_the_address_and_metadata_are_refused():
    with pytest.raises(UrlError, match="password"):
        check_target("https://admin:secret@shop.test/", resolve=False)
    for meta in ("http://169.254.169.254/latest/meta-data", "http://metadata.google.internal/", "http://[fd00:ec2::254]/"):
        with pytest.raises(UrlError, match="metadata"):
            check_target(meta, resolve=False)
    with pytest.raises(UrlError, match="metadata"):
        check_target("http://[::ffff:169.254.169.254]/", resolve=False)


def test_public_website_cannot_reach_private_network():
    s = Scope("https://shop.test/", ["auth.shop.test", "*.cdn.test"])
    assert s.navigation_blocked("https://shop.test/cart") is None
    assert s.navigation_blocked("https://auth.shop.test/login") is None          # ALLOWED_HOSTS
    assert s.navigation_blocked("https://img.cdn.test/x") is None                # wildcard
    assert "outside the approved scope" in s.navigation_blocked("https://evil.test/")
    assert "ALLOWED_HOSTS" in s.navigation_blocked("https://evil.test/")
    assert s.blocked("https://www.google-analytics.com/collect") is None         # other sites' files are fine
    for private in ("http://127.0.0.1:8000/api/runs", "http://localhost/", "http://192.168.1.1/", "http://10.0.0.5/",
                    "http://[::1]/"):
        assert "private" in s.blocked(private), private
    assert "metadata" in s.blocked("http://169.254.169.254/latest/meta-data")
    assert "server secrets" in s.blocked("http://169.254.169.254/")


def test_local_target_may_use_local_addresses_but_never_metadata():
    s = Scope("http://localhost:3000/")
    assert s.blocked("http://127.0.0.1:5173/@vite/client") is None   # a local dev app's own server
    assert "metadata" in s.blocked("http://169.254.169.254/")
    assert "metadata" in s.blocked("http://[::ffff:169.254.169.254]/")  # IPv4-mapped metadata
    assert "metadata" in s.blocked("http://metadata.google.internal/")
    assert is_metadata_host("::ffff:169.254.169.254")
    assert s.navigation_blocked("http://localhost:3000/about") is None
    assert "outside the approved scope" in s.navigation_blocked("https://example.org/")


def test_redaction_hides_secrets_everywhere(monkeypatch):
    monkeypatch.setenv("TEST_PASSWORD", "Sup3r$ecret!")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaFAKEKEY1234567890")
    text = "login with Sup3r$ecret! failed; key=AIzaFAKEKEY1234567890; https://bob:pw123@site.test/x"
    out = redact(text)
    assert "Sup3r$ecret!" not in out and "AIzaFAKEKEY" not in out and "pw123" not in out
    assert out.count(REDACTED) == 3
    monkeypatch.setenv("TEST_USERNAME", "qa.user@example.com")
    assert "qa.user@example.com" in redact("user qa.user@example.com")            # reports may name the account
    assert "qa.user@example.com" not in redact("user qa.user@example.com", include_username=True)  # AI requests: no


def test_blowai_secret_and_contract_input_values_are_redacted(monkeypatch):
    """BLOWAI_SECRET_* and ANDROID_CONTRACT_INPUTS must never leak into logs/reports."""
    monkeypatch.setenv("BLOWAI_SECRET_DEMO_PASSWORD", "contract-pw-never-print")
    monkeypatch.setenv("ANDROID_CONTRACT_INPUTS", json.dumps({
        "secrets": {"BLOWAI_SECRET_INLINE": "inline-contract-secret-zz"},
        "databases": {},
    }))
    text = "used contract-pw-never-print and inline-contract-secret-zz"
    out = redact(text)
    assert "contract-pw-never-print" not in out
    assert "inline-contract-secret-zz" not in out
    assert out.count(REDACTED) == 2
    cleaned = clean_env({"PATH": "x", "BLOWAI_SECRET_DEMO_PASSWORD": "contract-pw-never-print",
                         "ANDROID_CONTRACT_INPUTS": "{}", "BLOWAI_DB_SHOP": "x.db"})
    assert cleaned == {"PATH": "x"}


def test_generated_tests_and_started_apps_get_no_api_keys():
    env = {"PATH": "x", "GEMINI_API_KEY": "k", "OPENAI_API_KEY": "k", "GITHUB_TOKEN": "t",
           "TEST_USERNAME": "u", "TEST_PASSWORD": "p"}
    assert clean_env(env) == {"PATH": "x"}
    assert clean_env(env, keep_test_account=True) == {"PATH": "x", "TEST_USERNAME": "u", "TEST_PASSWORD": "p"}


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_created_account_password_is_encrypted_on_disk(tmp_path):
    from backend.secret_store import load_account, save_account
    f = save_account("shop.test", {"username": "agentic.qa.1@example.com", "password": "Qa@123456x9Z"}, tmp_path)
    raw = f.read_text(encoding="utf-8")
    assert "Qa@123456x9Z" not in raw and '"protection": "dpapi"' in raw
    assert load_account("shop.test", tmp_path)["password"] == "Qa@123456x9Z"


def test_duplicate_addresses_are_one_page():
    from backend.agents.discovery import _no_index, _normalize, _same_site, _skip_reason
    assert _normalize("https://s.test/about?utm_source=news&utm_medium=mail") == "https://s.test/about"
    assert _normalize("https://s.test/about/#team") == "https://s.test/about"
    assert _normalize("https://s.test/item?id=5&gclid=abc") == "https://s.test/item?id=5"
    page = "https://s.test/index.php?rt=product/category&path=68"
    assert _normalize(page + "&currency=EUR") == _normalize(page) == page  # the same page in euros: read once
    assert _normalize("https://s.test/?utm_source=x&q=a%20b") == "https://s.test/?q=a%20b"  # (kept as written)
    assert _normalize("https://s.test/app/#/cart") == "https://s.test/app#/cart"   # a single-page-app route stays
    assert _no_index("https://s.test/index.html") == "https://s.test"              # a folder's index file = the folder
    assert _no_index("https://s.test/shop/default.aspx?x=1") == "https://s.test/shop?x=1"
    assert _no_index("https://s.test/indexes.html") == "https://s.test/indexes.html"
    assert _same_site("example.com", "www.example.com") and not _same_site("example.com", "example.org")
    assert "change data" in _skip_reason("https://s.test/account/delete")
    assert "file" in _skip_reason("https://s.test/manual.pdf")
