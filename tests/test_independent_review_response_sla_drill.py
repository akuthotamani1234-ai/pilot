"""Independent review response SLA stays unsigned for Gate G."""
from backend.independent_review_response_sla_drill import (
    LOCAL_PARTIAL,
    run_independent_review_response_sla_drill,
)


def test_independent_review_response_sla_stays_partial(tmp_path, monkeypatch):
    import backend.independent_review_response_sla_drill as mod

    ops = tmp_path / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for name in LOCAL_PARTIAL:
        (ops / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    evidence = run_independent_review_response_sla_drill(ops_dir=tmp_path)
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert evidence["ok"] is True
    assert evidence["sla"]["ack_business_days"] == 2
    assert (tmp_path / "independent_review_response_sla_drill.json").is_file()
