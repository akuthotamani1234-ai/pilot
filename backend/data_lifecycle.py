"""QX-A05 test data lifecycle. Each worker gets its own synthetic records.

Records are tagged with the run id. A case starts from a known reset.
Cleanup removes only what this run created. Production customer data is refused.
"""
import re

KINDS = ("account", "cart", "order")
_RESERVED_DOMAINS = frozenset({"example.com", "example.org", "example.net"})
_TAG_UNSAFE = re.compile(r"[^a-zA-Z0-9_-]")
_PRODUCTION = frozenset({"production", "prod", "live"})


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
