"""An isolated GitHub source snapshot pinned to a commit; never pull into a user's checkout."""
import io
import json
import stat
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote

import requests


def snapshot(repo_url: str, token: str, run_dir: Path, branch: str = "") -> Path:
    from .repo_fix import RepoFixError, _gh, parse_repo
    owner, repo = parse_repo(repo_url)
    metadata = _gh("GET", f"/repos/{owner}/{repo}", token)
    base = branch or metadata["default_branch"]
    sha = _gh("GET", f"/repos/{owner}/{repo}/git/ref/heads/{quote(base, safe='')}", token)["object"]["sha"]
    root = run_dir / ".private" / "repo_source" / uuid.uuid4().hex
    root.mkdir(parents=True)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.get(f"https://api.github.com/repos/{owner}/{repo}/zipball/{sha}",
                            headers=headers, timeout=90, stream=True)
    response.raise_for_status()
    data = bytearray()
    for chunk in response.iter_content(65536):
        data.extend(chunk)
        if len(data) > 25_000_000:
            raise RepoFixError("Repository archive exceeds the 25 MB preparation limit.")
    total, modes = 0, {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            parts = Path(entry.filename).parts[1:]
            if not parts or entry.is_dir():
                continue
            dest = (root.joinpath(*parts)).resolve()
            total += entry.file_size
            mode = entry.external_attr >> 16
            if not dest.is_relative_to(root.resolve()) or stat.S_ISLNK(mode) or total > 100_000_000:
                raise RepoFixError("Unsafe path, link or oversized content in repository archive.")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(archive.read(entry))
            modes[dest.relative_to(root.resolve()).as_posix()] = "100755" if mode & 0o111 else "100644"
    (run_dir / "repo_source.json").write_text(json.dumps({
        "repo": f"{owner}/{repo}", "base_branch": base, "base_commit": sha,
        "root": str(root.resolve()), "modes": modes}), encoding="utf-8")
    return root
