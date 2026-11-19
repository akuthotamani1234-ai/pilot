"""Repo-fix prepare: every tag change is matched or unmatched; partial findings are not full success.

When one finding has several tag changes and only some are found, the preview
used to list the finding as fully applied and drop the missing subset.
"""
import json
from pathlib import Path

import pytest

from backend import repo_fix

REPO_URL = "https://github.com/example/demo-site"


def _run_with_repo(tmp_path: Path, monkeypatch, html: str, fixes: list[dict]) -> dict:
    """Local fake repo (no git/network): write fixes.json and point _local_copy at a fixture tree."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "fixes.json").write_text(json.dumps(fixes), encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "index.html").write_text(html, encoding="utf-8")
    monkeypatch.setattr(repo_fix, "_local_copy", lambda repo_url, token, rd: root)
    return repo_fix.prepare(run_dir, REPO_URL, token="")


def test_partial_multi_tag_finding_is_not_recorded_as_fully_applied(tmp_path, monkeypatch):
    """One finding, two tags: only email exists in the repo → applied as partial + unmatched in skipped."""
    html = '<form><input id="email" type="text" name="email"></form>\n'
    fixes = [{
        "title": "Require email and phone",
        "priority": "high",
        "why": "Both fields need required.",
        "code": {
            "before": '<input id="email" type="text" name="email">\n<input id="phone" type="text" name="phone">',
            "after": '<input id="email" type="email" name="email" required>\n<input id="phone" type="tel" name="phone" required>',
        },
    }]
    plan = _run_with_repo(tmp_path, monkeypatch, html, fixes)

    assert len(plan["applied"]) == 1
    assert plan["applied"][0]["partial"] is True
    assert plan["applied"][0]["title"] == "Require email and phone"
    assert any("email" in m for m in plan["applied"][0]["matched"])
    assert any("phone" in u for u in plan["applied"][0]["unmatched"])

    assert len(plan["skipped"]) == 1
    assert plan["skipped"][0]["partial"] is True
    assert plan["skipped"][0]["unmatched"] == plan["applied"][0]["unmatched"]
    assert "Only some" in plan["skipped"][0]["reason"]
    assert plan["files"] and "required" in plan["files"][0]["diff"]


def test_fully_matched_multi_tag_finding_stays_applied_only(tmp_path, monkeypatch):
    html = (
        '<form>\n'
        '<input id="email" type="text" name="email">\n'
        '<input id="phone" type="text" name="phone">\n'
        '</form>\n'
    )
    fixes = [{
        "title": "Require email and phone",
        "priority": "high",
        "why": "Both fields need required.",
        "code": {
            "before": '<input id="email" type="text" name="email">\n<input id="phone" type="text" name="phone">',
            "after": '<input id="email" type="email" name="email" required>\n<input id="phone" type="tel" name="phone" required>',
        },
    }]
    plan = _run_with_repo(tmp_path, monkeypatch, html, fixes)

    assert len(plan["applied"]) == 1
    assert "partial" not in plan["applied"][0]
    assert plan["skipped"] == []
    assert len(plan["files"]) == 1
    diff = plan["files"][0]["diff"]
    assert "required" in diff and "type=\"email\"" in diff


def test_fully_unmatched_finding_is_skipped_with_unmatched_list(tmp_path, monkeypatch):
    html = '<form><input id="other" type="text"></form>\n'
    fixes = [{
        "title": "Add required on email",
        "why": "Missing required.",
        "code": {
            "before": '<input id="email" type="text" name="email">',
            "after": '<input id="email" type="text" name="email" required>',
        },
    }]
    plan = _run_with_repo(tmp_path, monkeypatch, html, fixes)

    assert plan["applied"] == []
    assert plan["files"] == []
    assert len(plan["skipped"]) == 1
    assert plan["skipped"][0]["title"] == "Add required on email"
    assert "partial" not in plan["skipped"][0]
    assert plan["skipped"][0]["unmatched"]
    assert plan["skipped"][0]["code"] == plan["skipped"][0]["unmatched"][0]


def test_prepare_returns_scan_counts_and_advice_only_no_code(tmp_path, monkeypatch):
    """Prepare response includes files_scanned / fixes_considered and structured no_code advice."""
    html = '<form><input id="email" type="text" name="email"></form>\n'
    fixes = [
        {
            "title": "Require email",
            "why": "Missing required.",
            "code": {
                "before": '<input id="email" type="text" name="email">',
                "after": '<input id="email" type="text" name="email" required>',
            },
        },
        {
            "title": "Explain CAPTCHA to users",
            "why": "No automatic code change; document the login step.",
            "fix": "Add help text near login.",
        },
    ]
    plan = _run_with_repo(tmp_path, monkeypatch, html, fixes)

    assert plan["files_scanned"] == 1
    assert plan["fixes_considered"] == 1
    assert plan["fixes_total"] == 2
    assert plan["files"] and "required" in plan["files"][0]["diff"]
    assert len(plan["no_code"]) == 1
    assert plan["no_code"][0]["title"] == "Explain CAPTCHA to users"
    assert "document the login" in plan["no_code"][0]["why"].lower() or "help text" in plan["no_code"][0]["why"].lower()


def test_create_pr_body_does_not_count_partial_as_full_success(tmp_path, monkeypatch):
    """PR title/body list partial repairs separately from fully applied fixes."""
    plan = {
        "repo": "example/demo-site",
        "files": [{
            "path": "index.html",
            "fixes": ["Require email and phone"],
            "old_hash": repo_fix._text_hash('<input id="email" type="text">'),
            "content": '<input id="email" type="email" required>',
        }],
        "applied": [
            {"title": "Full fix", "why": "done", "priority": "high"},
            {"title": "Partial fix", "why": "half", "partial": True,
             "matched": ['<input id="email">'], "unmatched": ['<input id="phone">']},
        ],
        "skipped": [
            {"title": "Partial fix", "reason": "Only some...", "code": '<input id="phone">',
             "unmatched": ['<input id="phone">'], "partial": True},
            {"title": "Missing entirely", "reason": "not found", "code": "<x>", "unmatched": ["<x>"]},
        ],
    }
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "repo_fix_plan.json").write_text(json.dumps(plan), encoding="utf-8")

    calls = []

    def fake_gh(method, path, token, **kw):
        calls.append((method, path, kw))
        if method == "GET" and path.endswith("/example/demo-site"):
            return {"default_branch": "main"}
        if method == "GET" and "/git/ref/" in path:
            return {"object": {"sha": "abc"}}
        if method == "POST" and path.endswith("/git/refs"):
            return {}
        if method == "GET" and "/contents/" in path:
            import base64
            remote = '<input id="email" type="text">'
            return {"sha": "file-sha", "content": base64.b64encode(remote.encode()).decode()}
        if method == "PUT":
            return {}
        if method == "POST" and path.endswith("/pulls"):
            return {"html_url": "https://github.com/example/demo-site/pull/1"}
        raise AssertionError(f"unexpected GitHub call: {method} {path}")

    monkeypatch.setattr(repo_fix, "_gh", fake_gh)
    result = repo_fix.create_pr(run_dir, token="t", run_id="run-20260101-partial")

    assert result["pr_url"].endswith("/pull/1")
    pr_post = next(c for c in calls if c[0] == "POST" and c[1].endswith("/pulls"))
    body = pr_post[2]["json"]
    assert body["head"].startswith("qpilot/fixes-")
    assert body["title"] == "Qpilot: 1 website fix(es), 1 partial"
    assert "### What this changes" in body["body"]
    assert "**Full fix**" in body["body"]
    assert "### Partially applied" in body["body"]
    assert "**Partial fix**" in body["body"]
    assert "### Not changed here" in body["body"]
    assert "Missing entirely" in body["body"]
    # Partial must not be double-listed under the fully-skipped hand-fix section only as success
    assert body["body"].count("**Partial fix**") == 1


def test_a_reviewed_proposal_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-fix"
    other = tmp_path / "other"
    nested = other / "run"
    nested.mkdir(parents=True)
    (nested / "fixes.json").write_text(json.dumps([{
        "title": secret,
        "code": {"before": "<p>old</p>", "after": "<p>new</p>"},
    }]), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    called = []
    monkeypatch.setattr(repo_fix, "_local_copy", lambda *args: called.append(args))
    with pytest.raises(repo_fix.RepoFixError, match="link"):
        repo_fix.prepare(linked / "run", REPO_URL, token="")
    assert called == []
    assert secret in (nested / "fixes.json").read_text(encoding="utf-8")
    assert not (nested / "repo_fix_plan.json").exists()
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    (real / "fixes.json").write_text(json.dumps([{"title": "home-own", "why": "home-own"}]), encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(repo_fix, "_local_copy", lambda *_args: root)
    plan = repo_fix.prepare(real, REPO_URL, token="")
    assert plan["no_code"][0]["title"] == "home-own"
    assert secret not in json.dumps(plan)
    assert secret in (nested / "fixes.json").read_text(encoding="utf-8")


def test_a_published_proposal_file_does_not_follow_a_link_into_another_folder(tmp_path):
    from backend.repo_fix import RepoFixError
    from backend.repo_publication import _save_private

    secret = "tenant-b-only-publish"
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_text(secret, encoding="utf-8")
    (other / "repo_fix_publication.json").write_text(secret, encoding="utf-8")
    parent = tmp_path / "parent"
    parent.symlink_to(other, target_is_directory=True)
    with pytest.raises(RepoFixError, match="link"):
        _save_private(parent / "repo_fix_publication.json", "home-own")
    assert (other / "repo_fix_publication.json").read_text(encoding="utf-8") == secret
    assert (other / "keep.txt").read_text(encoding="utf-8") == secret
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    _save_private(real / "repo_fix_publication.json", "home-own")
    assert (real / "repo_fix_publication.json").read_text(encoding="utf-8") == "home-own"
    assert secret not in (real / "repo_fix_publication.json").read_text(encoding="utf-8")
    assert (other / "repo_fix_publication.json").read_text(encoding="utf-8") == secret
    assert (other / "keep.txt").read_text(encoding="utf-8") == secret


def test_a_published_proposal_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import base64

    secret = "tenant-b-only-proposal"
    other = tmp_path / "other"
    nested = other / "run"
    nested.mkdir(parents=True)
    (nested / "repo_fix_plan.json").write_text(json.dumps({
        "repo": "fixture/secret",
        "files": [{"path": "index.html", "content": secret, "old_hash": "x", "fixes": [secret]}],
        "applied": [{"title": secret, "why": secret}],
    }), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    called = []
    monkeypatch.setattr(repo_fix, "_gh", lambda *args, **kwargs: called.append(args))
    with pytest.raises(repo_fix.RepoFixError, match="link"):
        repo_fix.create_pr(linked / "run", "token", "run-home")
    assert called == []
    assert secret in (nested / "repo_fix_plan.json").read_text(encoding="utf-8")
    assert not (other / "fresh").exists()

    content = "home-own\n"
    real = tmp_path / "real"
    real.mkdir()
    (real / "repo_fix_plan.json").write_text(json.dumps({
        "repo": "fixture/home",
        "files": [{
            "path": "index.html", "content": content, "old_hash": repo_fix._text_hash(content),
            "fixes": ["home-own"],
        }],
        "applied": [{"title": "home-own", "why": "home-own"}],
        "skipped": [],
    }), encoding="utf-8")

    def fake_gh(method, path, token, **kwargs):
        called.append((method, path, kwargs))
        if method == "GET" and path == "/repos/fixture/home":
            return {"default_branch": "main"}
        if method == "GET" and path.endswith("/git/ref/heads/main"):
            return {"object": {"sha": "abc123"}}
        if method == "POST" and path.endswith("/git/refs"):
            return {}
        if method == "GET" and "/contents/" in path:
            return {"content": base64.b64encode(content.encode()).decode(), "sha": "file"}
        if method == "PUT":
            return {}
        if method == "POST" and path.endswith("/pulls"):
            return {"html_url": "https://github.com/fixture/home/pull/2"}
        raise AssertionError(path)

    monkeypatch.setattr(repo_fix, "_gh", fake_gh)
    result = repo_fix.create_pr(real, "token", "run-home")
    assert result["pr_url"].endswith("/pull/2")
    body = next(item[2]["json"]["body"] for item in called if item[0] == "POST" and item[1].endswith("/pulls"))
    assert "home-own" in body
    assert secret not in json.dumps([item[2] for item in called])
    assert secret in (nested / "repo_fix_plan.json").read_text(encoding="utf-8")
