"""An integrity receipt hashes this install's notes. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.independent_review_integrity_drill import (
    run_independent_review_integrity_drill,
)


def test_an_integrity_receipt_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.independent_review_request_drill as req

    calls = {"n": 0}
    real = req.run_independent_review_request_drill

    def _request(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(req, "run_independent_review_request_drill", _request)

    secret = "tenant-b-only-integrity"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "keep.txt"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_independent_review_integrity_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert calls["n"] == 0
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert [path.name for path in other.iterdir()] == ["keep.txt"]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / "independent_review_integrity_drill.json"
    planted.symlink_to(kept)
    skipped = run_independent_review_integrity_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert skipped["signed_off"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_independent_review_integrity_drill(ops_dir=real)
    written = (real / "independent_review_integrity_drill.json").read_text(encoding="utf-8")
    assert saved["ok"] is True
    assert saved["gate_g_complete"] is False
    assert saved["signed_off"] is False
    assert calls["n"] >= 1
    assert saved["integrity_sha256"]
    assert secret not in written
    assert kept.read_bytes() == original


def test_integrity_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-integrity-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
