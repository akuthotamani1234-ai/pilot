"""Gate C: run_rules lifecycle finish uses confirmed cleanup, not a local-only flag."""
from backend.run_rules import lifecycle_for


def test_lifecycle_for_finish_records_cleanup_proof(tmp_path):
    out = lifecycle_for({
        "run_dir": str(tmp_path),
        "environment": "test",
        "crawl": {"swarm": {"workers": 2}},
    }, finish=True)
    assert out["refused"] == ""
    assert out["cleanup"]["complete"] is True
    assert out["cleanup"]["local_only"] is False
    assert out["durable"] is True
    assert len(out["cleaned"]) == 6  # 3 records x 2 workers
    # Unused synthetic plan rows prove "no remote fixture" rather than inventing a remote delete.
    assert all(str(row.get("cleanup_proof") or "").startswith("synthetic_unused:") for row in out["cleaned"])
    assert all(row["state"] == "cleaned" for pack in out["prepared"] for row in pack)
    assert (tmp_path / "qx_lifecycle_state.json").is_file()
