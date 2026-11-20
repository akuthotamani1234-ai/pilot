"""A multi-browser suite stays in this install. A link does not start the portfolios."""
from backend.blueprint_progress import progress
from backend.multi_browser_portfolio_suite_drill import run_multi_browser_portfolio_suite_drill


def test_a_multi_browser_suite_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.a11y_portfolio_drill as a11y
    import backend.compatibility_portfolio_drill as compat
    import backend.locale_portfolio_drill as locale
    import backend.perf_portfolio_drill as perf
    import backend.security_portfolio_drill as security
    import backend.visual_portfolio_drill as visual

    calls = {"n": 0}

    def _compat(**_kwargs):
        calls["n"] += 1
        return {"ok": True, "matrix": {"browsers": ["chromium", "firefox", "webkit"]}}

    def _pass(**_kwargs):
        calls["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(compat, "run_compatibility_portfolio_drill", _compat)
    monkeypatch.setattr(a11y, "run_a11y_portfolio_drill", _pass)
    monkeypatch.setattr(locale, "run_locale_portfolio_drill", _pass)
    monkeypatch.setattr(security, "run_security_portfolio_drill", _pass)
    monkeypatch.setattr(perf, "run_perf_portfolio_drill", _pass)
    monkeypatch.setattr(visual, "run_visual_portfolio_drill", _pass)

    secret = "tenant-b-browsers"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "multi_browser_portfolio_suite_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_multi_browser_portfolio_suite_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_f_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_multi_browser_portfolio_suite_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_multi_browser_portfolio_suite_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_f_complete"] is False
    assert saved["ok"] is True
    assert saved["suites_passed"] == 6
    assert calls["n"] == 6
    assert "portfolio suite" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_browser_suite_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-browser-suite-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-browser-suite-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "F")["status"] != "done"
    assert snap["complete"] is False
