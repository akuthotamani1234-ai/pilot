"""Gate I Studio OIDC callback stays incomplete; needs PyJWT."""
from pathlib import Path

import pytest

pytest.importorskip("jwt")

from backend.studio_oidc_callback_drill import run_studio_oidc_callback_drill


def test_studio_oidc_callback_reports_honestly(tmp_path: Path):
    evidence = run_studio_oidc_callback_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert (tmp_path / "studio_oidc_callback_drill.json").is_file()
    assert evidence.get("ok") is True
    assert evidence["callback"]["signature_verified"] is True
