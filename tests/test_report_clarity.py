"""Phases 12–13: reports keep PASS/FAIL/BLOCKED/SKIPPED/NOT TESTED/INCONCLUSIVE separate and never imply
complete site coverage when limits leave work unvisited. No invented overall accuracy %."""
import json

from backend import metrics, report_clarity, story
from backend.discovery_report import discovery_report
from backend.qa_benchmark import measure, save_showcase


def test_case_status_counts_keep_outcomes_separate():
    tc = {"planned": 10, "passed": 3, "failed": 2, "flaky": 1, "blocked": 1, "skipped": 1,
          "inconclusive": 1, "not_run": 1, "pending": 0}
    counts = report_clarity.case_status_counts(tc)
    assert counts["PASS"] == 3
    assert counts["FAIL"] == 3  # failed + flaky
    assert counts["BLOCKED"] == 1
    assert counts["SKIPPED"] == 1
    assert counts["NOT TESTED"] == 1
    assert counts["INCONCLUSIVE"] == 1
    assert sum(counts[k] for k in report_clarity.CLARITY_STATUSES) == 10
    assert counts["flaky_included_in_FAIL"] == 1
    assert "PASS" in counts["note"]


def test_feature_status_counts_never_count_gaps_as_pass():
    features = {"discovered": 9, "verified": 2, "failed": 1, "blocked": 1, "skipped": 1,
                "inconclusive": 1, "needs_login": 1, "clicked_only": 1, "unresolved": 1}
    counts = report_clarity.feature_status_counts(features)
    assert counts["PASS"] == 2
    assert counts["FAIL"] == 1
    assert counts["BLOCKED"] == 1
    assert counts["SKIPPED"] == 1
    assert counts["INCONCLUSIVE"] == 1
    assert counts["NOT TESTED"] == 3  # needs_login + clicked_only + unresolved
    assert counts["PASS"] + counts["FAIL"] + counts["BLOCKED"] + counts["SKIPPED"] + counts[
        "NOT TESTED"] + counts["INCONCLUSIVE"] == 9


def test_coverage_limitations_surface_unvisited_pages_and_never_claim_complete_site():
    lim = report_clarity.coverage_limitations(
        crawl={"visited": 2, "not_visited_count": 5, "limit_reached": True,
               "exploration": {"status": "partial", "within_selected_scope": False,
                               "limitation": "Route discovery is not proof that every component was tested."}},
        limits=[{"id": "page_limit", "limit": "Page limit"}],
        incomplete=False)
    assert lim["partial"] is True
    assert lim["claims_complete_product_coverage"] is False
    assert lim["pages"]["not_visited"] == 5
    assert "entire site" in lim["statement"].lower() or "incomplete" in lim["statement"].lower()
    assert "not proof" in lim["limitation"] or "denominators" in lim


def test_partial_exploration_with_interaction_limit_does_not_claim_exhaustive_reachability():
    lim = report_clarity.coverage_limitations(
        crawl={"visited": 11, "not_visited_count": 0,
               "actions": {"not_tried_limit": 8},
               "exploration": {"status": "partial", "within_selected_scope": False, "actions_limited": True}},
        limits=[], incomplete=False)
    assert lim["partial"] is True
    assert lim["actions_not_tried_limit"] == 8
    assert lim["claims_complete_product_coverage"] is False
    text = (lim["statement"] + " " + lim["limitation"]).lower()
    assert "partial" in text or "incomplete" in text
    assert "exhaustive" not in lim["statement"].lower() or "not" in lim["statement"].lower()
    assert any(word in text for word in ("control", "interaction", "workflow", "feature", "url"))


def test_metrics_include_clarity_buckets_without_accuracy_percent():
    results = [{"nodeid": "a.py::t1", "file": "a.py", "test": "t1", "outcome": "passed", "checks": 1},
               {"nodeid": "a.py::t2", "file": "a.py", "test": "t2", "outcome": "failed", "checks": 1}]
    cases = [{"id": "c1", "tc_id": "TC-1", "title": "ok", "files": ["a.py"], "tests": ["t1"],
              "execution_status": "Passed"},
             {"id": "c2", "tc_id": "TC-2", "title": "bad", "files": ["a.py"], "tests": ["t2"],
              "execution_status": "Failed"},
             {"id": "c3", "tc_id": "TC-3", "title": "blocked", "files": [], "tests": [],
              "execution_status": "Blocked", "blocked": True},
             {"id": "c4", "tc_id": "TC-4", "title": "skip", "files": [], "tests": [],
              "execution_status": "Skipped"},
             {"id": "c5", "tc_id": "TC-5", "title": "pending", "files": [], "tests": [],
              "execution_status": "Not run"}]
    failures = [{"source": "test", "nodeid": "a.py::t2", "category": "product_defect"}]
    m = metrics.build(results, cases, None, failures)
    r = m["result_status_counts"]
    assert r["PASS"] == 1 and r["FAIL"] == 1 and r["BLOCKED"] == 1 and r["SKIPPED"] == 1 and r["NOT TESTED"] == 1
    assert "overall_accuracy" not in m
    assert m["headline"]["percent"] in (0, 50, 100, None)  # functional pass rate only, with its own denominator


def test_story_headline_mentions_incomplete_coverage_without_overclaiming_ready():
    ready = story.headline("Ready", [], [])
    assert "every page or feature" in ready["text"].lower() or "not a claim" in ready["text"].lower()
    partial = story.headline("Ready with Risks", [{"priority": "medium"}], ["page limit"], partial_coverage=True)
    assert "coverage was incomplete" in partial["text"].lower()


def test_discovery_report_summary_lists_pages_and_zero_functional_results(tmp_path):
    state = {
        "run_id": "disc1", "run_dir": str(tmp_path), "url": "https://example.test",
        "discovery_only": True,
        "app_map": [{"url": "https://example.test/", "title": "Home", "status": 200},
                    {"url": "https://example.test/a", "title": "A", "status": 200}],
        "crawl": {"visited": 2, "not_visited_count": 4, "limit_reached": True,
                  "exploration": {"status": "partial", "within_selected_scope": False,
                                  "statement": "Exploration is partial.",
                                  "limitation": "Route discovery is not proof."}},
        "log": [],
    }
    out = discovery_report(state)
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert out["verdict"] == "Insufficient Evidence"
    assert summary["pages_visited"] == 2 and summary["pages_not_visited"] == 4
    assert summary["pages_discovered"] == 6
    assert summary["passed"] == summary["failed"] == summary["tests"] == 0
    assert summary["result_status_counts"]["PASS"] == 0
    assert summary["coverage_limitations"]["discovery_only"] is True
    assert summary["coverage_limitations"]["claims_complete_product_coverage"] is False
    assert "functionality was not tested" in html.lower() or "no functional tests" in html.lower()
    assert "entire site" not in html.lower() or "not" in html.lower()


def test_benchmark_records_environment_and_refuses_overall_accuracy(tmp_path):
    run = tmp_path / "clean_run"
    run.mkdir()
    (run / "results.json").write_text(json.dumps([
        {"id": "login", "test": "test_login", "outcome": "passed"},
        {"id": "bug", "test": "test_bug", "outcome": "failed", "exception_type": "AssertionError"},
    ]), encoding="utf-8")
    (run / "report.html").write_text("<html></html>", encoding="utf-8")
    manifest = {"groups": [{"name": "clean", "runs": ["clean_run"],
                            "expected": {"login": "passed", "bug": "failed"}}]}
    result = measure(tmp_path, manifest)
    assert result["overall_accuracy_percent"] is None
    assert "not general product accuracy" in result["scope"].lower()
    assert "Not overall" in result["metric_labels"]["precision"]
    assert result["environment"]["python"]
    assert result["environment"]["platform"]
    assert str(tmp_path.resolve()) == result["environment"]["runs_root"]
    assert result["environment"]["measured_at"].endswith("Z")
    out = tmp_path / "showcase"
    save_showcase(tmp_path, manifest, out)
    bench = json.loads((out / "benchmark.json").read_text(encoding="utf-8"))
    html = (out / "report.html").read_text(encoding="utf-8")
    assert bench["overall_accuracy_percent"] is None
    assert "environment" in bench and "metric_labels" in bench
    assert "not overall product accuracy" in html.lower()
    assert "overall_accuracy_percent remains unset" in html.lower()
