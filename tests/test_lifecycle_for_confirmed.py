"""Gate C: run_rules lifecycle finish uses confirmed cleanup, not a local-only flag."""
from backend.run_rules import lifecycle_for


def test_lifecycle_for_finish_records_cleanup_proof():
    out = lifecycle_for({
        "run_dir": "run-confirm",
        "environment": "test",
        "crawl": {"swarm": {"workers": 2}},
    }, finish=True)
    assert out["refused"] == ""
    assert out["cleanup"]["complete"] is True
    assert out["cleanup"]["local_only"] is False
    assert len(out["cleaned"]) == 6  # 3 records x 2 workers
    assert all(str(row.get("cleanup_proof") or "").startswith("synthetic:") for row in out["cleaned"])
    assert all(row["state"] == "cleaned" for pack in out["prepared"] for row in pack)
