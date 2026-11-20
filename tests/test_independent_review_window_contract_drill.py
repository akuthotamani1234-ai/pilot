"""Independent review window contract stays unsigned for Gate G."""
from backend.independent_review_window_contract_drill import (
    LOCAL_PARTIAL,
    run_independent_review_window_contract_drill,
)


def test_independent_review_window_contract_stays_partial(tmp_path, monkeypatch):
    import backend.independent_review_window_contract_drill as mod

    ops = tmp_path / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for name in LOCAL_PARTIAL:
        (ops / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    evidence = run_independent_review_window_contract_drill(ops_dir=tmp_path)
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert evidence["ok"] is True
    assert evidence["window"]["business_days"] == 10
    assert (tmp_path / "independent_review_window_contract_drill.json").is_file()
