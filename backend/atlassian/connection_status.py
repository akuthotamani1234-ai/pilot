"""Whether an Atlassian connection really works - a saved token is not a connection.

Every real call to Jira / Confluence (the connection test, project discovery, the status check) records its outcome
here, bound to a fingerprint of what it used (site, account e-mail, token name, and a one-way hash of the token): a
changed site, e-mail or token makes the record stale, so the state goes back to 'unverified' until Atlassian answers
again. States (per connection; Jira and Confluence are independent):

  not_configured   no token for this connection (nothing saved, none in the environment)
  unverified       a token is saved, but Atlassian has not been asked with it (or something changed since)
  connected        Atlassian answered with this exact site, account and token
  failed           Atlassian refused it (wrong / expired token, no permission) - the reason is kept
  unreachable      Atlassian could not be asked (network, rate limit, server error) - nothing is known

Nothing here ever stores the token.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS req_connection_checks (
    tenant_id TEXT NOT NULL,
    connection_id TEXT NOT NULL,
    ok INTEGER NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    at TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    PRIMARY KEY (tenant_id, connection_id)
);
"""
REFUSED = ("auth_missing", "auth_expired", "forbidden", "refused")
STALE_AFTER_S = 600  # (a verified state older than this is checked again when the UI asks to verify)
RANK = {"connected": 0, "unverified": 1, "failed": 2, "unreachable": 3, "not_configured": 4}


def connect_schema(db) -> None:
    db.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def fingerprint(conn, token: str) -> str:
    raw = "\n".join([conn.site_url, conn.email.lower(), conn.token_ref, hashlib.sha256(token.encode()).hexdigest()])
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def record(db, tenant: str, conn, token: str, ok: bool, kind: str = "", message: str = "") -> None:
    with db:
        db.execute("INSERT OR REPLACE INTO req_connection_checks (tenant_id, connection_id, ok, kind, message, at, "
                   "fingerprint) VALUES (?,?,?,?,?,?,?)",
                   (tenant, conn.id, 1 if ok else 0, kind or "", (message or "")[:300], _now(),
                    fingerprint(conn, token)))


def forget(db, tenant: str, connection_id: str) -> None:
    with db:
        db.execute("DELETE FROM req_connection_checks WHERE tenant_id = ? AND connection_id = ?",
                   (tenant, connection_id))


def state(db, tenant: str, conn, token: str) -> dict:
    """{'id', 'product', 'site_url', 'state', 'message', 'checked_at', 'age_s'} - from the stored record only."""
    base = {"id": conn.id, "product": conn.product.value if hasattr(conn.product, "value") else str(conn.product),
            "site_url": conn.site_url, "checked_at": "", "message": "", "age_s": None}
    if not token:
        return {**base, "state": "not_configured", "message": "No API token is saved for this connection."}
    r = db.execute("SELECT ok, kind, message, at, fingerprint FROM req_connection_checks WHERE tenant_id = ? AND "
                   "connection_id = ?", (tenant, conn.id)).fetchone()
    if not r or r["fingerprint"] != fingerprint(conn, token):
        return {**base, "state": "unverified",
                "message": "A token is saved, but Atlassian has not been asked with it yet."}
    try:
        age = (datetime.now(UTC) - datetime.fromisoformat(r["at"])).total_seconds()
    except ValueError:
        age = None
    out = {**base, "checked_at": r["at"], "age_s": age, "message": r["message"]}
    if r["ok"]:
        return {**out, "state": "connected"}
    return {**out, "state": "failed" if r["kind"] in REFUSED else "unreachable"}


def summary(states: list[dict], product: str) -> dict:
    """The best state of one product's connections ('not_connected' when it has none at all)."""
    mine = sorted((s for s in states if s["product"] == product), key=lambda s: RANK.get(s["state"], 9))
    if not mine:
        return {"state": "not_connected", "message": f"No {product.title()} site is connected.", "connection": ""}
    best = mine[0]
    return {"state": best["state"], "message": best["message"], "connection": best["id"],
            "checked_at": best["checked_at"]}
