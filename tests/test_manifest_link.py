"""A showcase reads this install's manifest. A link is left unread."""
import json
import sys

import pytest

from backend.blueprint_progress import progress
from backend.qa_benchmark import main


def test_a_showcase_manifest_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch, capsys):
    secret = "tenant-b-only-manifest"
    other = tmp_path / "other"
    other.mkdir()
    stolen = other / "manifest.json"
    stolen.write_text(json.dumps({
        "groups": [{"name": secret, "runs": ["run-a"], "expected": {"home": "passed"}}],
    }), encoding="utf-8")
    original = stolen.read_bytes()
    linked = tmp_path / "linked.json"
    linked.symlink_to(stolen)
    runs = tmp_path / "runs"
    out = tmp_path / "showcase"
    monkeypatch.setattr(sys, "argv", [
        "qa_benchmark", "--manifest", str(linked), "--runs-root", str(runs), "--out", str(out),
    ])
    with pytest.raises(ValueError, match="link"):
        main()
    assert stolen.read_bytes() == original
    assert not out.exists()
    assert secret not in capsys.readouterr().out

    run = runs / "run-a"
    run.mkdir(parents=True)
    (run / "results.json").write_text(
        json.dumps([{"id": "home", "outcome": "passed", "checks": 1}]), encoding="utf-8")
    (run / "report.html").write_text("home-own-report", encoding="utf-8")
    real = tmp_path / "manifest.json"
    real.write_text(json.dumps({
        "groups": [{"name": "home-own", "runs": ["run-a"], "expected": {"home": "passed"}}],
    }), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "qa_benchmark", "--manifest", str(real), "--runs-root", str(runs), "--out", str(out),
    ])
    main()
    written = (out / "benchmark.json").read_text(encoding="utf-8")
    assert "home-own" in written
    assert secret not in written
    assert stolen.read_bytes() == original


def test_manifest_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-manifest-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
