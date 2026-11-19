"""A readiness score writes this install's receipt. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.independent_review_readiness_drill import (
    run_independent_review_readiness_drill,
)


def test_a_readiness_score_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.independent_review_pack_drill as pack
    import backend.remaining_blockers_drill as blockers

    calls = {"n": 0}
    real_pack = pack.run_independent_review_pack_drill
    real_blockers = blockers.run_remaining_blockers_drill

    def _pack(*args, **kwargs):
        calls["n"] += 1
        return real_pack(*args, **kwargs)

    def _blockers(*args, **kwargs):
        calls["n"] += 1
        return real_blockers(*args, **kwargs)

    monkeypatch.setattr(pack, "run_independent_review_pack_drill", _pack)
    monkeypatch.setattr(blockers, "run_remaining_blockers_drill", _blockers)

    secret = "tenant-b-only-readiness"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "independent_review_readiness_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_independent_review_readiness_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert calls["n"] == 0
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert [path.name for path in other.iterdir()] == [
        "independent_review_readiness_drill.json",
    ]

    folder = tmp_path / "real"
    folder.mkdir()
    planted = folder / "independent_review_readiness_drill.json"
    planted.symlink_to(kept)
    skipped = run_independent_review_readiness_drill(ops_dir=folder)
    assert skipped["ok"] is False
    assert skipped["signed_off"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_independent_review_readiness_drill(ops_dir=folder)
    written = (folder / "independent_review_readiness_drill.json").read_text(encoding="utf-8")
    assert calls["n"] == 2
    assert saved["ok"] is True
    assert saved["gate_g_complete"] is False
    assert saved["signed_off"] is False
    assert saved["score"] == saved["score_of"]
    assert secret not in written
    assert kept.read_bytes() == original


def test_readiness_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-readiness-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
