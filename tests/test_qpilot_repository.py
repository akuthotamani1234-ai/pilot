"""Repository proposals are evidence-bound, private, validated and published only as reviewed."""
import base64
import json

import pytest

from backend import repo_fix, repo_proposals, repo_publication


def _setup(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    root = tmp_path / "source"
    root.mkdir()
    (root / "age.py").write_text("def allowed(age):\n    return age >= 0\n", encoding="utf-8")
    (run / "failures.json").write_text(json.dumps([
        {"finding_id": "finding-age", "source": "test", "category": "product_defect", "confidence": "high",
         "test": "test_age", "explanation": "Explicit contract requires age at least eighteen", "evidence": ["trace.zip"]},
        {"finding_id": "finding-locator", "category": "locator", "confidence": "high", "test": "test_hidden"}]), encoding="utf-8")
    (run / "repo_source.json").write_text(json.dumps({"repo": "fixture/app", "base_branch": "main", "base_commit": "base"}), encoding="utf-8")
    return run, root


def _prepare(tmp_path, monkeypatch, replacement="return age >= 18"):
    run, root = _setup(tmp_path)
    monkeypatch.setattr(repo_proposals, "llm_enabled", lambda: True)
    monkeypatch.setattr(repo_proposals, "ask_structured", lambda *a, **k: repo_proposals.Proposal(
        finding_id="finding-age", explanation="Enforce the supplied contract", edits=[repo_proposals.Edit(
            path="age.py", before="return age >= 0", after=replacement)]))
    return run, root, repo_proposals.prepare_ai(run, root, ["finding-age"])


def test_ai_prepares_supported_source_patch_and_reports_validation(tmp_path, monkeypatch):
    run, root, plan = _prepare(tmp_path, monkeypatch)
    assert plan["files"][0]["finding_ids"] == ["finding-age"]
    assert "content" not in plan["files"][0]
    assert "return age >= 0" in (root / "age.py").read_text(encoding="utf-8")
    assert (run / ".private" / "repo_fix_plan.json").exists()
    assert not (run / "repo_fix_plan.json").exists()
    assert any(c["status"] == "passed" for c in plan["validation"])
    assert any(c["status"] == "unavailable" and "regression" in c["name"] for c in plan["validation"])


def test_automation_errors_cannot_produce_website_code_changes(tmp_path):
    run, root = _setup(tmp_path)
    with pytest.raises(repo_fix.RepoFixError, match="supported product"):
        repo_proposals.prepare_ai(run, root, ["finding-locator"])


def test_absent_ai_source_is_unsupported_without_changing_files(tmp_path, monkeypatch):
    run, root = _setup(tmp_path)
    monkeypatch.setattr(repo_proposals, "llm_enabled", lambda: True)
    monkeypatch.setattr(repo_proposals, "ask_structured", lambda *a, **k: repo_proposals.Proposal(
        finding_id="finding-age", explanation="invented", edits=[repo_proposals.Edit(
            path="../outside.py", before="anything", after="changed")]))
    plan = repo_proposals.prepare_ai(run, root, ["finding-age"])
    assert not plan["files"] and "absent or ambiguous" in plan["skipped"][0]["reason"]


def test_syntax_failure_blocks_publication(tmp_path, monkeypatch):
    run, root, plan = _prepare(tmp_path, monkeypatch, "return )")
    assert any(c["status"] == "failed" for c in plan["validation"])
    monkeypatch.setattr(repo_fix, "_gh", lambda *a, **k: pytest.fail("Validation failure must make no GitHub calls"))
    with pytest.raises(repo_fix.RepoFixError, match="Validation failed"):
        repo_publication.publish(run, "token", plan["proposal_id"])


def test_stale_base_and_modified_proposal_are_rejected_before_mutations(tmp_path, monkeypatch):
    run, root, plan = _prepare(tmp_path, monkeypatch)
    calls = []
    def gh(method, path, token, **kwargs):
        calls.append(method)
        return [] if path.endswith("/pulls") else {"object": {"sha": "new-base"}}
    monkeypatch.setattr(repo_fix, "_gh", gh)
    with pytest.raises(repo_fix.RepoFixError, match="base branch changed"):
        repo_publication.publish(run, "token", plan["proposal_id"])
    assert all(method == "GET" for method in calls)
    stored = run / ".private" / "repo_fix_plan.json"
    changed = json.loads(stored.read_text(encoding="utf-8"))
    changed["files"][0]["content"] = "tampered"
    stored.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(repo_fix.RepoFixError, match="content changed"):
        repo_publication.publish(run, "token", plan["proposal_id"])


def test_exact_reviewed_patch_is_published_once(tmp_path, monkeypatch):
    run, root, plan = _prepare(tmp_path, monkeypatch)
    calls = []
    def gh(method, path, token, **kwargs):
        calls.append((method, path, kwargs))
        if path.endswith("/pulls"):
            return [] if method == "GET" else {"html_url": "https://github.com/fixture/app/pull/1"}
        if "/git/ref/heads/" in path:
            return {"object": {"sha": "base"}}
        if "/contents/" in path:
            return {"content": base64.b64encode((root / "age.py").read_bytes()).decode()}
        if path.endswith("/git/commits/base"):
            return {"tree": {"sha": "tree-base"}}
        if path.endswith("/git/trees"):
            content = kwargs["json"]["tree"][0]["content"]
            assert content.replace("\r\n", "\n").endswith("return age >= 18\n")
            assert ("\r\n" in content) == (b"\r\n" in (root / "age.py").read_bytes())
            return {"sha": "tree-patch"}
        if path.endswith("/git/commits"):
            return {"sha": "commit-patch"}
        if path.endswith("/git/refs"):
            return {}
        raise AssertionError(path)
    monkeypatch.setattr(repo_fix, "_gh", gh)
    first = repo_publication.publish(run, "token", plan["proposal_id"])
    before = len(calls)
    assert repo_publication.publish(run, "token", plan["proposal_id"]) == first
    assert len(calls) == before
    assert first["branch"].startswith("qpilot/")
    assert all(not (method == "PUT" or "/heads/main" in path and method != "GET") for method, path, _ in calls)


def test_a_reviewed_fix_does_not_follow_a_link_into_another_run(tmp_path, monkeypatch):
    secret = "tenant-b-only-fix"
    other = tmp_path / "other"
    other.mkdir()
    (other / "repo_fix_plan.json").write_text(json.dumps({"secret": secret}), encoding="utf-8")
    (other / "repo_fix_publication.json").write_text(json.dumps({"secret": secret}), encoding="utf-8")
    (other / "repo_fix_journal.json").write_text(json.dumps({"secret": secret}), encoding="utf-8")
    (other / "repo_source.json").write_text(json.dumps({"secret": secret}), encoding="utf-8")
    (other / "repo_fix_status.json").write_text(json.dumps({"secret": secret}), encoding="utf-8")
    monkeypatch.setattr(repo_fix, "_gh", lambda *a, **k: pytest.fail("github"))

    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / ".private").symlink_to(other, target_is_directory=True)
    with pytest.raises(repo_fix.RepoFixError, match="link"):
        from backend.repo_source import snapshot
        snapshot("https://github.com/fixture/app", "token", snap)
    assert json.loads((other / "repo_source.json").read_text(encoding="utf-8"))["secret"] == secret

    prep = tmp_path / "prep"
    prep.mkdir()
    run, _root = _setup(prep)
    (run / ".private").symlink_to(other, target_is_directory=True)
    monkeypatch.setattr(repo_proposals, "llm_enabled", lambda: True)
    monkeypatch.setattr(repo_proposals, "ask_structured", lambda *a, **k: pytest.fail("asked"))
    with pytest.raises(repo_fix.RepoFixError, match="link"):
        repo_proposals.prepare_ai(run, prep / "source", ["finding-age"])
    assert json.loads((other / "repo_fix_plan.json").read_text(encoding="utf-8"))["secret"] == secret

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "fixes.json").write_text("[]", encoding="utf-8")
    (legacy / "repo_fix_plan.json").symlink_to(other / "repo_fix_plan.json")
    monkeypatch.setattr(repo_fix, "_local_copy", lambda *a: prep / "source")
    with pytest.raises(repo_fix.RepoFixError, match="link"):
        repo_fix.prepare(legacy, "https://github.com/fixture/app", "")
    assert json.loads((other / "repo_fix_plan.json").read_text(encoding="utf-8"))["secret"] == secret
    with pytest.raises(repo_fix.RepoFixError, match="link"):
        repo_fix.create_pr(legacy, "token", "legacy-run")

    published = tmp_path / "published"
    published.mkdir()
    saved, _root, plan = _prepare(published, monkeypatch)
    private = saved / ".private"
    (private / "repo_fix_publication.json").symlink_to(other / "repo_fix_publication.json")
    (private / "repo_fix_journal.json").symlink_to(other / "repo_fix_journal.json")
    with pytest.raises(repo_fix.RepoFixError, match="link"):
        repo_publication.publish(saved, "token", plan["proposal_id"])
    assert json.loads((other / "repo_fix_publication.json").read_text(encoding="utf-8"))["secret"] == secret
    assert json.loads((other / "repo_fix_journal.json").read_text(encoding="utf-8"))["secret"] == secret

    job = tmp_path / "job"
    job.mkdir()
    (job / ".private").mkdir()
    (job / ".private" / "repo_fix_status.json").symlink_to(other / "repo_fix_status.json")
    monkeypatch.setattr("backend.repo_jobs.subprocess.Popen", lambda *a, **k: pytest.fail("started"))
    from backend import repo_jobs
    with pytest.raises(repo_fix.RepoFixError, match="link"):
        repo_jobs.start(job, "https://github.com/fixture/app", "token", ["finding-age"])
    assert json.loads((other / "repo_fix_status.json").read_text(encoding="utf-8"))["secret"] == secret


def test_a_source_snapshot_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import io
    import zipfile

    secret = b"tenant-b-only-snapshot"
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    monkeypatch.setattr(repo_fix, "_gh", lambda *args, **kwargs: pytest.fail("github"))
    with pytest.raises(repo_fix.RepoFixError, match="link"):
        from backend.repo_source import snapshot
        snapshot("https://github.com/fixture/app", "token", linked / "run")
    assert (other / "keep.txt").read_bytes() == secret
    assert not (other / "run").exists()

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("fixture-app/README.md", "mine\n")

    class _Response:
        def raise_for_status(self):
            return None

        def iter_content(self, _size):
            yield archive.getvalue()

    monkeypatch.setattr(repo_fix, "_gh", lambda *args, **kwargs: {"default_branch": "main", "object": {"sha": "abc"}})
    monkeypatch.setattr("backend.repo_source.requests.get", lambda *args, **kwargs: _Response())
    real = tmp_path / "real"
    real.mkdir()
    from backend.repo_source import snapshot
    root = snapshot("https://github.com/fixture/app", "token", real)
    assert (root / "README.md").read_text(encoding="utf-8") == "mine\n"
    assert secret not in (root / "README.md").read_bytes()
    assert (other / "keep.txt").read_bytes() == secret


def test_legacy_tag_match_must_be_unique_across_files(tmp_path, monkeypatch):
    run, root = _setup(tmp_path)
    for name in ("first.html", "second.html"):
        (root / name).write_text('<input id="email" type="text">', encoding="utf-8")
    (run / "fixes.json").write_text(json.dumps([{"title": "Email", "code": {
        "before": '<input id="email" type="text">', "after": '<input id="email" type="email">'}}]), encoding="utf-8")
    monkeypatch.setattr(repo_fix, "_local_copy", lambda *args: root)
    plan = repo_fix.prepare(run, "https://github.com/fixture/app", "")
    assert not plan["files"] and plan["skipped"]
