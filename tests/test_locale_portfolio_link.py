"""A locale portfolio stays in this install. A link does not start the browser."""
from backend.blueprint_progress import progress
from backend.locale_portfolio_drill import run_locale_portfolio_drill


def test_a_locale_portfolio_does_not_follow_a_link(tmp_path, monkeypatch):
    import playwright.sync_api as pw_mod

    import tests.demo_store as store_mod

    calls = {"n": 0}

    class _Store:
        url = "http://127.0.0.1/demo"

        def start(self):
            calls["n"] += 1
            return self

        def stop(self):
            return None

    class _Page:
        def goto(self, *_args, **_kwargs):
            return None

        def evaluate(self, _script):
            return {
                "language": "en",
                "currency": "USD",
                "date_format": "MDY",
                "tax": "0",
                "offered": True,
            }

    class _Browser:
        def new_page(self):
            return _Page()

        def close(self):
            return None

    class _PW:
        class chromium:
            @staticmethod
            def launch():
                calls["n"] += 1
                return _Browser()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(store_mod, "DemoStore", _Store)
    monkeypatch.setattr(pw_mod, "sync_playwright", lambda: _PW())

    secret = "tenant-b-locale"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "locale_portfolio_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_locale_portfolio_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_f_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_locale_portfolio_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    planted.unlink()

    saved = run_locale_portfolio_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_f_complete"] is False
    assert saved["ok"] is True
    assert saved["portfolio"]["verdict"] == "pass"
    assert calls["n"] == 2
    assert "locale portfolio" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_locale_portfolio_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-locale-portfolio-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-locale-portfolio-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "F")["status"] != "done"
    assert snap["complete"] is False
