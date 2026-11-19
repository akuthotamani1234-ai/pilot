"""QX-A05 test data lifecycle. Each worker gets its own synthetic records.

Records are tagged with the run id. A case starts from a known reset.
Cleanup removes only what this run created. Production customer data is refused.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

KINDS = ("account", "cart", "order")
_RESERVED_DOMAINS = frozenset({"example.com", "example.org", "example.net"})
_TAG_UNSAFE = re.compile(r"[^a-zA-Z0-9_-]")
_PRODUCTION = frozenset({"production", "prod", "live"})
LIFECYCLE_FILE = "qx_lifecycle_state.json"


def production_environment(environment: str) -> bool:
    """True when this run is aimed at a live customer environment."""
    return (environment or "").strip().lower() in _PRODUCTION


def customer_data(value: str) -> tuple[bool, str]:
    """True when a fixture value looks like a real customer's address."""
    text = (value or "").strip()
    if "@" not in text:
        return False, ""
    domain = text.rsplit("@", 1)[-1].lower().strip(".")
    if domain in _RESERVED_DOMAINS:
        return False, ""
    return True, "production customer data is not used as fixture data"


def _safe_run(run_id: str) -> str:
    cleaned = _TAG_UNSAFE.sub("", run_id)[:48]
    return cleaned or "run"


class Lifecycle:
    """Synthetic account, cart, and order records for one run."""

    def __init__(self, run_id: str, environment: str = "test") -> None:
        if not str(run_id or "").strip():
            raise ValueError("a lifecycle needs a run id")
        if production_environment(environment):
            raise ValueError("production customer data is not used as fixture data")
        self.run_id = str(run_id).strip()
        self.environment = (environment or "test").strip().lower() or "test"
        self._tag = _safe_run(self.run_id)
        self._by_worker: dict[int, list[dict]] = {}
        self._case: dict[int, str | None] = {}

    def prepare(self, worker: int) -> list[dict]:
        """Create this worker's records and leave the worker at a known reset."""
        worker = int(worker)
        if worker < 1:
            raise ValueError("worker must be 1 or greater")
        if worker in self._by_worker:
            return [dict(row) for row in self._by_worker[worker]]
        rows = []
        for kind in KINDS:
            tag = f"qa-{self._tag}-w{worker}-{kind}"
            email = f"{tag}@example.com" if kind == "account" else ""
            rows.append({
                "run_id": self.run_id,
                "worker": worker,
                "kind": kind,
                "tag": tag,
                "email": email,
                "state": "ready",
                "environment": self.environment,
                "source": "synthetic",
            })
        self._by_worker[worker] = rows
        self._case[worker] = None
        return [dict(row) for row in rows]

    def for_worker(self, worker: int) -> list[dict]:
        """Records this worker may use. Another worker's records are not included."""
        rows = self._by_worker.get(int(worker), [])
        return [dict(row) for row in rows if row["state"] != "cleaned"]

    def snapshot(self, worker: int) -> list[dict]:
        """Every record for this worker, including ones already cleaned."""
        return [dict(row) for row in self._by_worker.get(int(worker), [])]

    def claim(self, worker: int, value: str) -> str:
        """Keep a fixture value for this worker. A real customer address is refused."""
        if int(worker) not in self._by_worker:
            raise ValueError("this worker has no records for this run")
        refused, reason = customer_data(value)
        if refused:
            raise ValueError(reason)
        return value

    def begin_case(self, worker: int, case_id: str) -> None:
        """Start a case. The worker must be sitting at a reset, with no case open."""
        worker = int(worker)
        if worker not in self._case:
            raise ValueError("this worker has no records for this run")
        if self._case[worker] is not None:
            raise ValueError("a case starts only from a known reset")
        if not str(case_id or "").strip():
            raise ValueError("a case needs an id")
        self._case[worker] = str(case_id).strip()
        for row in self._by_worker[worker]:
            if row["state"] == "ready":
                row["state"] = "in_use"

    def reset(self, worker: int) -> None:
        """Return this worker to the known starting state."""
        worker = int(worker)
        if worker not in self._case:
            raise ValueError("this worker has no records for this run")
        self._case[worker] = None
        for row in self._by_worker[worker]:
            if row["state"] == "in_use":
                row["state"] = "ready"

    def cleanup(self, worker: int | None = None) -> list[dict]:
        """Mark this run's records cleaned. Other workers stay when one worker is named."""
        cleaned = []
        for owner, rows in self._by_worker.items():
            if worker is not None and owner != int(worker):
                continue
            for row in rows:
                if row["state"] == "cleaned" or row["run_id"] != self.run_id:
                    continue
                row["state"] = "cleaned"
                cleaned.append(dict(row))
            self._case[owner] = None
        return cleaned

    def cleanup_confirmed(self, worker: int | None = None, *, remote_delete) -> dict:
        """Delete remote fixtures, then mark cleaned only when the adapter confirms.

        ``remote_delete(record) -> dict`` must return ``{"deleted": True}`` or
        ``{"deleted": False, "reason": "..."}``. Local status alone is not proof.
        """
        targets = []
        for owner, rows in self._by_worker.items():
            if worker is not None and owner != int(worker):
                continue
            for row in rows:
                if row["state"] != "cleaned" and row["run_id"] == self.run_id:
                    targets.append(row)
        confirmed, failed = [], []
        for row in targets:
            result = remote_delete(dict(row)) or {}
            if result.get("deleted"):
                row["state"] = "cleaned"
                row["cleanup_proof"] = result.get("proof") or "remote_deleted"
                confirmed.append(dict(row))
            else:
                failed.append({
                    "tag": row.get("tag"),
                    "kind": row.get("kind"),
                    "reason": result.get("reason") or "remote delete not confirmed",
                })
        owners = {int(worker)} if worker is not None else set(self._by_worker)
        for owner in owners:
            remaining = [r for r in self._by_worker.get(owner, [])
                         if r["run_id"] == self.run_id and r["state"] != "cleaned"]
            if not remaining:
                self._case[owner] = None
        return {
            "confirmed": confirmed,
            "failed": failed,
            "complete": not failed,
            "local_only": False,
        }


def account_tag_for_worker(prepared: list, worker_name: str) -> str:
    """The ready account tag for this pytest worker. gw0 is worker 1. A cleaned record is not used."""
    digits = re.sub(r"\D", "", worker_name or "")
    worker = int(digits) + 1 if digits else 1
    for pack in prepared:
        if not isinstance(pack, list):
            continue
        account = next((row for row in pack if isinstance(row, dict) and row.get("kind") == "account"), None)
        if not account or account.get("state") != "ready" or int(account.get("worker") or 0) != worker:
            continue
        return str(account.get("tag") or "")
    return ""


def plan_for_workers(run_id: str, environment: str, workers: list[int]) -> list[dict]:
    """The data plan stored with the swarm. One pack per worker, still at reset."""
    unique = sorted({int(worker) for worker in workers if int(worker) >= 1})
    if not unique:
        return []
    if production_environment(environment):
        reason = "production customer data is not used as fixture data"
        return [{"run_id": run_id, "worker": worker, "refused": reason, "records": [], "cleanup": []}
                for worker in unique]
    life = Lifecycle(run_id, environment)
    packs = []
    for worker in unique:
        records = life.prepare(worker)
        packs.append({
            "run_id": life.run_id,
            "worker": worker,
            "environment": life.environment,
            "reset": True,
            "isolated": True,
            "records": records,
            "cleanup": [row["tag"] for row in records],
        })
    return packs


def to_state(life: Lifecycle) -> dict:
    """Serialize a lifecycle for durable prepare/finish across process boundaries."""
    return {
        "run_id": life.run_id,
        "environment": life.environment,
        "workers": {
            str(worker): [dict(row) for row in rows]
            for worker, rows in life._by_worker.items()
        },
        "cases": {str(worker): case for worker, case in life._case.items()},
    }


def from_state(payload: dict) -> Lifecycle:
    """Restore a lifecycle previously written with ``to_state``."""
    life = Lifecycle(str(payload.get("run_id") or ""), str(payload.get("environment") or "test"))
    workers = payload.get("workers") if isinstance(payload.get("workers"), dict) else {}
    cases = payload.get("cases") if isinstance(payload.get("cases"), dict) else {}
    for key, rows in workers.items():
        worker = int(key)
        life._by_worker[worker] = [dict(row) for row in rows if isinstance(row, dict)]
        life._case[worker] = cases.get(key)
    return life


def save_lifecycle(run_dir: str | Path, life: Lifecycle) -> Path:
    path = Path(run_dir) / LIFECYCLE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_state(life), indent=2), encoding="utf-8")
    return path


def load_lifecycle(run_dir: str | Path, *, run_id: str = "", environment: str = "test") -> Lifecycle:
    path = Path(run_dir) / LIFECYCLE_FILE
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("run_id"):
                return from_state(payload)
        except (OSError, ValueError):
            pass
    return Lifecycle(run_id or Path(run_dir).name, environment)


def latest_created(run_dir: str | Path) -> dict[str, dict]:
    """Newest status per tag from staging ``created.jsonl``."""
    path = Path(run_dir) / "created.jsonl"
    latest: dict[str, dict] = {}
    if not path.is_file():
        return latest
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        tag = str(row.get("tag") or "").strip()
        if not tag:
            continue
        latest[tag] = dict(row)
    return latest


def ingest_created(life: Lifecycle, run_dir: str | Path) -> list[dict]:
    """Add created.jsonl tags into the lifecycle so finish cleanup can confirm them."""
    added = []
    known = {row.get("tag") for rows in life._by_worker.values() for row in rows}
    worker = 0
    for tag, row in latest_created(run_dir).items():
        if tag in known:
            continue
        status = str(row.get("status") or "created").lower()
        record = {
            "run_id": life.run_id,
            "worker": worker,
            "kind": "created",
            "tag": tag,
            "email": "",
            "state": "cleaned" if status == "deleted" else "ready",
            "environment": life.environment,
            "source": "created.jsonl",
            "what": row.get("what") or "",
            "where": row.get("where") or "",
        }
        life._by_worker.setdefault(worker, []).append(record)
        life._case.setdefault(worker, None)
        known.add(tag)
        added.append(dict(record))
    return added


def created_jsonl_delete(run_dir: str | Path):
    """Adapter: confirm remote cleanup from created.jsonl (never flip local-only)."""
    latest = latest_created(run_dir)

    def remote_delete(record: dict) -> dict:
        tag = str(record.get("tag") or "")
        row = latest.get(tag)
        if row is None:
            for candidate, payload in latest.items():
                if candidate.startswith(tag) or tag.startswith(candidate) or tag in candidate:
                    row = payload
                    if str(payload.get("status") or "").lower() == "deleted":
                        break
        if row is not None:
            if str(row.get("status") or "").lower() == "deleted":
                return {"deleted": True, "proof": f"created.jsonl:deleted:{row.get('tag') or tag}"}
            return {
                "deleted": False,
                "reason": f"created.jsonl still {row.get('status') or 'created'} for {row.get('tag') or tag}",
            }
        if record.get("source") == "synthetic":
            # Synthetic plan row never written by staging tests — no remote fixture to delete.
            return {"deleted": True, "proof": f"synthetic_unused:{tag}"}
        return {"deleted": False, "reason": f"no cleanup proof in created.jsonl for {tag}"}

    return remote_delete


def _login_landing(url: str) -> bool:
    """A sign-in page is not proof that a record was removed."""
    from urllib.parse import urlsplit

    path = urlsplit(url or "").path.lower()
    return any(part in path for part in ("/login", "/signin", "/sign-in"))


def _admin_delete_confirmed(code: int, url: str) -> bool:
    """True when the response is the delete itself or the fixture's deleted=1 landing."""
    from urllib.parse import urlsplit

    if _login_landing(url) or int(code) not in {200, 302, 303}:
        return False
    parsed = urlsplit(url or "")
    if "deleted=1" in (parsed.query or ""):
        return True
    return parsed.path.rstrip("/").endswith("/delete")


def admin_portal_delete(base_url: str):
    """Adapter: POST /users/<id>/delete on the local AdminPortal fixture."""
    import urllib.error
    import urllib.request
    from urllib.parse import urljoin

    root = (base_url or "").rstrip("/") + "/"

    def remote_delete(record: dict) -> dict:
        user_id = (
            record.get("remote_id")
            or record.get("id")
            or (record.get("meta") or {}).get("user_id")
            or ""
        )
        tag = str(record.get("tag") or "")
        if not str(user_id).strip():
            # Prefer numeric suffix from tags like user:12
            for part in reversed(tag.replace("/", ":").split(":")):
                if part.isdigit():
                    user_id = part
                    break
        if not str(user_id).strip():
            if record.get("source") == "synthetic":
                return {"deleted": True, "proof": f"synthetic_unused:{tag}"}
            return {"deleted": False, "reason": f"no AdminPortal user id for {tag}"}
        url = urljoin(root, f"users/{user_id}/delete")
        if not url.startswith(("http://127.0.0.1:", "http://localhost:")):
            return {"deleted": False, "reason": "AdminPortal adapter only allows localhost URLs"}
        req = urllib.request.Request(url, data=b"", method="POST")  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                code = int(getattr(resp, "status", None) or resp.getcode())
                final = resp.geturl()
                if _admin_delete_confirmed(code, final):
                    return {"deleted": True, "proof": f"admin_portal:deleted:{user_id}:{code}"}
                return {
                    "deleted": False,
                    "reason": f"admin_portal HTTP {code} did not confirm delete for user {user_id}",
                }
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location") if exc.headers else ""
            landed = urljoin(url, location) if location else ""
            if location and _admin_delete_confirmed(exc.code, landed):
                return {"deleted": True, "proof": f"admin_portal:deleted:{user_id}:{exc.code}"}
            return {"deleted": False, "reason": f"admin_portal HTTP {exc.code} for user {user_id}"}
        except Exception as exc:
            return {"deleted": False, "reason": f"admin_portal delete failed: {exc}"}

    return remote_delete


def demo_store_cart_delete(base_url: str, sid_cookie: str):
    """Adapter: POST /cart/remove on the local DemoStore fixture (session cookie)."""
    import urllib.error
    import urllib.parse
    import urllib.request
    from urllib.parse import urljoin

    root = (base_url or "").rstrip("/") + "/"
    cookie = (sid_cookie or "").strip()

    def remote_delete(record: dict) -> dict:
        tag = str(record.get("tag") or "")
        if record.get("source") == "synthetic":
            return {"deleted": True, "proof": f"synthetic_unused:{tag}"}
        line = record.get("line")
        if line is None:
            line = record.get("remote_id") or record.get("id")
        if line is None:
            for part in reversed(tag.replace("/", ":").split(":")):
                if part.isdigit():
                    line = part
                    break
        if line is None or str(line).strip() == "":
            return {"deleted": False, "reason": f"no DemoStore cart line for {tag}"}
        if not root.startswith(("http://127.0.0.1:", "http://localhost:")):
            return {"deleted": False, "reason": "DemoStore adapter only allows localhost URLs"}
        if not cookie.startswith("sid="):
            return {"deleted": False, "reason": "DemoStore cart delete needs sid cookie"}
        url = urljoin(root, "cart/remove")
        body = urllib.parse.urlencode({"line": str(int(line))}).encode()
        req = urllib.request.Request(  # noqa: S310
            url,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": cookie,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                code = int(getattr(resp, "status", None) or resp.getcode())
                raw = resp.read().decode("utf-8", errors="replace")
                final = resp.geturl()
                if (
                    code == 200
                    and not _login_landing(final)
                    and "Removed from your cart" in raw
                ):
                    return {"deleted": True, "proof": f"demo_store:cart_removed:{line}:{code}:{raw[:80]}"}
                return {
                    "deleted": False,
                    "reason": f"demo_store HTTP {code} did not confirm cart line {line} was removed",
                }
        except urllib.error.HTTPError as exc:
            return {"deleted": False, "reason": f"demo_store HTTP {exc.code} for cart line {line}"}
        except Exception as exc:
            return {"deleted": False, "reason": f"demo_store cart remove failed: {exc}"}

    return remote_delete


def choose_remote_delete(run_dir: str | Path, state: dict | None = None):
    """Pick AdminPortal adapter when the run targets that fixture; else created.jsonl."""
    state = state or {}
    source = str(state.get("url") or state.get("source") or "")
    portal = str(state.get("admin_portal_url") or os.getenv("ADMIN_PORTAL_URL") or "").strip()
    if portal:
        return admin_portal_delete(portal)
    if "8768" in source or "adminportal" in source.lower() or "admin-portal" in source.lower():
        # Heuristic: discover from source host
        from urllib.parse import urlparse
        parsed = urlparse(source)
        if parsed.scheme and parsed.netloc:
            return admin_portal_delete(f"{parsed.scheme}://{parsed.netloc}")
    return created_jsonl_delete(run_dir)
