from pathlib import Path

from backend.loopback_pkce_sso_drill import run_loopback_pkce_sso_drill


def test_loopback_pkce_sso_reports_honestly(tmp_path: Path):
    evidence = run_loopback_pkce_sso_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert (tmp_path / "loopback_pkce_sso_drill.json").is_file()
    assert evidence.get("ok") is True
    assert evidence.get("pkce") == "S256"
    steps = {s["step"]: s for s in evidence.get("steps") or []}
    assert steps["reject_bad_verifier"]["ok"] is True
    assert steps["reject_redirect_mismatch"]["ok"] is True
