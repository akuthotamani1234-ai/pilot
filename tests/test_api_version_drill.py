"""Gate I API versioning contract drill stays incomplete and self-consistent."""
from pathlib import Path

from backend.api_version_drill import build_api_version_contract, run_api_version_drill


def test_api_version_contract_rejects_unsupported(tmp_path: Path):
    body = build_api_version_contract()
    assert body["gate_i_complete"] is False
    assert body["ok"] is True
    assert 1 in body["supported"]
    assert body["unsupported"]["ok"] is False
    evidence = run_api_version_drill(ops_dir=tmp_path)
    assert (tmp_path / "api_version_contract.json").is_file()
    assert evidence["ok"] is True
