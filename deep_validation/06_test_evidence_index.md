# 06 — Test evidence index

Current verification status lives in [`STATUS.md`](../STATUS.md).

## Current offline evidence (Linux)

| Check | Result |
| --- | --- |
| `pytest -m "not slow"` | 816 passed, 2 skipped, 65 slow deselected |
| `ruff check .` | Clean |
| MCP / LLM / privacy focused suites | Pass |

## Live / optional

| Check | Result |
| --- | --- |
| Android emulator demos | Summaries under `live_runs/*.md` |
| Cloud LLM providers | Not claimed without authorization |
| MCP IDE client round-trip | Requires local `requirements-mcp.txt` install + UI consent |

Historical Windows phase notes (`08`–`12`) remain for archive reading only; they are not re-run on every host.
