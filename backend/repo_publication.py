"""Publish exactly the reviewed, pinned proposal as a branch and pull request."""
import base64
import hashlib
import json
import threading
from pathlib import Path
from urllib.parse import quote

_LOCKS: dict[str, threading.Lock] = {}
_LOCK = threading.Lock()


def publish(run_dir: Path, token: str, proposal_id: str) -> dict:
    from .finalization import read_json
    from .repo_fix import RepoFixError, _gh, _text_hash
    with _LOCK:
        guard = _LOCKS.setdefault(str(run_dir.resolve()), threading.Lock())
    with guard:
        plan = read_json(run_dir / ".private" / "repo_fix_plan.json", {})
        if not proposal_id or proposal_id != plan.get("proposal_id"):
            raise RepoFixError("The reviewed proposal changed. Prepare and review the current diff again.")
        content_id = hashlib.sha256(json.dumps({k: v for k, v in plan.items() if k != "proposal_id"}, sort_keys=True).encode()).hexdigest()
        if content_id != proposal_id:
            raise RepoFixError("The proposal content changed after review. Prepare it again.")
        prior = read_json(run_dir / ".private" / "repo_fix_publication.json", {})
        if prior.get("proposal_id") == proposal_id:
            return prior
        if not token or not plan.get("files"):
            raise RepoFixError("A token and a nonempty reviewed proposal are required.")
        if any(check.get("status") == "failed" for check in plan.get("validation", [])):
            raise RepoFixError("Validation failed. Correct the proposal before publication.")
        repo, base, expected = plan["repo"], plan["base_branch"], plan["base_commit"]
        branch = "qpilot/fix-" + proposal_id[:16]
        existing = _gh("GET", f"/repos/{repo}/pulls", token, params={"head": repo.split('/')[0] + ':' + branch, "state": "all"})
        if existing:
            result = {"proposal_id": proposal_id, "pr_url": existing[0]["html_url"], "branch": branch}
            (run_dir / ".private" / "repo_fix_publication.json").write_text(json.dumps(result), encoding="utf-8")
            return result
        current = _gh("GET", f"/repos/{repo}/git/ref/heads/{quote(base, safe='')}", token)["object"]["sha"]
        if current != expected:
            raise RepoFixError("The base branch changed after preparation. Prepare and review a fresh proposal.")
        tree_files = []
        for file in plan["files"]:
            remote = _gh("GET", f"/repos/{repo}/contents/{quote(file['path'], safe='/')}", token, params={"ref": expected})
            text = base64.b64decode(remote.get("content") or "").decode("utf-8", errors="replace")
            if _text_hash(text) != file["old_hash"]:
                raise RepoFixError("Source changed or does not match the reviewed patch: " + file["path"])
            content = file["content"].replace("\r\n", "\n")
            if "\r\n" in text:
                content = content.replace("\n", "\r\n")
            tree_files.append({"path": file["path"], "mode": file.get("mode", "100644"), "type": "blob", "content": content})
        journal_file = run_dir / ".private" / "repo_fix_journal.json"
        journal = read_json(journal_file, {})
        if journal.get("proposal_id") == proposal_id:
            commit = {"sha": journal["commit_sha"]}
        else:
            original = _gh("GET", f"/repos/{repo}/git/commits/{expected}", token)
            tree = _gh("POST", f"/repos/{repo}/git/trees", token, json={"base_tree": original["tree"]["sha"], "tree": tree_files})
            commit = _gh("POST", f"/repos/{repo}/git/commits", token, json={
                "message": "Qpilot: apply reviewed QA fixes", "tree": tree["sha"], "parents": [expected]})
            journal_file.write_text(json.dumps({"proposal_id": proposal_id, "commit_sha": commit["sha"]}), encoding="utf-8")
        try:
            _gh("POST", f"/repos/{repo}/git/refs", token, json={"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
        except RepoFixError:
            # Recover an earlier publication interrupted between branch creation and PR creation.
            ref = _gh("GET", f"/repos/{repo}/git/ref/heads/{branch}", token)
            if ref["object"]["sha"] != commit["sha"]:
                raise RepoFixError("The proposal branch has unexpected changes; it was not overwritten.") from None
        lines = ["Qpilot QA fixes", "", f"Reviewed proposal: `{proposal_id}`", f"Base commit: `{expected}`", ""]
        lines += [f"- {item['title']}: {item['why']} (finding `{item.get('finding_id', '')}`)" for item in plan.get("applied", [])]
        lines += ["", "Validation:"] + [f"- {c['name']}: {c['status']}. {c.get('detail', '')}" for c in plan.get("validation", [])]
        lines += ["", "Review changes and run project CI before merging. Recheck the deployed application afterward."]
        pr = _gh("POST", f"/repos/{repo}/pulls", token, json={"title": "Qpilot: reviewed QA fixes", "head": branch,
                                                              "base": base, "body": "\n".join(lines)})
        result = {"proposal_id": proposal_id, "pr_url": pr["html_url"], "branch": branch,
                  "files": [f["path"] for f in plan["files"]]}
        (run_dir / ".private" / "repo_fix_publication.json").write_text(json.dumps(result), encoding="utf-8")
        return result
