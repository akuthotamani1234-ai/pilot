"""Gate I loopback SSO stays incomplete; requires PyJWT."""
from pathlib import Path

import pytest

from backend.loopback_sso_drill import run_loopback_sso_drill

pytest.importorskip("jwt")


def test_loopback_sso_drill_verifies_signature(tmp_path: Path):
    evidence = run_loopback_sso_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert (tmp_path / "loopback_sso_drill.json").is_file()
    assert evidence.get("ok") is True
    assert evidence.get("signature_verified") is True
