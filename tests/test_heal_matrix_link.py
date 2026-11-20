"""A healing matrix stays in this install. A link does not start a browser."""
from backend.blueprint_progress import progress
from backend.production_healing_matrix_drill import run_production_healing_matrix_drill


def test_a_healing_matrix_does_not_follow_a_link(tmp_path, monkeypatch):
    import importlib

    import playwright.sync_api as pw

    calls = {"n": 0}

    class _Locator:
        def click(self, timeout=0):
            raise TimeoutError("missing")

        def inner_text(self, timeout=0):
            return "hello"

    class _Page:
        def locator(self, _selector):
            return _Locator()

        def get_by_role(self, _role, name=None):
            return _Locator()

        def goto(self, url, wait_until=None, timeout=0):
            if "qpilot-prod-unreachable" in url:
                raise TimeoutError("nav")
            return None

        def close(self):
            return None

    class _Browser:
        def new_page(self):
            return _Page()

        def close(self):
            return None

    class _Chromium:
        def launch(self):
            return _Browser()

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        chromium = _Chromium()

    def _sync():
        calls["n"] += 1
        return _Session()

    class _Started:
        url = "http://127.0.0.1:9/local"

        def stop(self):
            return None

    class _Fixture:
        def start(self):
            return _Started()

    def _import(name):
        calls["n"] += 1
        cls = {
            "tests.demo_store": "DemoStore",
            "tests.classic_shop": "ClassicShop",
            "tests.admin_portal": "AdminPortal",
            "tests.travel_site": "TravelSite",
        }[name]
        mod = type("M", (), {})()
        setattr(mod, cls, _Fixture)
        return mod

    monkeypatch.setattr(pw, "sync_playwright", _sync)
    monkeypatch.setattr(importlib, "import_module", _import)

    secret = "tenant-b-matrix"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "production_healing_matrix_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_production_healing_matrix_drill(ops_dir=linked)
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
    skipped = run_production_healing_matrix_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_production_healing_matrix_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_e_complete"] is False
    assert saved["ok"] is True
    assert saved["passed"] == 4
    assert calls["n"] == 5
    assert "healing matrix" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_heal_matrix_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-heal-matrix-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-heal-matrix-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "E")["status"] != "done"
    assert snap["complete"] is False
