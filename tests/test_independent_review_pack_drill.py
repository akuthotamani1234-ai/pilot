from pathlib import Path

from backend.independent_review_pack_drill import run_independent_review_pack_drill


def test_independent_review_pack_stays_unsigned(tmp_path: Path):
    evidence = run_independent_review_pack_drill(ops_dir=tmp_path)
    assert evidence["gate_g_complete"] is False
    assert evidence.get("signed_off") is False
    assert evidence.get("ok") is True
    assert evidence.get("artifact_count", 0) > 0
    assert (tmp_path / "independent_review_pack.json").is_file()
