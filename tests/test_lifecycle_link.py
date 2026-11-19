"""A lifecycle cleanup stays in this install. A link does not write created.jsonl."""
from backend.blueprint_progress import progress
from backend.lifecycle_cleanup_drill import run_lifecycle_cleanup_drill


def test_a_lifecycle_cleanup_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.lifecycle_cleanup_drill as mod

    calls = {"n": 0}
    real_ingest = mod.ingest_created

    def _ingest(*args, **kwargs):
        calls["n"] += 1
        return real_ingest(*args, **kwargs)

    monkeypatch.setattr(mod, "ingest_created", _ingest)

    secret = "tenant-b-lifecycle"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "lifecycle_cleanup_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)
    work = tmp_path / "work"

    refused = run_lifecycle_cleanup_drill(ops_dir=linked, work_dir=work)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_c_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert not work.exists()
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_lifecycle_cleanup_drill(ops_dir=real, work_dir=work)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert not work.exists()
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    work.symlink_to(other, target_is_directory=True)
    unread = run_lifecycle_cleanup_drill(ops_dir=real, work_dir=work)
    assert unread["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(unread)
    assert not any(path.name.startswith("run_") for path in other.iterdir())
    assert kept.read_bytes() == original
    work.unlink()
    work.mkdir()

    saved = run_lifecycle_cleanup_drill(ops_dir=real, work_dir=work)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_c_complete"] is False
    assert saved["ok"] is True
    assert saved["confirmed"] >= 4
    assert saved["failed"] == 0
    assert calls["n"] == 1
    assert "cleanup" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_lifecycle_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-lifecycle-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-lifecycle-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "C")["status"] != "done"
    assert snap["complete"] is False
