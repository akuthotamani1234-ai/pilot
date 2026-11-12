# Contributing to Blow AI

How to set up the code, check a change and hand it in. What the tool does and how to use it is in
[README.md](README.md); how the code is built is in [backend/README.md](backend/README.md) and
[project-docs/02_ARCHITECTURE.md](project-docs/02_ARCHITECTURE.md).

## 1. Set up
Windows 10 / 11 with Python 3.13 (see [README, Requirements](README.md#1-requirements)).

```powershell
git clone <repository-url> blow-ai
cd blow-ai
setup\install.bat                                                  # .venv, packages, Chromium, .env from .env.example
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # + ruff (checker), vulture, httpx (server tests)
```

`.env` is yours: it is ignored by git and must never be committed (see [Secrets](#5-secrets-and-local-data)).

## 2. Check a change
```powershell
.venv\Scripts\python.exe -m ruff check .                                       # must say "All checks passed!"
.venv\Scripts\python.exe -m pytest -q -n 3 --dist loadfile -m "not slow"       # quick regression suite, a few minutes
.venv\Scripts\python.exe -m pytest -q tests/test_end_to_end.py                 # + the slow file your change touches
```
- The checker's rules are in `pyproject.toml`: errors, likely bugs (bugbear), security (bandit), sorted imports and
  modern syntax. `ruff check . --fix` fixes the simple ones. A deliberate exception is a `# noqa: <rule>` with its
  reason on the same line.
- The whole suite (330 tests, one to two hours or more on a 16 GB laptop) is for changes to the pipeline itself:
  `.venv\Scripts\python.exe -m pytest -q -n 3 --dist loadfile`. Don't edit `backend/` while it runs: its tests start
  fresh `main.py` processes that would mix two versions of the code.
- Unused code: `.venv\Scripts\python.exe -m vulture backend main.py --min-confidence 60`. Check every hit by hand:
  web API routes, settings fields, pytest hooks and Excel formatting look unused to vulture but are used.
- More about the tests, the practice websites and the accuracy benchmark: [tests/README.md](tests/README.md).

**GitHub Actions** runs the same checks: [.github/workflows/ci.yml](.github/workflows/ci.yml) runs ruff and the quick
tests on every push to `main` and every Pull Request. Start it by hand with *full* ticked to run the slow tests too.

**Updating packages:** `requirements.txt` names the app's packages; `constraints.txt` pins every installed package to
the version the tests passed with, so every PC gets the same. To move to newer versions, change them, run the whole
suite, then replace the package lines of `constraints.txt` with `.venv\Scripts\python.exe -m pip freeze`.

## 3. Coding rules
- **Rules decide, the AI only explains.** Verdicts, categories and severities come from code. The AI's answer is
  validated (`ask_structured` with a pydantic model), and the run falls back to the built-in rules if it fails.
  The one exception is written down in `agents/failure_analysis.py` (`classify`): the AI's look at a failed test's
  screenshots (`VISION`) may clear a failure as a *test mistake* or raise it to *suspect*, never to a proven bug.
- Every AI call goes through `backend/llm` (`ask_llm` / `ask_structured`): budget, retries, cost and secret removal
  happen there. The instructions sent to the AI are in `backend/llm/prompts/*.txt`.
- Never print or save a secret. Use `backend/safety.redact` for anything that may contain one.
- Never invent numbers: every number in a report is counted from the run's own files (`backend/metrics.py`).
- Every fixed mistake gets a test that fails without the fix (the `tests/test_*_lessons.py` files).
- Progress is written with `print`: the web UI reads marker lines (`::stage::`, `::page::`, `::human::`), so keep them
  working when you change the console output.
- The history of changes is the git history: say in each commit message what changed and why.
- Rules for the web page (escaping, no secrets in the browser): [frontend/README.md](frontend/README.md).

## 4. Style
- Keep the layout of the surrounding code. The code is checked by ruff but not reformatted by a formatter:
  4 spaces in Python, 2 in JavaScript / CSS / HTML, lines up to 120 characters (`.editorconfig` sets this for your
  editor).
- Comments say **why**, not what. Name the website and the run a rule came from when it fixes a real mistake.
- Type hints on new functions. No type checker is set up yet.
- Line endings: git stores LF; the `.bat` files keep CRLF (`.gitattributes`).

## 5. Secrets and local data
`.gitignore` keeps these out of the repository. Check `git status` before every commit anyway:

| Never commit | Why |
|---|---|
| `.env` | your API keys, tokens and test accounts |
| `accounts/` | test accounts the tester created (encrypted for one Windows user) |
| `runs/`, `baseline/`, `logs/`, `workspace/`, `schedules.json` | one tester's runs, screenshots and data |
| `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/` | built for one PC, or caches |

If a key or password was committed by mistake, **revoke it at the provider at once** (OpenAI, Gemini, Anthropic,
GitHub, Slack, Jira) and make a new one. Deleting the commit is not enough: the key may already have been copied.

## 6. Commits and Pull Requests
- One change per commit, with a short summary line in the imperative ("Retry the login after a lost session"), and a
  body that says why when it is not obvious.
- Work on a branch and open a Pull Request into `main`. CI must pass.
- In the Pull Request, say what changed, why, and how you checked it (which tests, which website). For a fix of a
  mistake on a real website, name the website and the run.

## 7. Known limits of the code base
- Three modules are very large: `agents/script_generator.py` (about 2,900 lines), `agents/discovery.py` (about
  2,600) and `agents/test_design.py` (about 2,000). Split them only with the full test suite as a safety net.
- Windows only: the sandbox uses a Windows Job Object and the account store uses Windows DPAPI.
- No type checker yet (the code has type hints).
