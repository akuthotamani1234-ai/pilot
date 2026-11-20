"""Gate F: portfolio evidence is captured from discovery app_map fields."""
from backend.portfolio_capture import capture_portfolios
from backend.portfolio_gates import evaluate_portfolios


def test_a_portfolio_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = b"tenant-b-only-portfolio"
    other = tmp_path / "other"
    nested = other / "run"
    nested.mkdir(parents=True)
    (nested / "keep.txt").write_bytes(secret)
    (nested / "a11y_page.json").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    page = {"url": "https://shop.test/", "load_time_ms": 800, "inputs": [], "buttons": []}
    refused = capture_portfolios(linked / "run", [page], source_url="https://shop.test/")
    missing = capture_portfolios(linked / "fresh", [page], source_url="https://shop.test/")
    assert refused["a11y_page"] == {} and refused["performance"] is None
    assert missing["a11y_page"] == {}
    assert not (other / "fresh").exists()
    assert not (nested / "performance.json").exists()
    assert (nested / "a11y_page.json").read_bytes() == secret
    assert (nested / "keep.txt").read_bytes() == secret

    real = tmp_path / "real"
    saved = capture_portfolios(real, [page], source_url="https://shop.test/", crawl={"mobile_check": True})
    written = real / "a11y_page.json"
    assert written.is_file() and not written.is_symlink()
    assert secret not in written.read_bytes()
    assert saved["performance"]["load_ms"] == 800
    assert (real / "compatibility.json").is_file()
    assert (nested / "keep.txt").read_bytes() == secret


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
