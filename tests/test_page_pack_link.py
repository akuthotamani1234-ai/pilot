"""A paging pack stays in this install. A link does not start the bundled checks."""
from backend.blueprint_progress import progress
from backend.paging_escalation_ack_pack_drill import (
    run_paging_escalation_ack_pack_drill,
)


def test_a_paging_pack_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.paging_ack_drill as ack
    import backend.paging_escalation_drill as escalation

    calls = {"n": 0}

    def _pass(**_kwargs):
        calls["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(escalation, "run_paging_escalation_drill", _pass)
    monkeypatch.setattr(ack, "run_paging_ack_drill", _pass)

    secret = "tenant-b-page-pack"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "paging_escalation_ack_pack_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_paging_escalation_ack_pack_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_h_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_paging_escalation_ack_pack_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_paging_escalation_ack_pack_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_h_complete"] is False
    assert saved["ok"] is True
    assert saved["escalation_ok"] is True
    assert saved["ack_ok"] is True
    assert calls["n"] == 2
    assert "escalation+ack pack ok" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_page_pack_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-page-pack-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-page-pack-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "H")["status"] != "done"
    assert snap["complete"] is False
