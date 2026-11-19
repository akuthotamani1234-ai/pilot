"""A trace redaction edits this run's zip. A link is left unread."""
import importlib.util
import json
import zipfile

from backend.blueprint_progress import progress


def _load(tmp_path, monkeypatch):
    run = tmp_path / "harness"
    run.mkdir()
    monkeypatch.setenv("QA_RUN_DIR", str(run))
    monkeypatch.setenv("QA_SCREENSHOT_DIR", str(run / "shots"))
    monkeypatch.setenv("QA_TRACE_DIR", str(run / "traces"))
    monkeypatch.setenv("QA_TRACES", "false")
    monkeypatch.setenv("TEST_PASSWORD", "secret-pass")
    spec = importlib.util.spec_from_file_location(
        "qa_conftest_link", "backend/templates/conftest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _zip(path, text):
    with zipfile.ZipFile(path, "w") as handle:
        handle.writestr("note.txt", text)


def test_a_trace_redaction_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-trace"
    other = tmp_path / "other"
    other.mkdir()
    target = other / "trace.zip"
    _zip(target, secret)
    original = target.read_bytes()
    (other / "keep.txt").write_text(secret, encoding="utf-8")
    module = _load(tmp_path, monkeypatch)

    run = tmp_path / "run"
    run.mkdir()
    linked = run / "trace.zip"
    linked.symlink_to(target)
    module._redact_zip(linked)
    nested = tmp_path / "nested"
    nested.symlink_to(other, target_is_directory=True)
    module._redact_zip(nested / "trace.zip")
    assert linked.is_symlink()
    assert target.read_bytes() == original
    assert not (run / "trace.tmp").exists()
    assert not (other / "trace.tmp").exists()
    assert (other / "keep.txt").read_text(encoding="utf-8") == secret

    real = tmp_path / "real.zip"
    _zip(real, "home-own-trace secret-pass")
    module._redact_zip(real)
    with zipfile.ZipFile(real) as handle:
        text = handle.read("note.txt")
    assert b"home-own-trace" in text
    assert b"secret-pass" not in text
    assert b"[REDACTED]" in text
    assert secret.encode() not in text
    assert target.read_bytes() == original


def test_trace_redact_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-trace-redact-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
    assert "tenant-b-only-trace" not in json.dumps(snap)
