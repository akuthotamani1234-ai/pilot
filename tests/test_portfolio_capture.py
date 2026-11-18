"""Gate F: portfolio evidence is captured from discovery app_map fields."""
from backend.portfolio_capture import capture_portfolios
from backend.portfolio_gates import evaluate_portfolios


def test_capture_writes_a11y_perf_and_security(tmp_path):
    app_map = [
        {
            "url": "https://shop.test/",
            "final_url": "https://shop.test/",
            "load_time_ms": 800,
            "inputs": [{"name": "q", "label": "Search", "selector": "#q"},
                       {"name": "email", "label": "", "selector": "#email"}],
            "buttons": [{"selector": "#icon", "named": False}],
            "imageAlts": [
                {"src": "http://shop.test/hero.png", "alt": "", "missing_alt_attr": False},
                {"src": "http://shop.test/logo.png", "alt": "Shop", "missing_alt_attr": False},
            ],
            "brokenImages": ["http://shop.test/missing.png"],
            "response_headers": {
                "content-security-policy": "default-src 'self'",
                "x-content-type-options": "nosniff",
            },
        },
        {"url": "https://shop.test/cart", "load_time_ms": 1200, "inputs": [], "buttons": []},
    ]
    out = capture_portfolios(
        tmp_path, app_map, source_url="https://shop.test/", crawl={"mobile_check": True})
    assert (tmp_path / "a11y_page.json").is_file()
    assert (tmp_path / "performance.json").is_file()
    assert (tmp_path / "security_headers.json").is_file()
    assert (tmp_path / "compatibility.json").is_file()
    assert out["performance"]["load_ms"] == 1200
    assert out["security_headers"]["https"] is True
    assert out["compatibility"]["mobile"] == 2
    portfolios = evaluate_portfolios(
        a11y_page=out["a11y_page"],
        visual_report={"changed": [], "same": ["home"]},
        timings=out["performance"],
        locale_observed={"language": "en", "currency": "USD", "date_format": "MDY", "tax": "0", "offered": True},
        locale_expected={"language": "en", "currency": "USD", "date_format": "MDY", "tax": "0", "offered": True},
        security_headers=out["security_headers"]["headers"],
        https=out["security_headers"]["https"],
        compatibility_matrix=out["compatibility"],
    )
    assert "a11y" in portfolios["failed"]  # unlabeled email + missing alts
    assert "performance" in portfolios["passed"]
    assert "security" in portfolios["failed"]  # missing HSTS
    assert "compatibility" in portfolios["passed"]
