"""Phase 5 Gate F: portfolio gates never pass on missing evidence."""
from backend.portfolio_gates import (
    evaluate_a11y,
    evaluate_compatibility,
    evaluate_performance,
    evaluate_portfolios,
    evaluate_security,
)


def test_missing_evidence_is_unknown_not_pass():
    out = evaluate_portfolios()
    assert out["complete"] is False
    assert out["ok"] is False
    assert set(out["unknown"]) == {
        "a11y", "visual", "performance", "locale", "security", "compatibility",
    }
    assert out["passed"] == []


def test_compatibility_requires_desktop_and_mobile():
    missing = evaluate_compatibility({"desktop": 3, "mobile": 0})
    assert missing["verdict"] == "fail"
    assert missing["gate_f_complete"] is False
    ok = evaluate_compatibility({"desktop": 2, "mobile": 2, "browsers": ["chromium"]})
    assert ok["verdict"] == "pass"
    assert ok["ok"] is True


def test_a11y_flags_missing_alt_and_unlabeled_inputs():
    result = evaluate_a11y({
        "images": [{"src": "/hero.png", "alt": ""}],
        "inputs": [{"name": "email", "label": ""}],
    })
    assert result["verdict"] == "fail"
    kinds = {f["kind"] for f in result["findings"]}
    assert kinds == {"missing_alt", "unlabeled_input"}


def test_performance_budget_breach_and_security_headers():
    perf = evaluate_performance({"load_ms": 9000, "dom_content_loaded_ms": 1000})
    assert perf["verdict"] == "fail"
    assert perf["findings"][0]["metric"] == "load_ms"
    sec = evaluate_security({"x-content-type-options": "nosniff"}, https=True)
    assert sec["verdict"] == "fail"
    assert sec["probe"] is False
    missing = {f["target"] for f in sec["findings"]}
    assert "content-security-policy" in missing
    assert "strict-transport-security" in missing


def test_full_portfolios_can_pass_with_evidence():
    out = evaluate_portfolios(
        a11y_page={"images": [{"src": "/a.png", "alt": "Product"}], "inputs": [{"name": "q", "label": "Search"}]},
        visual_report={"changed": [], "same": ["home"]},
        timings={"dom_content_loaded_ms": 500, "load_ms": 900, "largest_contentful_paint_ms": 800},
        locale_observed={"language": "en", "currency": "USD", "date_format": "MDY", "tax": "0", "offered": True},
        locale_expected={"language": "en", "currency": "USD", "date_format": "MDY", "tax": "0", "offered": True},
        security_headers={
            "content-security-policy": "default-src 'self'",
            "strict-transport-security": "max-age=31536000",
            "x-content-type-options": "nosniff",
        },
        https=True,
        compatibility_matrix={"desktop": 2, "mobile": 2, "browsers": ["chromium"]},
    )
    assert out["complete"] is True
    assert out["ok"] is True
    assert out["failed"] == []
    assert set(out["passed"]) == {
        "a11y", "visual", "performance", "locale", "security", "compatibility",
    }
