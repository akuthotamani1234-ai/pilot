"""Hosted CI runner matrix stays incomplete for Gates D/F."""
from backend.hosted_ci_runner_matrix_drill import run_hosted_ci_runner_matrix_drill


def test_hosted_ci_runner_matrix_stays_partial(tmp_path):
    evidence = run_hosted_ci_runner_matrix_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["gate_f_complete"] is False
    assert evidence["ok"] is True
    assert evidence["matrix"]["multi_device"]["api_levels"] == [24, 30, 34]
    assert evidence["matrix"]["multi_browser"]["browsers"] == [
        "chromium", "firefox", "webkit",
    ]
    assert (tmp_path / "hosted_ci_runner_matrix_drill.json").is_file()
