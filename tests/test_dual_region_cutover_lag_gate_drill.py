"""Cutover lag gate stays incomplete for Gate H."""
from backend.dual_region_cutover_lag_gate_drill import (
    evaluate_cutover_lag,
    run_dual_region_cutover_lag_gate_drill,
)


def test_over_budget_blocks_cutover():
    decision = evaluate_cutover_lag([
        {"store": "postgres", "ok": True, "elapsed_ms": 1000},
        {"store": "redis", "ok": True, "elapsed_ms": 6000},
        {"store": "minio", "ok": True, "elapsed_ms": 1000},
    ])
    assert decision["cutover_blocked"] is True
    redis = next(row for row in decision["stores"] if row["store"] == "redis")
    assert redis["over_budget"] is True


def test_within_budget_allows_cutover():
    decision = evaluate_cutover_lag([
        {"store": "postgres", "ok": True, "elapsed_ms": 800},
        {"store": "redis", "ok": True, "elapsed_ms": 200},
        {"store": "minio", "ok": True, "elapsed_ms": 900},
    ])
    assert decision["cutover_blocked"] is False


def test_cutover_lag_gate_stays_partial(tmp_path, monkeypatch):
    def _fake(*, ops_dir=None):
        return {
            "ok": True,
            "stores": [
                {"store": "postgres", "ok": True, "elapsed_ms": 400},
                {"store": "redis", "ok": True, "elapsed_ms": 120},
                {"store": "minio", "ok": True, "elapsed_ms": 300},
            ],
        }

    monkeypatch.setattr(
        "backend.failover_rto_drill.run_failover_rto_drill",
        _fake,
    )
    evidence = run_dual_region_cutover_lag_gate_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["live_hosted_dr"] is False
    assert evidence["ok"] is True
    assert evidence["cutover_blocked"] is False
    assert (tmp_path / "dual_region_cutover_lag_gate_drill.json").is_file()
