"""QX-A01 swarm handoff. Tasks are structured records, not hidden chat.

A leader task names the listing. Worker tasks name the products that will be
tested. Payment and checkout addresses are blocked tasks, never completed work.
"""
from uuid import uuid4

SCHEMA_VERSION = 1
STATUSES = frozenset({"completed", "partial", "failed", "blocked", "cancelled", "needs_review"})
ROLES = frozenset({"leader", "worker", "coverage", "oracle"})


def new_task(*, role: str, url: str, parent_task_id: str = "", scope: str = "listing",
             action_budget: int = 15, time_budget_s: int = 120, approval_required: bool = False,
             status: str = "partial", evidence: list | None = None, worker: int = 0,
             reason: str = "") -> dict:
    """One handoff. The caller fills evidence when the worker finishes."""
    return {
        "task_id": uuid4().hex,
        "parent_task_id": parent_task_id,
        "schema_version": SCHEMA_VERSION,
        "role": role,
        "url": url,
        "scope": scope,
        "action_budget": int(action_budget),
        "time_budget_s": int(time_budget_s),
        "approval_required": bool(approval_required),
        "approved": False,
        "status": status,
        "worker": int(worker),
        "reason": reason,
        "evidence": list(evidence or []),
    }


def validate_task(task: dict) -> list[str]:
    """Problems that stop this handoff from being accepted. Empty means it is well formed."""
    problems = []
    if not task.get("task_id"):
        problems.append("missing task_id")
    if task.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version is not supported")
    if task.get("role") not in ROLES:
        problems.append("role is not a swarm role")
    if not str(task.get("url") or "").strip():
        problems.append("missing url")
    if int(task.get("action_budget") or 0) <= 0:
        problems.append("action_budget must be greater than zero")
    if int(task.get("time_budget_s") or 0) <= 0:
        problems.append("time_budget_s must be greater than zero")
    if task.get("status") not in STATUSES:
        problems.append("status is not a swarm status")
    return problems


def accept_result(task: dict) -> tuple[bool, str]:
    """A finished task needs evidence. A sensitive task needs a person. Payment cannot complete."""
    problems = validate_task(task)
    if problems:
        return False, "; ".join(problems)
    status = task["status"]
    if status == "completed" and not task.get("evidence"):
        return False, "a completed task needs evidence"
    if task.get("approval_required") and status == "completed" and not task.get("approved"):
        return False, "this task needs a person before it can complete"
    if status == "completed" and task.get("reason", "").startswith("checkout"):
        return False, "checkout and payment cannot be completed"
    return True, ""


class Lease:
    """One owner per address. A second worker cannot claim it until it is released."""

    def __init__(self) -> None:
        self._owner: dict[str, str] = {}

    def claim(self, url: str, owner: str) -> bool:
        current = self._owner.get(url)
        if current is not None and current != owner:
            return False
        self._owner[url] = owner
        return True

    def release(self, url: str, owner: str) -> None:
        if self._owner.get(url) == owner:
            del self._owner[url]


def tasks_for_listing(parent_url: str, chosen: list[str], skipped: list[tuple[str, str]],
                      worker_count: int) -> list[dict]:
    """Leader task, one worker task per chosen product, and blocked tasks for the rest."""
    from .swarm import assign_workers, is_payment_url

    leader = new_task(role="leader", url=parent_url, scope="listing", status="completed",
                      evidence=[f"chose {len(chosen)} product(s)"])
    parent = leader["task_id"]
    tasks = [leader]
    lease = Lease()
    for row in assign_workers(chosen, worker_count):
        owner = f"worker-{row['worker']}"
        if not lease.claim(row["url"], owner):
            tasks.append(new_task(
                role="worker", url=row["url"], parent_task_id=parent, worker=row["worker"],
                status="blocked", reason="another worker already owns this address",
            ))
            continue
        tasks.append(new_task(
            role="worker", url=row["url"], parent_task_id=parent, worker=row["worker"],
            status="partial", reason="chosen for this sample",
        ))
    for url, reason in skipped:
        payment = is_payment_url(url) or reason.startswith("checkout")
        tasks.append(new_task(
            role="worker", url=url, parent_task_id=parent, status="blocked", reason=reason,
            approval_required=payment,
        ))
    return tasks
