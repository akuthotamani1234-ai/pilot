# Blow AI — Copilot / assistant instructions

These instructions mirror `ARCHITECTURE.md`. Follow them for every suggestion in this repository.

## Read first
- `ARCHITECTURE.md`
- `CONTRIBUTING.md`
- `backend/README.md`
- For Android: `project-docs/12_ANDROID.md`

## Where code belongs
| Work | Directory |
| --- | --- |
| Studio UI | `frontend/` |
| Pipeline agents | `backend/agents/` (register in `graph.py`, declare keys in `state.py`) |
| Android / Appium | `backend/android*.py`, `backend/templates/` |
| Safety / redaction | `backend/safety.py` |
| Tests | `tests/` |

## Hard rules
1. Rules and metrics code decide verdicts; optional LLM providers only assist.
2. Never commit secrets; never print secrets (use `redact`).
3. Do not bypass irreversible-action blocks (pay, delete, logout, checkout submission, etc.).
4. Prefer reusing existing helpers over new parallel utilities.
5. Keep new files small; do not grow already oversized agents without a dedicated, fully tested PR.
6. No AI attribution comments or `Co-authored-by` AI trailers in commits.
7. New environment variables or dependencies require `.env.example` / README / requirements updates.
