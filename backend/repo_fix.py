"""Apply the report's code fixes to the website's GitHub repo - as a Pull Request, never directly.

  1. prepare(): download the repo, find each "Code now" element in the source files and apply the
     "Change to" -> a preview (which files, which lines). Nothing is sent to GitHub.
  2. create_pr(): only when the user presses "Create Pull Request": a new branch with the changed files
     and a Pull Request. The main branch is never touched; the user reviews and merges on GitHub.

How an element is found in the source: by its id or name attribute (e.g. <input name="email">), and the
attribute changes (add required, type="email", remove novalidate...) are applied to that tag - this works
for HTML, JSX (React), Vue, Angular templates, PHP... AI-written changes are applied only when the exact
"Code now" text exists in exactly one file. Each change is tracked as matched or unmatched: a finding with
only some tags found is recorded as partial (applied + skipped), never as a full success. Anything that
can't be found safely is listed as "do it by hand".

Needs a GitHub token with "Contents: write" and "Pull requests: write" (GITHUB_TOKEN in .env, or pasted in
the web page for this action only).
"""
import base64
import difflib
import hashlib
import json
import re
import time
from pathlib import Path

import requests

from .codefix import del_attr, set_attr
from .config import settings

GH = "https://api.github.com"
SOURCE_EXT = {".html", ".htm", ".jsx", ".tsx", ".js", ".ts", ".vue", ".svelte", ".php", ".erb", ".hbs", ".ejs",
              ".njk", ".liquid", ".cshtml", ".twig", ".astro", ".jinja", ".j2"}
SKIP_DIRS = {"node_modules", ".git", ".next", ".nuxt", "vendor", ".venv", "venv", "__pycache__", "coverage", ".cache"}
BUILD_DIRS = {"dist", "build", "out", ".output"}
MAX_FILE = 1_000_000
ATTR_RE = re.compile(r"""\s([^\s=/>"']+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s>]+))?""")


class RepoFixError(Exception):
    pass


# ------------------------------------------------------------------ tags

def _attrs(tag: str) -> dict[str, str | None]:
    m = re.match(r"<\s*([\w-]+)", tag)
    body = tag[m.end():] if m else tag
    out = {}
    for name, value in ATTR_RE.findall(body.rstrip(">").rstrip("/")):
        out[name.lower()] = value.strip("\"'") if value else None
    return out


def _tag_name(tag: str) -> str | None:
    m = re.match(r"<\s*([\w-]+)", tag.strip())
    return m.group(1).lower() if m else None


def _ops(before: str, after: str) -> list[tuple]:
    """Attribute changes from the 'Code now' tag to the 'Change to' tag."""
    a, b = _attrs(before), _attrs(after)
    ops = [("del", k) for k in a if k not in b]
    for k, v in b.items():
        if k not in a or (a[k] or "") != (v or ""):
            ops.append(("set", k, v if v not in ("",) else None))
    return ops


def _apply_ops(tag: str, ops: list[tuple]) -> str:
    for op in ops:
        tag = del_attr(tag, op[1]) if op[0] == "del" else set_attr(tag, op[1], op[2])
    return tag


def _find_tags(text: str, tag: str) -> list[re.Match]:
    """Tags in a source file that are the same element: same tag name and same id (or name)."""
    name = _tag_name(tag)
    attrs = _attrs(tag)
    for key in ("id", "name"):
        value = attrs.get(key)
        if name and value:
            rx = re.compile(rf"""<{name}\b[^>]*?\s{key}\s*=\s*["']{re.escape(value)}["'][^>]*>""", re.I | re.S)
            hits = list(rx.finditer(text))
            if hits:
                return hits
    return []


# ------------------------------------------------------------------ repo files

def parse_repo(url: str) -> tuple[str, str]:
    from .agents.setup_agent import GITHUB_RE
    m = GITHUB_RE.match((url or "").strip())
    if not m:
        raise RepoFixError("That is not a GitHub repository link (e.g. https://github.com/user/repo).")
    return m.group(1), m.group(2)


def _local_copy(repo_url: str, token: str, run_dir: Path) -> Path:
    """Download the repo (git clone, or a zip if git is not installed) into workspace/."""
    from .agents import setup_agent
    old = settings.github_token
    settings.github_token = token or old
    try:
        return setup_agent._clone(repo_url, run_dir / "repo_fix.log")
    except Exception as e:
        raise RepoFixError(f"Could not download the repository: {str(e)[:200]}") from e
    finally:
        settings.github_token = old


def _source_files(root: Path) -> list[Path]:
    files = []
    for p in root.rglob("*"):
        rel = p.relative_to(root).parts
        if p.is_file() and p.suffix.lower() in SOURCE_EXT and not SKIP_DIRS.intersection(rel) \
                and p.stat().st_size <= MAX_FILE:
            files.append(p)
    # real source files first, built copies (dist/, build/) last
    return sorted(files, key=lambda p: (bool(BUILD_DIRS.intersection(p.relative_to(root).parts)), str(p)))


def _text_hash(text: str) -> str:
    """Hash of a file's text, ignoring Windows/Unix line endings (git may convert them on download)."""
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ 1) prepare (local only)

def prepare(run_dir: Path, repo_url: str, token: str) -> dict:
    owner, repo = parse_repo(repo_url)
    fixes = json.loads((run_dir / "fixes.json").read_text(encoding="utf-8")) if (run_dir / "fixes.json").exists() else []
    with_code = [x for x in fixes if (x.get("code") or {}).get("before") and (x.get("code") or {}).get("after")]
    root = _local_copy(repo_url, token, run_dir)
    files = _source_files(root)
    texts = {p: p.read_text(encoding="utf-8", errors="replace") for p in files}
    original = dict(texts)
    changed_by: dict[Path, list[str]] = {}
    applied, skipped = [], []

    for x in with_code:
        before, after = x["code"]["before"], x["code"]["after"]
        b_lines, a_lines = before.split("\n"), after.split("\n")
        matched, unmatched = [], []
        if len(b_lines) == len(a_lines) and all(l.strip().startswith("<") for l in b_lines + a_lines):
            # tag by tag: find the same element in the source and apply the attribute changes to it
            for b, a in zip(b_lines, a_lines):
                if b.strip() == a.strip():
                    continue
                ops = _ops(b, a)
                where = None
                for p in files:
                    hits = _find_tags(texts[p], b)
                    if len(hits) == 1:
                        where = (p, hits[0])
                        break
                snippet = b.strip()[:80]
                if not where:
                    unmatched.append(snippet)
                    continue
                p, hit = where
                new_tag = _apply_ops(hit.group(0), ops)
                if new_tag != hit.group(0):
                    texts[p] = texts[p][:hit.start()] + new_tag + texts[p][hit.end():]
                    changed_by.setdefault(p, []).append(x["title"])
                    matched.append(snippet)
                # Found but already matching the "Change to" attributes: neither matched nor unmatched
        elif "…" not in before:
            # AI-written change: only when the exact current code is in exactly one file
            hits = [p for p in files if texts[p].count(before.strip()) == 1]
            snippet = before.strip()[:80]
            if len(hits) == 1:
                p = hits[0]
                texts[p] = texts[p].replace(before.strip(), after.strip(), 1)
                changed_by.setdefault(p, []).append(x["title"])
                matched.append(snippet)
            else:
                unmatched.append(snippet)
        else:
            unmatched.append(before.strip()[:80])

        entry = {"title": x["title"], "priority": x.get("priority"), "why": x.get("why", "")}
        if matched and not unmatched:
            applied.append(entry)
        elif matched and unmatched:
            # Partial: some tags applied, the rest must stay visible as skipped — never as full success
            applied.append({**entry, "partial": True, "matched": matched, "unmatched": unmatched})
            skipped.append({
                "title": x["title"],
                "reason": (f"Only some of this finding's changes were found in the repository "
                           f"({len(matched)} applied, {len(unmatched)} not found) - finish the rest by hand."),
                "code": unmatched[0],
                "matched": matched,
                "unmatched": unmatched,
                "partial": True,
            })
        elif unmatched:
            skipped.append({"title": x["title"], "reason": "This code was not found in the repository (the page may be built "
                                                            "by a framework or a server template) - change it by hand.",
                            "code": unmatched[0], "unmatched": unmatched})

    out_files = []
    for p, titles in changed_by.items():
        rel = p.relative_to(root).as_posix()
        diff = "".join(difflib.unified_diff(original[p].splitlines(True), texts[p].splitlines(True),
                                            f"a/{rel}", f"b/{rel}", n=2))
        out_files.append({"path": rel, "fixes": sorted(set(titles)), "diff": diff,
                          "old_hash": _text_hash(original[p]), "content": texts[p]})
    no_code = [
        {"title": x.get("title") or "Advice", "why": (x.get("why") or x.get("fix") or "")[:400]}
        for x in fixes if x not in with_code
    ]
    plan = {
        "repo": f"{owner}/{repo}",
        "repo_url": repo_url,
        "files": out_files,
        "applied": applied,
        "skipped": skipped,
        "no_code": no_code,
        "files_scanned": len(files),
        "fixes_considered": len(with_code),
        "fixes_total": len(fixes),
        "prepared": time.time(),
    }
    (run_dir / "repo_fix_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return dict(plan) | {"files": [{k: v for k, v in f.items() if k != "content"} for f in out_files]}


# ------------------------------------------------------------------ 2) create the Pull Request (GitHub)

def _gh(method: str, path: str, token: str, **kw) -> dict:
    r = requests.request(method, f"{GH}{path}", timeout=60, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}, **kw)
    if r.status_code >= 400:
        msg = r.json().get("message", r.text[:200]) if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]
        if r.status_code in (401, 403):
            msg += " - the token needs 'Contents: write' and 'Pull requests: write' permission for this repository."
        raise RepoFixError(f"GitHub said: {msg} (HTTP {r.status_code})")
    return r.json() if r.content else {}


def create_pr(run_dir: Path, token: str, run_id: str, summary: dict | None = None) -> dict:
    plan_file = run_dir / "repo_fix_plan.json"
    if not plan_file.exists():
        raise RepoFixError("Press 'Prepare changes' first.")
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    if not plan["files"]:
        raise RepoFixError("There are no changes to send.")
    if not token:
        raise RepoFixError("A GitHub token is needed (GITHUB_TOKEN in .env, or paste one).")
    repo = plan["repo"]
    base = _gh("GET", f"/repos/{repo}", token)["default_branch"]
    sha = _gh("GET", f"/repos/{repo}/git/ref/heads/{base}", token)["object"]["sha"]
    branch = f"blow-ai/fixes-{run_id[-15:]}".replace(":", "-")
    _gh("POST", f"/repos/{repo}/git/refs", token, json={"ref": f"refs/heads/{branch}", "sha": sha})

    sent, stale = [], []
    for f in plan["files"]:
        current = _gh("GET", f"/repos/{repo}/contents/{f['path']}", token, params={"ref": branch})
        remote = base64.b64decode(current.get("content") or "").decode("utf-8", errors="replace")
        if _text_hash(remote) != f["old_hash"]:  # changed on GitHub after we downloaded it: don't overwrite
            stale.append(f["path"])
            continue
        content = f["content"].replace("\r\n", "\n")
        if "\r\n" in remote:  # keep the file's own line-ending style
            content = content.replace("\n", "\r\n")
        _gh("PUT", f"/repos/{repo}/contents/{f['path']}", token, json={
            "message": f"Blow AI: fix {', '.join(f['fixes'])[:60]}", "branch": branch, "sha": current["sha"],
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii")})
        sent.append(f["path"])
    if not sent:
        raise RepoFixError("Every file changed on GitHub since it was downloaded - press 'Prepare changes' again.")

    full = [a for a in plan["applied"] if not a.get("partial")]
    partial = [a for a in plan["applied"] if a.get("partial")]
    lines = ["Automated fixes from a **Blow AI** website test.", ""]
    if summary:
        lines += [f"Test result: **{summary.get('verdict', '')}** - {summary.get('passed', 0)} passed, "
                  f"{summary.get('failed', 0)} failed.", ""]
    if full:
        lines += ["### What this changes"] + [f"- **{a['title']}** - {a['why']}" for a in full]
    if partial:
        lines += ["", "### Partially applied (please finish by hand)"] + [
            f"- **{a['title']}** - {a['why']} (not found: {', '.join(a.get('unmatched') or [])})" for a in partial]
    # Fully skipped only (partials already listed above); keep titles unique for the hand-fix section
    hand = [s for s in plan["skipped"] if not s.get("partial")]
    if hand:
        lines += ["", "### Not changed here (please fix by hand)"] + [f"- {s['title']}" for s in hand]
    if stale:
        lines += ["", "### Skipped (changed on GitHub meanwhile)"] + [f"- `{p}`" for p in stale]
    lines += ["", "Please review every change before merging. Re-run the test after merging to confirm the fixes."]
    title = f"Blow AI: {len(full)} website fix(es)"
    if partial:
        title += f", {len(partial)} partial"
    pr = _gh("POST", f"/repos/{repo}/pulls", token, json={
        "title": title, "head": branch, "base": base,
        "body": "\n".join(lines)})
    return {"pr_url": pr.get("html_url"), "branch": branch, "files": sent, "stale": stale}
