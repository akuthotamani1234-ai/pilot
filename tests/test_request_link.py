"""A review request writes this install's receipt. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.independent_review_request_drill import (
    run_independent_review_request_drill,
)


def test_a_review_request_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.independent_review_pack_drill as pack_mod
    import backend.independent_review_readiness_drill as ready_mod
    import backend.independent_review_summary_drill as summary_mod
    import backend.remaining_blockers_drill as blockers_mod

    calls = {"n": 0}

    def _wrap(fn):
        def _inner(*args, **kwargs):
            calls["n"] += 1
            return fn(*args, **kwargs)
        return _inner

    monkeypatch.setattr(pack_mod, "run_independent_review_pack_drill", _wrap(pack_mod.run_independent_review_pack_drill))
    monkeypatch.setattr(ready_mod, "run_independent_review_readiness_drill", _wrap(ready_mod.run_independent_review_readiness_drill))
    monkeypatch.setattr(summary_mod, "run_independent_review_summary_drill", _wrap(summary_mod.run_independent_review_summary_drill))
    monkeypatch.setattr(blockers_mod, "run_remaining_blockers_drill", _wrap(blockers_mod.run_remaining_blockers_drill))

    secret = "tenant-b-only-request"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "independent_review_request_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_independent_review_request_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert calls["n"] == 0
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert [path.name for path in other.iterdir()] == [
        "independent_review_request_drill.json",
    ]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / "independent_review_request_drill.json"
    planted.symlink_to(kept)
    skipped = run_independent_review_request_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert skipped["signed_off"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_independent_review_request_drill(ops_dir=real)
    written = (real / "independent_review_request_drill.json").read_text(encoding="utf-8")
    assert saved["ok"] is True
    assert saved["gate_g_complete"] is False
    assert saved["signed_off"] is False
    assert calls["n"] >= 4
    assert saved["request"]["open_blockers"]
    assert secret not in written
    assert kept.read_bytes() == original


def test_request_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-request-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
