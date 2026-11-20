"""A visual portfolio stays in this install. A link does not start the browser."""
from backend.blueprint_progress import progress
from backend.visual_portfolio_drill import run_visual_portfolio_drill


def test_a_visual_portfolio_does_not_follow_a_link(tmp_path, monkeypatch):
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

        def wait_for_timeout(self, *_args):
            return None

        def screenshot(self, path, full_page=False):
            from pathlib import Path
            Path(path).write_bytes(b"png")

    class _Browser:
        def new_page(self, viewport=None):
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

    secret = "tenant-b-visual"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "visual_portfolio_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_visual_portfolio_drill(ops_dir=linked)
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
    skipped = run_visual_portfolio_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    planted.unlink()

    work = real / "visual_work"
    work.symlink_to(other, target_is_directory=True)
    unread = run_visual_portfolio_drill(ops_dir=real)
    assert unread["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(unread)
    assert not (other / "shots").exists()
    assert kept.read_bytes() == original
    work.unlink()

    saved = run_visual_portfolio_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_f_complete"] is False
    assert saved["ok"] is True
    assert saved["pages_recorded"] >= 1
    assert calls["n"] == 2
    assert "visual evidence" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_visual_portfolio_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-visual-portfolio-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-visual-portfolio-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "F")["status"] != "done"
    assert snap["complete"] is False
