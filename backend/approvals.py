"""Gate I: durable approval queue for human_review decisions.

Studio /dashboard can list pending items and record accept/reject. No answer
keeps the safe choice (human_review.decide). Auth/hosting still open — this is
the approvals contract foundation only.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

from .human_review import WAITING, decide

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "artifacts" / "approvals.sqlite"


def _connect(path: Path | None = None) -> sqlite3.Connection:
    from .migrate import sqlite_path_is_linked
    db = Path(path) if path else DEFAULT_DB
    if sqlite_path_is_linked(db):
        raise ValueError("The approval database is a link.")
    db.parent.mkdir(parents=True, exist_ok=True)
    if sqlite_path_is_linked(db):
        raise ValueError("The approval database is a link.")
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS approvals (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            subject TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            answer TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            decided_at REAL,
            tenant_id TEXT NOT NULL DEFAULT ''
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(approvals)")}
    if "tenant_id" not in columns:
        conn.execute("ALTER TABLE approvals ADD COLUMN tenant_id TEXT NOT NULL DEFAULT ''")
    conn.commit()
    return conn


def create(kind: str, subject: str, *, detail: str = "", tenant_id: str = "", path: Path | None = None) -> dict:
    """Enqueue one approval. Unknown kinds are rejected."""
    name = (kind or "").strip().lower()
    if name not in WAITING:
        raise ValueError(f"kind must be one of {sorted(WAITING)}")
    row = {
        "id": uuid.uuid4().hex,
        "kind": name,
        "subject": (subject or "").strip() or "untitled",
        "detail": (detail or "").strip()[:2000],
        "status": "pending",
        "answer": "",
        "reason": "waiting for a person",
        "created_at": time.time(),
        "decided_at": None,
        "tenant_id": (tenant_id or "").strip(),
    }
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO approvals (id, kind, subject, detail, status, answer, reason, created_at, decided_at, tenant_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["id"], row["kind"], row["subject"], row["detail"], row["status"],
             row["answer"], row["reason"], row["created_at"], row["decided_at"], row["tenant_id"]),
        )
        conn.commit()
    return row


def list_approvals(*, status: str = "pending", limit: int = 50, tenant_id: str | None = None,
                   path: Path | None = None) -> list[dict]:
    """Newest first. status=all returns every row. A tenant id keeps other tenants out."""
    from .migrate import sqlite_path_is_linked
    db = Path(path) if path else DEFAULT_DB
    if sqlite_path_is_linked(db):
        return []
    want = (status or "pending").strip().lower()
    lim = min(200, max(1, int(limit or 50)))
    clauses, args = [], []
    if want != "all":
        clauses.append("status = ?")
        args.append(want)
    if tenant_id is not None:
        clauses.append("tenant_id = ?")
        args.append(tenant_id)
    sql = "SELECT * FROM approvals"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(lim)
    with _connect(path) as conn:
        rows = conn.execute(sql, tuple(args)).fetchall()
    return [dict(r) for r in rows]


def _heal_run_in_tenant(detail: str, tenant_id: str) -> bool:
    """A heal with a script path may write only that tenant's indexed run."""
    try:
        payload = json.loads(detail or "")
    except json.JSONDecodeError:
        return True
    if not isinstance(payload, dict):
        return True
    run_raw = str(payload.get("run_dir") or "").strip()
    if not run_raw:
        return True
    from .config import settings
    from .tenancy_store import get_run_tenant
    run_name = Path(run_raw).name
    if not run_name or run_name in {".", ".."} or get_run_tenant(run_name) != tenant_id:
        return False
    studio = Path(settings.runs_dir) / run_name
    # Resolving a symlink named like the run still matches the studio path, and the
    # write would follow it. A folder on the way to the run is the same.
    from .finalization import folder_is_linked
    if folder_is_linked(studio) or not studio.is_dir():
        return False
    try:
        resolved = Path(run_raw).resolve()
        if resolved != studio.resolve():
            return False
        resolved.relative_to(Path(settings.runs_dir).resolve())
    except (OSError, ValueError):
        return False
    return True


def heal_detail_allowed(detail: str) -> dict:
    """A heal approval may apply only when Gate E policy allows that exact diff."""
    from .healing_policy import escalation_for, issue_healing_approval, review_repair

    reason = "heal approval detail must include old_code, new_code, and failure_class"
    try:
        payload = json.loads(detail or "")
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict):
        return {"allowed": False, "reason": reason}
    old = payload.get("old_code")
    new = payload.get("new_code")
    failure_class = str(payload.get("failure_class") or "").strip()
    if not isinstance(old, str) or not isinstance(new, str) or not failure_class:
        return {"allowed": False, "reason": reason}
    decision = escalation_for(failure_class)
    token = ""
    if not decision["auto_apply"] and decision["level"] < 4:
        issued = issue_healing_approval(old, new, failure_class)
        if not issued.get("ok"):
            return {
                "allowed": False,
                "reason": issued.get("reason") or "healing approval refused",
            }
        token = str(issued.get("token") or "")
    reviewed = review_repair(
        old, new, failure_class=failure_class, approval_token=token, consume=False,
    )
    if not reviewed.get("allowed"):
        return {
            "allowed": False,
            "reason": reviewed.get("reason") or "healing policy refused the repair",
        }
    return {"allowed": True, "reason": "", "token": token}


def apply_approved_heal(detail: str, token: str = "") -> dict:
    """Write one approved repair under the run's generated tests.

    The file must already match ``old_code``. The path cannot leave that folder.
    """
    from .healing_policy import review_repair

    try:
        payload = json.loads(detail or "")
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict):
        return {"ok": False, "applied": False, "reason": "heal detail is not a repair"}
    run_raw = str(payload.get("run_dir") or "").strip()
    rel = str(payload.get("file") or "").strip()
    if not run_raw or not rel:
        return {"ok": True, "applied": False, "reason": "no script path on this approval"}
    parts = Path(rel).parts
    if Path(rel).is_absolute() or ".." in parts or not parts:
        return {"ok": False, "applied": False, "reason": "script path must stay inside the run"}
    from .finalization import folder_is_linked
    run_path = Path(run_raw)
    if folder_is_linked(run_path) or not run_path.is_dir():
        return {"ok": False, "applied": False, "reason": "script path must stay inside the run"}
    cursor = run_path
    for part in ("generated_tests", *parts):
        cursor = cursor / part
        if cursor.is_symlink():
            return {"ok": False, "applied": False, "reason": "script path must stay inside the run"}
    run_dir = run_path.resolve()
    path = cursor.resolve()
    if run_dir not in path.parents:
        return {"ok": False, "applied": False, "reason": "script path must stay inside the run"}
    if not path.is_file():
        return {"ok": False, "applied": False, "reason": "script no longer matches the approved repair"}
    old = path.read_text(encoding="utf-8")
    new = payload.get("new_code")
    if not isinstance(new, str) or old != payload.get("old_code"):
        return {"ok": False, "applied": False, "reason": "script no longer matches the approved repair"}
    reviewed = review_repair(
        old, new, failure_class=str(payload.get("failure_class") or ""),
        approval_token=token, consume=True,
    )
    if not reviewed.get("allowed"):
        return {
            "ok": False,
            "applied": False,
            "reason": reviewed.get("reason") or "healing policy refused the repair",
        }
    path.write_text(new, encoding="utf-8")
    return {"ok": True, "applied": True, "reason": ""}


def decide_approval(approval_id: str, answer: str, *, tenant_id: str | None = None,
                    path: Path | None = None) -> dict:
    """Apply human_review.decide and persist the outcome.

    An accepted ``heal`` still has to pass the locator-only healing policy.
    """
    with _connect(path) as conn:
        row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            raise KeyError(approval_id)
        current = dict(row)
        if tenant_id is not None and str(current.get("tenant_id") or "") != tenant_id:
            raise PermissionError("tenant isolation")
        if current["status"] != "pending":
            return current
        verdict = decide(current["kind"], answer)
        status = "accepted" if verdict["apply"] else "rejected"
        reason = verdict["reason"]
        # No answer → rejected (safe choice); explicit reject also rejected.
        if (answer or "").strip() == "":
            status = "rejected"
        heal_token = ""
        heal_applied = False
        if status == "accepted" and current["kind"] == "heal":
            if tenant_id is not None and not _heal_run_in_tenant(current["detail"], tenant_id):
                status = "rejected"
                reason = "tenant isolation"
            else:
                policy = heal_detail_allowed(current["detail"])
                if not policy["allowed"]:
                    status = "rejected"
                    reason = str(policy["reason"])
                else:
                    heal_token = str(policy.get("token") or "")
                    applied = apply_approved_heal(current["detail"], heal_token)
                    heal_applied = bool(applied.get("applied"))
                    if not applied.get("ok"):
                        status = "rejected"
                        reason = str(applied.get("reason") or "approved repair was not written")
                        heal_token = ""
                    elif heal_token and not heal_applied:
                        from .healing_policy import review_repair
                        payload = json.loads(current["detail"])
                        spent = review_repair(
                            payload["old_code"], payload["new_code"],
                            failure_class=str(payload.get("failure_class") or ""),
                            approval_token=heal_token, consume=True,
                        )
                        if not spent.get("allowed"):
                            status = "rejected"
                            reason = str(spent.get("reason") or "healing approval already used")
                            heal_token = ""
        decided_at = time.time()
        conn.execute(
            "UPDATE approvals SET status = ?, answer = ?, reason = ?, decided_at = ? WHERE id = ?",
            (status, (answer or "").strip(), reason, decided_at, approval_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        result = dict(updated)
        if heal_token:
            result["heal_token"] = heal_token
        result["heal_applied"] = heal_applied
        return result


def snapshot(*, path: Path | None = None) -> dict:
    """Readiness helper for Gate I. Never claims gate complete."""
    pending = list_approvals(status="pending", limit=200, path=path)
    decided = list_approvals(status="all", limit=200, path=path)
    return {
        "gate_i_approvals_ready": True,
        "gate_i_complete": False,
        "pending": len(pending),
        "total_seen": len(decided),
        "db": str(path or DEFAULT_DB),
        "reason": "Approvals queue + decide API available; auth/hosting still open",
    }


def export_json(path: Path | None = None) -> str:
    """Debug helper."""
    return json.dumps(list_approvals(status="all", limit=200, path=path), indent=2)
