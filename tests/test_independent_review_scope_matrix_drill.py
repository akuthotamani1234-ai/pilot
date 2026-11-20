"""Independent review scope matrix stays unsigned for Gate G."""
from backend.independent_review_scope_matrix_drill import (
    SCOPE,
    run_independent_review_scope_matrix_drill,
)


def test_independent_review_scope_matrix_stays_partial(tmp_path, monkeypatch):
    import backend.independent_review_scope_matrix_drill as mod

    ops = tmp_path / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for _, _, artifacts in SCOPE:
        for artifact in artifacts:
            (ops / artifact).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    evidence = run_independent_review_scope_matrix_drill(ops_dir=tmp_path)
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert evidence["ok"] is True
    assert evidence["score_of"] == len(SCOPE)
    assert (tmp_path / "independent_review_scope_matrix_drill.json").is_file()
