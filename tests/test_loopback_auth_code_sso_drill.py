"""Gate I auth-code SSO stays incomplete; needs PyJWT."""
from pathlib import Path

import pytest

pytest.importorskip("jwt")

from backend.loopback_auth_code_sso_drill import run_loopback_auth_code_sso_drill


def test_loopback_auth_code_sso_reports_honestly(tmp_path: Path):
    evidence = run_loopback_auth_code_sso_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert (tmp_path / "loopback_auth_code_sso_drill.json").is_file()
    assert evidence.get("ok") is True
    assert all(s.get("ok") for s in (evidence.get("steps") or []))
