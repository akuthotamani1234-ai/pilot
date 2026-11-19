"""Accuracy reads this run's known-truth file. A link is left unread."""
import json
import sys

import pytest

from backend import accuracy
from backend.blueprint_progress import progress


def test_a_known_truth_file_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch, capsys):
    secret = "tenant-b-only-truth"
    other = tmp_path / "other"
    other.mkdir()
    stolen = other / "truth.json"
    stolen.write_text(json.dumps({"pages": [{"path": f"/{secret}"}], "features": []}), encoding="utf-8")
    original = stolen.read_bytes()
    linked = tmp_path / "linked.json"
    linked.symlink_to(stolen)
    run = tmp_path / "run"
    run.mkdir()
    out = tmp_path / "accuracy.json"
    monkeypatch.setattr(sys, "argv", ["accuracy", str(run), "--truth", str(linked), "--out", str(out)])
    with pytest.raises(ValueError, match="link"):
        accuracy.main()
    assert stolen.read_bytes() == original
    assert not out.exists()
    assert secret not in capsys.readouterr().out

    real = tmp_path / "truth.json"
    real.write_text(json.dumps({"pages": [{"path": "/home-own"}], "features": []}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["accuracy", str(run), "--truth", str(real), "--out", str(out)])
    accuracy.main()
    written = out.read_text(encoding="utf-8")
    assert "/home-own" in written
    assert secret not in written
    assert stolen.read_bytes() == original


def test_truth_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-truth-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
