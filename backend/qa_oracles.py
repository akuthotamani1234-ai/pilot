"""Bounded, read-only backend oracles. No generated SQL execution or HTTP mutations."""

import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .qa_contracts import contract_cases, origin
from .safety import is_metadata_host


def check_http(check, approved_origins, secrets):
    if origin(check.url) not in {origin(u) for u in approved_origins} or is_metadata_host(
        urlsplit(check.url).hostname, resolve=True
    ):
        raise ValueError("API target is outside the approved scope")
    deadline = time.monotonic() + 15
    headers = {"Accept": "application/json"}
    if check.token_ref:
        headers["Authorization"] = "Bearer " + secrets[check.token_ref]
    with requests.Session() as client:
        client.trust_env = False
        with client.get(check.url, headers=headers, timeout=(3, 10), allow_redirects=False, stream=True) as response:
            assert response.status_code == check.status, f"Expected HTTP {check.status}, found {response.status_code}."
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                if time.monotonic() > deadline:
                    raise TimeoutError("The API evidence exceeded its overall response deadline")
                size += len(chunk)
                if size > 2 * 1024 * 1024:
                    raise ValueError("API evidence exceeds 2 MB")
                chunks.append(chunk)
            import json

            value = json.loads(b"".join(chunks))
    for key in check.json_pointer.split("/")[1:] if check.json_pointer else []:
        key = key.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    assert type(value) is type(check.expected) and value == check.expected, (
        f"API field {check.json_pointer or '<root>'} differs from expected {check.expected!r}; response value omitted."
    )
    return {"kind": "http", "status": check.status, "json_pointer": check.json_pointer, "matched": True}


def check_sqlite(check, database_paths):
    path = Path(database_paths[check.database_ref]).resolve(strict=True)
    deadline = time.monotonic() + 3
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2) as connection:
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1024 * 1024)
        connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 10000)
        connection.execute("PRAGMA query_only=ON")
        connection.enable_load_extension(False)
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}

        def authorize(action, first, second, _database, _trigger):
            if (
                action not in allowed
                or action == sqlite3.SQLITE_FUNCTION
                and (second or first or "").lower() in {"load_extension", "writefile", "readfile"}
            ):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        cursor = connection.execute(check.query, check.parameters)
        rows = cursor.fetchmany(2)
        if len(rows) != 1 or len(rows[0]) != 1:
            raise ValueError("A database oracle must return exactly one row and one column")
        value = rows[0][0]
    assert type(value) is type(check.expected) and value == check.expected, (
        f"Read-only database scalar differs from expected {check.expected!r}; stored value omitted."
    )
    return {"kind": "sqlite", "matched": True, "read_only": True}


def resolve_private_inputs(contract, environment=None):
    environment = os.environ if environment is None else environment
    if not contract.test_environment:
        return {"secrets": {}, "databases": {}}
    active_ids = {c["contract_id"] for c in contract_cases(contract) if not c["blocked"]}
    active_flows = [f for f in contract.flows if f.id in active_ids]
    active_checks = [c for c in contract.checks if c.id in active_ids]
    secret_refs = {s.secret_ref for f in active_flows for s in f.steps if s.secret_ref}
    secret_refs.update(c.token_ref for c in active_checks if c.token_ref)
    database_refs = {c.database_ref for c in active_checks if c.database_ref}
    missing = [name for name in secret_refs | database_refs if not environment.get(name)]
    if missing:
        raise ValueError("Configure these environment references before execution: " + ", ".join(sorted(missing)))
    return {"secrets": {k: environment[k] for k in secret_refs}, "databases": {k: environment[k] for k in database_refs}}
