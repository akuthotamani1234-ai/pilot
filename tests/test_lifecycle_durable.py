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


def test_a_cleanup_record_does_not_follow_a_link_into_another_run(tmp_path, monkeypatch):
    from backend.agents.executor import _clean_up_again
    from backend.agents.reporter import created_records
    from backend.data_lifecycle import ingest_created, latest_created, load_lifecycle, save_lifecycle

    secret = "tenant-b-only-order"
    other = tmp_path / "other"
    other.mkdir()
    (other / "created.jsonl").write_text(
        json.dumps({"what": "order", "tag": secret, "where": "/orders", "status": "created"}) + "\n",
        encoding="utf-8")
    (other / "qx_lifecycle_state.json").write_text(
        json.dumps({"run_id": "run-b", "environment": "test", "workers": {}, "cases": {}}),
        encoding="utf-8")
    before_summary = json.dumps({"secret": secret})
    (other / "created.json").write_text(before_summary, encoding="utf-8")
    run = tmp_path / "run-a"
    run.mkdir()
    (run / "created.jsonl").symlink_to(other / "created.jsonl")
    (run / "qx_lifecycle_state.json").symlink_to(other / "qx_lifecycle_state.json")
    (run / "created.json").symlink_to(other / "created.json")
    assert latest_created(run) == {}
    life = load_lifecycle(run, run_id="run-a", environment="test")
    assert life.run_id == "run-a"
    assert ingest_created(life, run) == []
    assert secret not in json.dumps(created_records(run))
    assert (other / "created.json").read_text(encoding="utf-8") == before_summary
    save_lifecycle(run, life)
    assert json.loads((other / "qx_lifecycle_state.json").read_text(encoding="utf-8"))["run_id"] == "run-b"
    calls = []
    monkeypatch.setattr("backend.agents.executor._run_pytest", lambda *a, **k: calls.append(a))
    (run / "generated").mkdir()
    (run / "generated" / "test_cleanup.py").write_text("def test_cleanup():\n    pass\n", encoding="utf-8")
    _clean_up_again({"log": []}, run, run / "generated", run / "shots")
    assert calls == []
    assert secret in (other / "created.jsonl").read_text(encoding="utf-8")


def test_created_jsonl_delete_refuses_uncleared_records(tmp_path):
    with (tmp_path / "created.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"what": "order", "tag": "qa-run-order", "where": "/orders", "status": "created"}) + "\n")
    life = load_lifecycle(tmp_path, run_id="run", environment="test")
    ingest_created(life, tmp_path)
    out = life.cleanup_confirmed(remote_delete=created_jsonl_delete(tmp_path))
    assert out["complete"] is False
    assert out["failed"][0]["reason"].startswith("created.jsonl still created")
    save_lifecycle(tmp_path, life)
