# Cleanup Summary — production Git governance

Branch: `cursor/production-repo-governance-cb5b` (from `main` @ `7edc962`).
Prerequisite completed: all prior Phase 0–18 / Android work merged and pushed to **`main`**.

## Security risks

| Finding | Severity | Action |
| --- | --- | --- |
| Local `.env` exists with filled `GITHUB_TOKEN`, `SLACK_WEBHOOK_URL`, `JIRA_API_TOKEN`, `WEBHOOK_TOKEN`, etc. | High if committed | **Already gitignored / not tracked.** Do not commit. Rotate any tokens that may have leaked outside this VM. |
| `.env.example` | OK | Placeholders only; keep as the public template. |
| Hardcoded live secrets in source | None found in tracked product code | Continue using `BLOWAI_SECRET_*` / `.env` only. |

## Planned deletions / untrack

| Path | Reason |
| --- | --- |
| `.claude/` (tracked agent defs) | Tool-specific AI agent metadata; rules moved into `ARCHITECTURE.md` / `.cursorrules` |
| Untracked `artifacts/` | Local scratch (already not on main) |
| Untracked `tests/android_demo/local.properties` | Machine-local Android SDK path |
| Untracked gradle dirty state under `tests/android_demo/.gradle/` | Build cache (must stay ignored) |
| Root/`tests`/`backend` `__pycache__`, `.pytest_cache` | Already gitignored; ensure absent from commits |

**Not deleted (intentional product / evidence):** `FINAL_*.md`, `deep_validation/**` assessments, LLM provider docs (OpenAI/Anthropic/Gemini are **product features**, not authorship attribution), live-run assessment markdown.

## Planned refactors (scoped)

| Item | Plan |
| --- | --- |
| Oversized modules (`discovery.py` ~2.7k, `script_generator.py` ~2.9k, `server.py` ~1.6k, `android.py` ~1.3k) | **No mass split in this pass** (high regression risk). Document hard limits and placement rules in `ARCHITECTURE.md` for future work. |
| Naming / DRY | Enforce via architecture guardrails + existing ruff/pytest; no drive-by rewrites. |
| Dependencies | Confirm `requirements.txt` + `constraints.txt` remain the lock story; do not remove packages without unused-evidence. |

## Planned documentation / governance

| File | Action |
| --- | --- |
| `.gitignore` | Expand: Android/Gradle locals, `artifacts/`, `.claude/`, IDE leftovers |
| `README.md` | Tighten overview + folder tree + env/deploy pointers (preserve install truth) |
| `CONTRIBUTING.md` | Branching (`main` + `cursor/*-cb5b` / `feature/*`), Conventional Commits, PR checklist |
| `ARCHITECTURE.md` | Directory rules, file-size limits, UI/logic split, vibe-coding workflow |
| `.cursorrules` | Core rules mirrored for assistants |
| `.github/copilot-instructions.md` | Same core rules for Copilot |

## Proceed

Safe to apply the above without deleting product source or validation evidence.
