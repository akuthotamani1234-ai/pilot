"""A live failure matrix stays in this install. A link does not start the browser."""
from backend.blueprint_progress import progress
from backend.live_failure_matrix_drill import run_live_failure_matrix_drill


def test_a_live_failure_matrix_does_not_follow_a_link(tmp_path, monkeypatch):
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

    class _Loc:
        def click(self, timeout=None):
            raise TimeoutError("missing")

        def inner_text(self, timeout=None):
            return "hello"

    class _Page:
        def goto(self, *_args, **_kwargs):
            return None

        def locator(self, _sel):
            return _Loc()

        def get_by_role(self, *_args, **_kwargs):
            return _Loc()

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

    secret = "tenant-b-live-matrix"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "live_failure_matrix_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_live_failure_matrix_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_e_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_live_failure_matrix_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_live_failure_matrix_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_e_complete"] is False
    assert saved["ok"] is True
    assert saved["failed"] >= 2
    assert calls["n"] == 2
    assert "failure matrix" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_live_matrix_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-live-matrix-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-live-matrix-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "E")["status"] != "done"
    assert snap["complete"] is False
