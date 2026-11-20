"""An API version contract stays in this install. A link does not build it."""
from backend.api_version_drill import run_api_version_drill
from backend.blueprint_progress import progress


def test_an_api_version_contract_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.api_version_drill as mod

    calls = {"n": 0}
    real_build = mod.build_api_version_contract

    def _build():
        calls["n"] += 1
        return real_build()

    monkeypatch.setattr(mod, "build_api_version_contract", _build)

    secret = "tenant-b-api"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "api_version_contract.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_api_version_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_i_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_api_version_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_api_version_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_i_complete"] is False
    assert saved["ok"] is True
    assert calls["n"] == 1
    assert "API versioning" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_api_version_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-api-version-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-api-version-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "I")["status"] != "done"
    assert snap["complete"] is False
