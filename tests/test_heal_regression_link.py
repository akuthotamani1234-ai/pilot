"""A healing regression stays in this install. A link does not review repairs."""
from backend.blueprint_progress import progress
from backend.healing_regression import run_healing_regression_drill


def test_a_healing_regression_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.healing_regression as mod

    calls = {"n": 0}
    real_build = mod.build_healing_regression

    def _build():
        calls["n"] += 1
        return real_build()

    monkeypatch.setattr(mod, "build_healing_regression", _build)

    secret = "tenant-b-heal"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "healing_regression_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_healing_regression_drill(ops_dir=linked)
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
    skipped = run_healing_regression_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_healing_regression_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_e_complete"] is False
    assert saved["mismatches"] == 0
    assert calls["n"] == 1
    assert "healing regression" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_heal_regression_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-heal-regression-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-heal-regression-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "E")["status"] != "done"
    assert snap["complete"] is False
