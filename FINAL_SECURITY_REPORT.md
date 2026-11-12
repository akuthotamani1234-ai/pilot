# FINAL_SECURITY_REPORT.md

**Date:** 2026-11-12  
**Scope:** Static review + Phase 11 hardening + offline safety/server tests. Not a penetration test.

## Controls reviewed / strengthened

| Control | Status |
|---|---|
| Local-only UI + `X-Agentic-QA` mutating header | Preserved |
| URL / private-host / cloud-metadata blocking | Strengthened (IPv4-mapped metadata; DNS metadata in scope) |
| Generated-code sandbox / Windows Job Object fail-closed | Preserved; Linux creationflags getattr-safe |
| Sensitive run artifacts not publicly served | Expanded block list (`app.apk`, configs, auth, etc.) |
| APK upload size / Content-Length validation | Covered by tests |
| Secret redaction (`BLOWAI_SECRET_*`, contract inputs) | Covered by tests |
| Privacy local default blanks cloud providers / Slack-Jira | Preserved |
| MCP disabled without consent | Preserved |
| `.env` secrets | Not opened during this work |

## Dependency note

Pinned dependencies via `constraints.txt` were **not** auto-upgraded. `pip check`: clean at install time. A full advisory scan (e.g. `pip-audit`) was not completed in this run — track as remaining work if required for release.

## Residual risks

1. Sandbox is process/Job-Object based, **not** a container.
2. UI has **no multi-user authentication** — must stay loopback-only.
3. Testing untrusted GitHub repos still executes their code locally.
4. DNS-based metadata blocking depends on resolver behavior.

## Explicit non-goals

No multi-tenant auth, shared server, or Docker shared deployment was introduced.
