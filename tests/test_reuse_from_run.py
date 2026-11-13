"""Regression: Studio "Run the same tests again" must prefer that run's scripts."""
from __future__ import annotations

import json

from backend.agents.change_detection import saved_tests
from backend.config import settings


def test_saved_tests_prefers_from_run(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    baseline = tmp_path / "baseline"
    monkeypatch.setattr(settings, "runs_dir", runs)
    monkeypatch.setattr(settings, "baseline_dir", baseline)

    site = "example.com"
    # baseline has older scripts
    btests = baseline / site / "tests"
    btests.mkdir(parents=True)
    (btests / "test_old.py").write_text("def test_old():\n    assert True\n", encoding="utf-8")
    (baseline / site / "test_cases.json").write_text("[]", encoding="utf-8")
    (baseline / site / "meta.json").write_text(json.dumps({"date": "old", "origin": "http://example.com"}), encoding="utf-8")

    run = "run-20260101-abc"
    g = runs / run / "generated_tests"
    g.mkdir(parents=True)
    (g / "test_login.py").write_text("def test_login():\n    assert True\n", encoding="utf-8")
    (g / "helpers.py").write_text("X = 1\n", encoding="utf-8")
    (runs / run / "test_cases.json").write_text(json.dumps([{"id": "c1"}]), encoding="utf-8")
    (runs / run / "summary.json").write_text(json.dumps({"url": "http://example.com/app"}), encoding="utf-8")

    got = saved_tests(site, from_run=run)
    assert got is not None
    names = {f.name for f in got["files"]}
    assert "test_login.py" in names
    assert "helpers.py" in names
    assert "test_old.py" not in names
    assert got["meta"]["source_run"] == run
    assert got["meta"]["origin"] == "http://example.com/app"
    assert got["cases"] == [{"id": "c1"}]


def test_saved_tests_falls_back_to_baseline(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    baseline = tmp_path / "baseline"
    monkeypatch.setattr(settings, "runs_dir", runs)
    monkeypatch.setattr(settings, "baseline_dir", baseline)
    site = "example.com"
    btests = baseline / site / "tests"
    btests.mkdir(parents=True)
    (btests / "test_old.py").write_text("def test_old():\n    assert True\n", encoding="utf-8")
    (baseline / site / "test_cases.json").write_text("[]", encoding="utf-8")
    (baseline / site / "meta.json").write_text(json.dumps({"date": "old", "origin": "http://example.com"}), encoding="utf-8")

    got = saved_tests(site, from_run="missing-run")
    assert got is not None
    assert got["files"][0].name == "test_old.py"
