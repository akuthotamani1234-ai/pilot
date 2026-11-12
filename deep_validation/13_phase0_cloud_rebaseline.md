# 13 — Phase 0 cloud re-baseline (2026-11-12)

**Scope:** Documentation-only re-inspection of the Git checkout on the Cursor cloud agent.  
**No application source, tests, APIs, credentials, baselines, runs or APKs were changed.**

## Environment

| Item | Observed value |
|---|---|
| Host OS | Linux 6.12.x |
| Workspace | `/workspace` |
| Git | Present; branch `main` at `925ae2f` (`Initial commit: Blow AI`); working tree clean before this docs update |
| Python | System `python3` = **3.12.3** (no `python3.13` on PATH). Product declares `requires-python >=3.13` |
| Virtualenv | `.venv/` absent |
| `.env` | Absent (only `.env.example` present). Secrets were not opened |
| Java | OpenJDK 21 present |
| ADB / Appium | Not on PATH |
| Chrome | `/usr/local/bin/google-chrome` present |
| Runtime dirs | `runs/`, `accounts/`, `logs/` absent; `baseline/` and `workspace/` contain only `.gitkeep` |

## Source vs non-source

| Path | Role |
|---|---|
| `backend/`, `frontend/`, `main.py`, `mcp_entry.py`, `setup/`, `tests/` (excluding Gradle cache) | Product source and product tests |
| `docs/`, `project-docs/`, root status markdown | Documentation |
| `demo-apps/*.json` | Demo check configs (APKs gitignored, none present) |
| `deep_validation/` | Historical validation evidence (mostly Windows Phase 0–5) |
| `baseline/`, `workspace/` | Runtime placeholders |
| `tests/android_demo/.gradle/` | Generated Gradle cache under the demo fixture |

## Prior Windows phase claims (historical)

Root status docs and `deep_validation/08`–`12` claim Phases 0–5 completed on a Windows workstation, including serial non-slow pytest counts (751→756) and Phase 5 healing E2E. Those results are **not re-executed on this Linux host** during Phase 0.

## Cloud Phase 0 conclusions

1. The repository is already under Git; Phase 1 “establish Git tracking” is largely obsolete for this checkout.
2. Fresh verification on this host still needs a Python 3.13 environment, dependencies, Playwright browsers, and a writable pytest temp path before treating any suite as a Linux baseline.
3. Live Android verification remains blocked without ADB/Appium/device or emulator.
4. External providers (cloud LLM, GitHub, Slack, Jira) were not contacted.
5. Next owner-approved work should re-baseline tests on this environment (Phase 1-style) before advancing into Phase 6+.

## Suggested next gate

Approve **Phase 1 — Linux/cloud regression re-baseline** (venv + non-slow suite + exact counts), then decide Phase 6 (Android) vs other high-value offline phases if the emulator remains unavailable.
