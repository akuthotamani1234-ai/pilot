"""A core capability drill stays in this install. A link does not run the checks."""
from backend.blueprint_progress import progress
from backend.qx_core_capabilities_drill import run_qx_core_capabilities_drill


def test_a_core_capability_drill_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.qx_core_capabilities_drill as mod

    calls = {"n": 0}
    real_choose = mod.choose_listing

    def _choose(*args, **kwargs):
        calls["n"] += 1
        return real_choose(*args, **kwargs)

    monkeypatch.setattr(mod, "choose_listing", _choose)

    secret = "tenant-b-qx"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "qx_core_capabilities_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_qx_core_capabilities_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_qx_core_capabilities_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    origin = mod.ROOT
    fake = tmp_path / "evidence-root"
    ops = fake / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    secret_note = other / "secret-redis.json"
    secret_note.write_text(secret, encoding="utf-8")
    (ops / "redis_durable_queue_drill.json").symlink_to(secret_note)
    monkeypatch.setattr(mod, "ROOT", fake)
    scanned = run_qx_core_capabilities_drill(ops_dir=real)
    assert scanned["checks"]["A01_redis_evidence"] is False
    assert secret not in str(scanned)
    assert secret_note.read_text(encoding="utf-8") == secret
    assert calls["n"] == 1
    monkeypatch.setattr(mod, "ROOT", origin)

    saved = run_qx_core_capabilities_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_complete"] is False
    assert saved["ok"] is True
    assert calls["n"] == 2
    assert "QX core capabilities" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_qx_core_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-qx-core-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-qx-core-link")
    assert row["status"] == "done"
    assert all(gate["status"] != "done" for gate in snap["gates"])
    assert snap["complete"] is False
