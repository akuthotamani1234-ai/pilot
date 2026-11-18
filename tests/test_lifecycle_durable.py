"""Gate C: durable lifecycle + created.jsonl cleanup confirmation."""
import json

from backend.data_lifecycle import (
    created_jsonl_delete,
    ingest_created,
    load_lifecycle,
    save_lifecycle,
)
from backend.run_rules import lifecycle_for


def test_lifecycle_persists_between_prepare_and_finish(tmp_path):
    state = {"run_dir": str(tmp_path), "environment": "test", "crawl": {"swarm": {"workers": 1}}}
    first = lifecycle_for(state, finish=False)
    assert first["durable"] is True
    assert (tmp_path / "qx_lifecycle_state.json").is_file()
    tag = first["prepared"][0][0]["tag"]

    # Staging test created then deleted a real fixture tag derived from the synthetic plan.
    with (tmp_path / "created.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"what": "account", "tag": f"{tag}-1", "where": "/users", "status": "created"}) + "\n")
        fh.write(json.dumps({"what": "account", "tag": f"{tag}-1", "where": "/users", "status": "deleted"}) + "\n")

    finished = lifecycle_for(state, finish=True)
    assert finished["cleanup"]["complete"] is True
    proofs = [str(row.get("cleanup_proof") or "") for row in finished["cleaned"]]
    assert any(p.startswith("synthetic_unused:") for p in proofs)
    assert any("created.jsonl:deleted:" in p for p in proofs)


def test_created_jsonl_delete_refuses_uncleared_records(tmp_path):
    with (tmp_path / "created.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"what": "order", "tag": "qa-run-order", "where": "/orders", "status": "created"}) + "\n")
    life = load_lifecycle(tmp_path, run_id="run", environment="test")
    ingest_created(life, tmp_path)
    out = life.cleanup_confirmed(remote_delete=created_jsonl_delete(tmp_path))
    assert out["complete"] is False
    assert out["failed"][0]["reason"].startswith("created.jsonl still created")
    save_lifecycle(tmp_path, life)
