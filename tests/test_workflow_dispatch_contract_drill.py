from pathlib import Path

from backend.workflow_dispatch_contract_drill import (
    run_workflow_dispatch_contract_drill,
)


def test_workflow_dispatch_contract_reports_honestly(tmp_path: Path):
    evidence = run_workflow_dispatch_contract_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["gate_f_complete"] is False
    assert (tmp_path / "workflow_dispatch_contract_drill.json").is_file()
    assert evidence.get("ok") is True
