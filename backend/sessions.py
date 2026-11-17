"""QX-A06 sessions. Each role has its own session, and a secret is a vault reference.

The run records which role could open a page and which role was refused.
Session expiry is a recorded state. A password is never stored on the session.
"""


class RoleBook:
    """Sessions for one run. The public view has vault references, not secrets."""

    def __init__(self, run_id: str) -> None:
        if not str(run_id or "").strip():
            raise ValueError("a session book needs a run id")
        self.run_id = str(run_id).strip()
        self._roles: dict[str, dict] = {}

    def add_role(self, role: str, vault_ref: str) -> None:
        name = str(role or "").strip()
        ref = str(vault_ref or "").strip()
        if not name:
            raise ValueError("a role needs a name")
        if not ref.startswith("vault:"):
            raise ValueError("credentials stay as vault references")
        self._roles[name] = {"vault_ref": ref, "state": "ready", "access": []}

    def record_access(self, role: str, url: str, opened: bool) -> None:
        row = self._roles.get(role)
        if row is None:
            raise ValueError("this role has no session")
        row["access"].append({"url": url, "result": "opened" if opened else "refused"})

    def expire(self, role: str) -> None:
        row = self._roles.get(role)
        if row is None:
            raise ValueError("this role has no session")
        row["state"] = "session_expired"

    def public(self) -> dict:
        """What a report may store. Vault references stay. Secret values do not."""
        return {
            "run_id": self.run_id,
            "roles": {
                role: {
                    "vault_ref": row["vault_ref"],
                    "state": row["state"],
                    "access": list(row["access"]),
                }
                for role, row in self._roles.items()
            },
        }
