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
    db = Path(path) if path else DEFAULT_DB
    db.parent.mkdir(parents=True, exist_ok=True)
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
            decided_at REAL
        )
        """
    )
    conn.commit()
    return conn


def create(kind: str, subject: str, *, detail: str = "", path: Path | None = None) -> dict:
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
    }
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO approvals (id, kind, subject, detail, status, answer, reason, created_at, decided_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["id"], row["kind"], row["subject"], row["detail"], row["status"],
             row["answer"], row["reason"], row["created_at"], row["decided_at"]),
        )
        conn.commit()
    return row


def list_approvals(*, status: str = "pending", limit: int = 50, path: Path | None = None) -> list[dict]:
    """Newest first. status=all returns every row."""
    want = (status or "pending").strip().lower()
    lim = min(200, max(1, int(limit or 50)))
    with _connect(path) as conn:
        if want == "all":
            rows = conn.execute(
                "SELECT * FROM approvals ORDER BY created_at DESC LIMIT ?", (lim,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM approvals WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (want, lim),
            ).fetchall()
    return [dict(r) for r in rows]


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
        old, new, failure_class=failure_class, approval_token=token,
    )
    if not reviewed.get("allowed"):
        return {
            "allowed": False,
            "reason": reviewed.get("reason") or "healing policy refused the repair",
        }
    return {"allowed": True, "reason": ""}


def decide_approval(approval_id: str, answer: str, *, path: Path | None = None) -> dict:
    """Apply human_review.decide and persist the outcome.

    An accepted ``heal`` still has to pass the locator-only healing policy.
    """
    with _connect(path) as conn:
        row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            raise KeyError(approval_id)
        current = dict(row)
        if current["status"] != "pending":
            return current
        verdict = decide(current["kind"], answer)
        status = "accepted" if verdict["apply"] else "rejected"
        reason = verdict["reason"]
        # No answer → rejected (safe choice); explicit reject also rejected.
        if (answer or "").strip() == "":
            status = "rejected"
        if status == "accepted" and current["kind"] == "heal":
            policy = heal_detail_allowed(current["detail"])
            if not policy["allowed"]:
                status = "rejected"
                reason = str(policy["reason"])
        decided_at = time.time()
        conn.execute(
            "UPDATE approvals SET status = ?, answer = ?, reason = ?, decided_at = ? WHERE id = ?",
            (status, (answer or "").strip(), reason, decided_at, approval_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return dict(updated)


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
