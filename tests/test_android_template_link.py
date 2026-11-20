"""The Android harness is this product's template. A link is not copied into the run."""
import json
from types import SimpleNamespace

from backend.blueprint_progress import progress


def test_an_android_test_template_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.android_design as design
    import backend.android_pipeline as android_pipeline

    secret = b"tenant-b-only-harness"
    other = tmp_path / "other"
    other.mkdir()
    (other / "android_conftest.py").write_bytes(secret)
    (other / "keep.txt").write_bytes(secret)
    linked = tmp_path / "linked-template.py"
    linked.symlink_to(other / "android_conftest.py")
    monkeypatch.setattr(design, "ANDROID_CONFTEST", linked)
    monkeypatch.setattr(design.llm, "llm_enabled", lambda: False)
    monkeypatch.setattr(android_pipeline, "validate_mobile_script", lambda *_a, **_k: None)
    monkeypatch.setattr(android_pipeline, "_cleanup_worker_session", lambda *_a, **_k: "")

    def started(*_a, **_k):
        raise AssertionError("started")

    monkeypatch.setattr(android_pipeline, "_run_mobile_process", started)
    case = {"id": "home", "page": "home", "title": "Home", "plan": [["open_screen", ["S1"]], ["assert_visible", ["E1"]]]}
    run = tmp_path / "run"
    run.mkdir()
    (run / "generated_tests").mkdir()
    (run / "generated_tests" / "test_android_generated.py").write_text("def test_home(mobile):\n    pass\n", encoding="utf-8")
    refused = design.generate_scripts({"run_dir": str(run), "test_cases": [dict(case)], "screens": [], "log": []})
    assert refused["scripts"] == [] and "link" in refused["script_errors"][0]
    assert not (run / "generated_tests" / "conftest.py").exists()
    try:
        android_pipeline._execute_mobile({"run_dir": str(run), "config": {}, "test_cases": [dict(case)]})
    except android_pipeline.AndroidEnvironmentError as exc:
        assert "link" in str(exc)
    else:
        raise AssertionError("a linked template was copied")
    assert not (run / "generated_tests" / "conftest.py").exists()
    assert (other / "android_conftest.py").read_bytes() == secret
    assert (other / "keep.txt").read_bytes() == secret

    real_template = tmp_path / "android_conftest.py"
    real_template.write_text("home-own-harness\n", encoding="utf-8")
    monkeypatch.setattr(design, "ANDROID_CONFTEST", real_template)
    real = tmp_path / "real"
    real.mkdir()
    saved = design.generate_scripts({"run_dir": str(real), "test_cases": [dict(case)], "screens": [], "log": []})
    harness = real / "generated_tests" / "conftest.py"
    assert harness.is_file() and not harness.is_symlink()
    assert harness.read_text(encoding="utf-8") == "home-own-harness\n"
    assert secret not in harness.read_bytes()
    assert saved["script_sources"]["test_android_generated.py"] == "template"

    executed = tmp_path / "executed"
    (executed / "generated_tests").mkdir(parents=True)
    (executed / "generated_tests" / "test_android_generated.py").write_text(
        "def test_home(mobile):\n    pass\n", encoding="utf-8")

    def execute(_command, _env, _timeout):
        (executed / "android_results.jsonl").write_text(
            json.dumps({"id": "home", "outcome": "passed", "checks": 1}) + "\n", encoding="utf-8")
        return SimpleNamespace(stdout="", stderr="", returncode=0), False

    monkeypatch.setattr(android_pipeline, "_run_mobile_process", execute)
    result = android_pipeline._execute_mobile({"run_dir": str(executed), "config": {}, "test_cases": [dict(case)]})
    copied = executed / "generated_tests" / "conftest.py"
    assert copied.is_file() and not copied.is_symlink()
    assert copied.read_text(encoding="utf-8") == "home-own-harness\n"
    assert secret not in copied.read_bytes()
    assert result["results"][0]["id"] == "home"
    assert (other / "keep.txt").read_bytes() == secret


def test_android_template_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-android-template-link")
    assert row["status"] == "done"
    gate_g = next(gate for gate in snap["gates"] if gate["id"] == "G")
    assert gate_g["status"] != "done"
    assert snap["complete"] is False
